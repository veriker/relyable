#!/usr/bin/env python3
"""netpower.py — POWERED request-shape re-derivation over the NETWORK skills.

`netscan.py` gave a STRUCTURAL number (65% of network skills have request-build code).
`netcut.py` PROVED the mechanism on one skill by hand. This closes the gap: it actually
EXECUTES a sample of network skills offline and confirms, per skill, that the request the
code builds is re-derivable — with no hand-tailoring.

Protocol per skill (all offline; no bytes leave the box — see `_netpower_site.py`):

  1. CONSTRUCT (one direct-API call, like cold_golden): an LLM reads SKILL.md + the entry
     file and emits a runnable invocation — entry script, two argv variants that differ in
     ONE user value, fake-credential env vars — plus the doc-claimed request (host, path
     substring, expected param keys, whether auth is claimed). Or it abstains with a reason.
  2. RUN under the injected sitecustomize (frozen clock, no-op sleeps, HTTP intercepted).
  3. VERDICT from the captured request(s):
       - DETERMINISM : variant A run twice -> identical request shape (pure fn of inputs)
       - SENSITIVITY : variant B -> request changes with the changed input (anti-vacuity:
                       the request genuinely consumes the input, not a constant)
       - CONFORMANCE : captured host/path/params match the doc-claim
       - SIGNED      : an auth/signature header is present when the docs claim auth
     RE-DERIVED = determinism AND sensitivity AND conformance.
     ABSTAIN(reason) if no request is captured (exits early / unsupported lib / bad args).

HONEST SCOPE (carry to the call):
  * This powers the REQUEST cut (does the code build the documented request, offline,
    deterministically, input-sensitively). It does NOT power response-correctness or prove
    the live service — those are the parse cut (netcut_parse) and provenance, respectively.
  * Python-primary skills only (the JS minority abstains, counted honestly).
  * "Re-derived" here = request-SHAPE conformance + determinism + input-sensitivity, a
    weaker claim than netcut's independent HMAC re-derivation (which needs per-skill clock
    freezing we do generically but do not recompute the signature for).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

# reuse cold_golden's key loader + API poster (same direct-API pattern)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cold_golden import _http_post, _load_key  # noqa: E402

HERE = Path(__file__).resolve().parent
POOL = Path("/tmp/clawhub_pool")
# dir holding sitecustomize.py — Python auto-loads it at startup when on PYTHONPATH
SITE_DIR = HERE / "_netpower_hooks"
DEFAULT_MODEL = "claude-sonnet-4-6"

CONSTRUCTOR_SYSTEM = """You set up an OFFLINE test invocation of a ClawHub "skill" (a CLI \
tool). The skill makes network calls; we intercept them, so no real service is hit and \
fake credentials are fine. Your job: produce a runnable invocation and state what request \
the docs say it should build.

You are given SKILL.md and the source of the most likely entry script. Return ONE JSON \
object, no prose:

{
  "abstain": false,
  "reason": "",                      // if abstain=true, why (e.g. "needs an input file",
                                     //   "no documented request endpoint", "interactive")
  "entry": "scripts/foo.py",         // path RELATIVE to the skill dir, the script to run
  "env": {"SOME_API_KEY": "FAKETESTKEY123", ...},   // fake creds the code reads from env
  "argv_a": ["--query", "alpha-token-AAA", "--limit", "5"],   // a full, valid invocation
  "argv_b": ["--query", "beta-token-BBB",  "--limit", "5"],   // SAME shape, ONE value
                                     //   changed (here --query) so the request must change
  "sensitive_value_a": "alpha-token-AAA",   // the distinctive value in argv_a that should
  "sensitive_value_b": "beta-token-BBB",    //   appear in the built request (url/params)
  "doc_host": "api.example.com",     // host the docs say it calls ("" if unknown)
  "doc_path_substr": "/v1/search",   // a path fragment the docs name ("" if unknown)
  "expected_param_keys": ["q", "limit"],    // query/body keys the docs imply ([] if none)
  "claims_auth": true                // do the docs say it needs an API key / signs requests?
}

Rules:
- Pick argv that will REACH a network call (provide all REQUIRED args the entry parses).
- argv_a and argv_b must differ in exactly ONE user-supplied value; keep everything else
  identical. Choose distinctive values (e.g. AAA/BBB) so they are findable in the request.
- Use the env var names the code actually reads. Invent fake values.
- If the skill cannot be driven to a network call without a real file/service/interactive
  input, or builds no documented request, set abstain=true with a short reason.
- Output ONLY the JSON object."""


def find_entry(skill_dir: Path) -> Path | None:
    """Most likely CLI entry: a .py with __main__ or argparse, prefer shallow + named cli/main."""
    cands = []
    for p in skill_dir.rglob("*.py"):
        if "node_modules" in p.parts or p.name.startswith("_netpower"):
            continue
        try:
            txt = p.read_text(errors="replace")
        except Exception:
            continue
        score = 0
        if "__main__" in txt:
            score += 5
        if "argparse" in txt or "click" in txt or "sys.argv" in txt:
            score += 3
        if p.name in ("cli.py", "main.py", "__main__.py"):
            score += 3
        if (
            "requests" in txt
            or "urllib" in txt
            or "httpx" in txt
            or "http.client" in txt
        ):
            score += 2
        score -= len(p.relative_to(skill_dir).parts)  # prefer shallow
        if score > 0:
            cands.append((score, p))
    if not cands:
        return None
    cands.sort(key=lambda t: -t[0])
    return cands[0][1]


def construct(skill_dir: Path, entry: Path, api_key: str, model: str) -> dict:
    skill_md = ""
    for name in ("SKILL.md", "skill.md", "README.md"):
        f = skill_dir / name
        if f.exists():
            skill_md = f.read_text(errors="replace")[:6000]
            break
    full = entry.read_text(errors="replace")
    # Always include the CLI/__main__ region even if it sits past the head cutoff — that is
    # where argv parsing lives, and truncating it makes the constructor misjudge a CLI as a
    # "library module".
    entry_src = full[:8000]
    mi = full.find("if __name__")
    if mi > 8000:
        entry_src += "\n# ... [elided] ...\n" + full[mi - 600 : mi + 2500]
    listing = "\n".join(
        f"  - {p.relative_to(skill_dir)}"
        for p in sorted(skill_dir.rglob("*.py"))[:40]
        if "node_modules" not in p.parts
    )
    user = (
        f"ENTRY SCRIPT (relative path): {entry.relative_to(skill_dir)}\n\n"
        f"ALL .py FILES:\n{listing}\n\n"
        f"--- SKILL.md ---\n{skill_md}\n\n"
        f"--- ENTRY SOURCE ({entry.name}) ---\n{entry_src}\n"
    )
    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": CONSTRUCTOR_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    resp = _http_post(api_key, payload)
    text = "".join(
        b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"
    )
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        return {"abstain": True, "reason": "constructor returned no JSON"}
    try:
        return json.loads(text[s : e + 1])
    except Exception as ex:
        return {"abstain": True, "reason": f"constructor JSON parse: {ex}"}


def run_capture(
    skill_dir: Path, entry: Path, env_extra: dict, argv: list, rec: Path
) -> list:
    """Run the entry as a subprocess under the interceptor; return captured requests."""
    import os

    rec.unlink(missing_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{SITE_DIR}:{env.get('PYTHONPATH', '')}"
    env["NETPOWER_REC"] = str(rec)
    env.update({k: str(v) for k, v in (env_extra or {}).items()})
    interp = [sys.executable]
    if entry.suffix in (".js", ".mjs"):
        interp = ["node"]
    try:
        subprocess.run(
            interp + [str(entry)] + [str(a) for a in argv],
            cwd=str(skill_dir),
            env=env,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    out = []
    if rec.exists():
        for line in rec.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _body_keys(req: dict) -> list:
    body = req.get("body", "")
    if not body:
        return []
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            return list(obj.keys())
    except Exception:
        pass
    # form-encoded body
    try:
        return [k for k, _ in parse_qsl(body)]
    except Exception:
        return []


def shape(req: dict) -> dict:
    parts = urlsplit(req.get("url", ""))
    qkeys = [k for k, _ in parse_qsl(parts.query)]
    return {
        "method": req.get("method", "GET"),
        "host": parts.netloc,
        "path": parts.path,
        "param_keys": sorted(qkeys),
        "all_keys": sorted(set(qkeys) | set(_body_keys(req))),  # query + POST body
    }


def _auth_header(req: dict) -> bool:
    keys = " ".join(req.get("headers", {}).keys()).lower()
    return any(
        t in keys
        for t in (
            "authorization",
            "sign",
            "api-key",
            "apikey",
            "access-key",
            "token",
            "x-api",
        )
    )


def _external(reqs: list) -> list:
    return [
        r
        for r in reqs
        if urlsplit(r.get("url", "")).netloc not in ("", "localhost", "127.0.0.1")
    ]


def adjudicate(skill_dir: Path, entry: Path, spec: dict, rec: Path) -> dict:
    env, argv_a, argv_b = (
        spec.get("env", {}),
        spec.get("argv_a", []),
        spec.get("argv_b", []),
    )
    a1 = _external(run_capture(skill_dir, entry, env, argv_a, rec))
    a2 = _external(run_capture(skill_dir, entry, env, argv_a, rec))
    b = _external(run_capture(skill_dir, entry, env, argv_b, rec))
    if not a1:
        return {
            "verdict": "ABSTAIN",
            "reason": "no external request captured (exits before call / unsupported)",
        }

    # pick the request matching the documented host, else the first external one
    doc_host = (spec.get("doc_host") or "").lower()

    def pick(reqs):
        if doc_host:
            for r in reqs:
                if doc_host in urlsplit(r["url"]).netloc.lower():
                    return r
        return reqs[0]

    r_a1, r_a2 = pick(a1), pick(a2)
    determinism = shape(r_a1) == shape(r_a2)

    # sensitivity: changed input value appears in B's request and not identically in A,
    # OR the built request shape/values differ between A and B.
    va = str(spec.get("sensitive_value_a", ""))
    vb = str(spec.get("sensitive_value_b", ""))
    blob_a = json.dumps(r_a1)
    sensitivity = False
    if b:
        r_b = pick(b)
        blob_b = json.dumps(r_b)
        if va and vb:
            sensitivity = (va in blob_a) and (vb in blob_b) and (vb not in blob_a)
        if not sensitivity:
            sensitivity = blob_a != blob_b  # request changed with the input at all

    sh = shape(r_a1)
    host_ok = (not doc_host) or (doc_host in sh["host"].lower())
    path_substr = (spec.get("doc_path_substr") or "").lower()
    path_ok = (not path_substr) or (path_substr in sh["path"].lower())
    exp_keys = [k.lower() for k in spec.get("expected_param_keys", [])]
    got_keys = [k.lower() for k in sh["all_keys"]]  # query + POST body keys
    keys_ok = (not exp_keys) or (
        sum(k in got_keys for k in exp_keys) >= max(1, len(exp_keys) // 2)
    )
    conformance = host_ok and path_ok and keys_ok
    signed = _auth_header(r_a1)

    rederived = determinism and sensitivity and conformance
    return {
        "verdict": "RE-DERIVED" if rederived else "WEAK",
        "determinism": determinism,
        "sensitivity": sensitivity,
        "conformance": conformance,
        "host_ok": host_ok,
        "path_ok": path_ok,
        "keys_ok": keys_ok,
        "signed": signed,
        "claims_auth": bool(spec.get("claims_auth")),
        "captured_shape": sh,
        "n_external_requests": len(a1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--slugs",
        nargs="*",
        help="explicit slugs (default: all request-reclaimable py skills)",
    )
    ap.add_argument("--limit", type=int, default=0, help="cap number of skills")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=str(HERE / "NETPOWER_RUN.json"))
    args = ap.parse_args()

    if args.slugs:
        slugs = args.slugs
    else:
        scan = json.load(open(HERE / "NETCUT_SCAN.json"))
        slugs = [r["slug"] for r in scan["rows"] if r.get("R")]
    if args.limit:
        slugs = slugs[: args.limit]

    api_key = _load_key()
    rec = Path("/tmp/netpower_rec.jsonl")
    results = []
    for i, slug in enumerate(slugs, 1):
        d = POOL / slug
        if not d.exists():
            d = POOL / slug.replace("/", "__")
        if not d.exists():
            results.append(
                {"slug": slug, "verdict": "ABSTAIN", "reason": "no source on disk"}
            )
            print(f"[{i}/{len(slugs)}] {slug:46s} ABSTAIN (no source)")
            continue
        entry = find_entry(d)
        if entry is None:
            results.append(
                {"slug": slug, "verdict": "ABSTAIN", "reason": "no python entry"}
            )
            print(f"[{i}/{len(slugs)}] {slug:46s} ABSTAIN (no py entry)")
            continue
        try:
            spec = construct(d, entry, api_key, args.model)
        except Exception as ex:
            results.append(
                {"slug": slug, "verdict": "ABSTAIN", "reason": f"construct error: {ex}"}
            )
            print(f"[{i}/{len(slugs)}] {slug:46s} ABSTAIN (construct error)")
            continue
        if spec.get("abstain"):
            results.append(
                {
                    "slug": slug,
                    "verdict": "ABSTAIN",
                    "reason": spec.get("reason", "constructor abstained"),
                }
            )
            print(
                f"[{i}/{len(slugs)}] {slug:46s} ABSTAIN ({spec.get('reason', '')[:48]})"
            )
            continue
        try:
            entry_abs = (
                (d / spec["entry"])
                if not str(spec["entry"]).startswith("/")
                else Path(spec["entry"])
            )
            if not entry_abs.exists():
                entry_abs = entry
            res = adjudicate(d, entry_abs, spec, rec)
        except Exception as ex:
            res = {"verdict": "ABSTAIN", "reason": f"run error: {ex}"}
        res["slug"] = slug
        res["entry"] = str(spec.get("entry", entry.name))
        results.append(res)
        v = res["verdict"]
        extra = ""
        if v in ("RE-DERIVED", "WEAK"):
            extra = (
                f"det={res['determinism']} sens={res['sensitivity']} "
                f"conf={res['conformance']} signed={res['signed']} "
                f"host={res['captured_shape']['host']}"
            )
        else:
            extra = res.get("reason", "")[:60]
        print(f"[{i}/{len(slugs)}] {slug:46s} {v:11s} {extra}")

    n = len(results)
    rederived = [r for r in results if r["verdict"] == "RE-DERIVED"]
    weak = [r for r in results if r["verdict"] == "WEAK"]
    abstain = [r for r in results if r["verdict"] == "ABSTAIN"]
    ran = [r for r in results if r["verdict"] in ("RE-DERIVED", "WEAK")]
    print(
        f"\n{'=' * 64}\nPOWERED request-shape re-derivation, n={n} request-reclaimable skills"
    )
    print(
        f"  RE-DERIVED (det + sensitive + doc-conformant)  : {len(rederived)}/{n} = {len(rederived) / n * 100:.0f}%"
    )
    print(f"  WEAK (ran + captured, missed >=1 criterion)    : {len(weak)}/{n}")
    print(f"  ABSTAIN (couldn't drive to an offline request) : {len(abstain)}/{n}")
    if ran:
        print(
            f"  conditional on RAN ({len(ran)}): RE-DERIVED = {len(rederived)}/{len(ran)} = {len(rederived) / len(ran) * 100:.0f}%"
        )
        signed = [r for r in ran if r.get("signed")]
        print(
            f"  of those that ran, carry an auth/signature header: {len(signed)}/{len(ran)}"
        )

    Path(args.out).write_text(json.dumps({"n": n, "results": results}, indent=2))
    print(f"\n[wrote {args.out}]")
    print(
        "\nHONEST: powers the REQUEST cut (offline, deterministic, input-sensitive,\n"
        "doc-conformant request-build) — NOT response-correctness or service liveness."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
