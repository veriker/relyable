#!/usr/bin/env python3
"""netscan.py — size the re-derivable boundary skeleton inside NETWORK skills.

netcut.py PROVES that one network skill (`dex-quote`) has a deterministic request-build
half and a pure parse half, both re-derivable offline against a frozen boundary. This
sizes how common that structure is across the 62 NETWORK-classified skills in the
seed-11 / 194-skill pool (CLASSIFY_POOL.json).

PURELY MECHANICAL — no LLM, no API spend, no network. For each skill's source we detect:

  R (request-build skeleton present): non-trivial local code that constructs the request
      from inputs — URL/path assembly, query/param building (urlencode / params=),
      and/or request signing (hmac / signature / OK-ACCESS-SIGN / X-Signature). A single
      constant URL with no param/sign logic does NOT count (nothing to re-derive).

  P (pure parse/transform present): the response is taken apart, not just relayed —
      field extraction off a parsed body (resp.json()[...] / data["..."] / .get("...")),
      a *.from_api / parse_* constructor, dataclass assembly, scoring/ranking/formatting
      over fetched fields, or a summary/report builder.

  PASSTHROUGH: makes a call but returns/prints the body verbatim with no field access —
      no local function to re-derive (stays in provenance's lane).

A skill is RECLAIMABLE if it has R or P. This is a STRUCTURAL upper bound on what a
boundary-pinning golden could check — not a proof each one re-derives (that needs a
per-skill harness like netcut). dex-quote is the existence proof that the structure pays
out into a real, mutation-backed re-derivation.

Honest scope: regex over source is coarse. We report the signal, the per-skill hits, and
hand-auditable evidence strings so the number is inspectable, not a black box.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

POOL = Path("/tmp/clawhub_pool")
HERE = Path(__file__).resolve().parent
CLASSIFY = HERE / "CLASSIFY_POOL.json"

CODE_EXT = {".py", ".js", ".mjs", ".ts", ".sh"}

# --- signal patterns (language-agnostic-ish; biased to py/js which dominate) -----------
SIGN = re.compile(
    r"hmac|hashlib\.sha|createHmac|signature|x-signature|ok-access-sign|"
    r"\bsign\s*\(|_sign\b|sign_request|generate_signature",
    re.I,
)
PARAM_BUILD = re.compile(
    r"urlencode|urllib\.parse\.urlencode|URLSearchParams|params\s*=\s*\{|"
    r"querystring|\?\$\{|params\.append|\.set\([\"']",
    re.I,
)
URL_ASSEMBLE = re.compile(
    r"f[\"'].*https?://|f[\"'].*\{[^}]*BASE_URL|BASE_URL\s*\+|"
    r"`https?://\$\{|\+\s*request_path|urljoin\(",
    re.I,
)
# parse / transform of a fetched body
FROM_API = re.compile(
    r"def\s+from_api|\.from_api\(|def\s+parse_|def\s+_parse|from_json", re.I
)
FIELD_EXTRACT = re.compile(
    r"\.json\(\)\s*[\.\[]|resp(?:onse)?\.json\(\)|data\[[\"']|"
    r"\.get\([\"'][a-zA-Z]|result\[[\"']|\[[\"']data[\"']\]",
    re.I,
)
TRANSFORM = re.compile(
    r"def\s+summary|def\s+format_|sorted\(|\.sort\(|score|rank|"
    r"def\s+to_|def\s+build_report|dataclass",
    re.I,
)
# passthrough: body returned/printed verbatim
PASSTHROUGH = re.compile(
    r"return\s+resp(?:onse)?\.json\(\)\s*$|print\(\s*resp(?:onse)?\.json\(\)\s*\)|"
    r"console\.log\([^)]*await[^)]*\.json\(\)\)|return\s+await\s+\w+\.json\(\)",
    re.I | re.M,
)
HTTP_CALL = re.compile(
    r"requests\.(get|post|put|delete)|session\.(get|post)|urlopen|http\.client|"
    r"fetch\(|axios|httpx|urllib\.request|curl\b",
    re.I,
)
# The skill's real OUTPUT is produced by a remote model (LLM / vision / image-gen), not
# by local parsing of a structured response. The request half is still re-derivable, but
# the "parse" half is exogenous (model output), so P must NOT count for these.
LLM_OUTPUT = re.compile(
    r"chat/completions|/v1/chat|messages\.create|generateContent|"
    r"image[_-]?generat|text2image|vision|ocr|大模型|生成图|图像识别|识别|"
    r"dashscope|qwen|gpt-4|gemini|claude-|stable-?diffusion|dall-?e|elevenlabs|tts",
    re.I,
)
# A boilerplate utility file (shared template) — its casing/date/http helpers trip the
# transform/param signals without being skill-specific boundary logic. Down-weight it.
UTIL_FILE = re.compile(
    r"(?:^|/)(util|utils|_common|common|helpers?|_http|sdk)\.[a-z]+$", re.I
)
# Named-field extraction off a response, in a NON-util file, is the trustworthy parse tell.
NAMED_FIELD = re.compile(
    r"\.get\([\"'][a-zA-Z][\w]{2,}[\"']|\[[\"'][a-zA-Z][\w]{2,}[\"']\]", re.I
)


def network_slugs() -> list[str]:
    rows = json.load(open(CLASSIFY))["rows"]
    return [r["slug"] for r in rows if r["category"] == "NETWORK"]


def read_source(skill_dir: Path):
    """Return (all_source, non_util_source). Util/boilerplate files are split out so
    their casing/http helpers don't masquerade as skill-specific parse logic."""
    allc, nonutil = [], []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.suffix in CODE_EXT and "node_modules" not in p.parts:
            try:
                txt = p.read_text(errors="replace")
            except Exception:
                continue
            allc.append(txt)
            if not UTIL_FILE.search(p.name):
                nonutil.append(txt)
    return "\n".join(allc), "\n".join(nonutil)


def classify(src: str, nonutil: str) -> dict:
    has_http = bool(HTTP_CALL.search(src))
    has_sign = bool(SIGN.search(src))
    has_param = bool(PARAM_BUILD.search(src))
    has_urlasm = bool(URL_ASSEMBLE.search(src))
    # request-build skeleton: signing, OR (param-building AND/OR url-assembly). Robust:
    # even an LLM/vision skill builds a deterministic, re-derivable request.
    R = has_sign or has_param or has_urlasm

    llm_out = bool(LLM_OUTPUT.search(src))
    has_fromapi = bool(FROM_API.search(src))
    # trustworthy parse tell: a real constructor/parser, OR named-field extraction that
    # lives in a NON-util file AND co-occurs with a transform there.
    strict_extract = bool(NAMED_FIELD.search(nonutil)) and bool(
        TRANSFORM.search(nonutil)
    )
    P_raw = has_fromapi or strict_extract
    # if the output is model-generated, the "parse" is exogenous -> P does not count.
    P = P_raw and not llm_out

    passthrough = bool(PASSTHROUGH.search(src)) and not P
    return {
        "has_http": has_http,
        "R": R,
        "P": P,
        "P_raw": P_raw,
        "llm_out": llm_out,
        "sign": has_sign,
        "param": has_param,
        "url_asm": has_urlasm,
        "from_api": has_fromapi,
        "strict_extract": strict_extract,
        "passthrough": passthrough,
        "reclaimable": (R or P) and not passthrough,
        "both": R and P,
    }


def main() -> int:
    slugs = network_slugs()
    rows = []
    for slug in slugs:
        d = POOL / slug
        if not d.exists():
            d = POOL / slug.replace("/", "__")
        src, nonutil = read_source(d) if d.exists() else ("", "")
        c = (
            classify(src, nonutil)
            if src
            else {
                "has_http": False,
                "R": False,
                "P": False,
                "P_raw": False,
                "llm_out": False,
                "reclaimable": False,
                "both": False,
                "passthrough": False,
                "no_source": True,
            }
        )
        c["slug"] = slug
        c["bytes"] = len(src)
        rows.append(c)

    n = len(rows)
    with_src = [r for r in rows if r["bytes"] > 0]
    req = [r for r in rows if r["R"]]  # request-build re-derivable
    parse = [r for r in rows if r["P"]]  # parse re-derivable (strict)
    both = [r for r in rows if r.get("both")]
    req_only = [r for r in rows if r["R"] and not r["P"]]
    reclaim = [r for r in rows if r["reclaimable"]]
    passth = [r for r in rows if r.get("passthrough")]
    signed = [r for r in rows if r.get("sign")]
    llm_parse_lost = [r for r in rows if r.get("P_raw") and r.get("llm_out")]

    def pct(k):
        return f"{k}/{n} = {k / n * 100:.0f}%"

    print(
        f"NETWORK skills scanned: {n}  (source recovered for {len(with_src)})\n{'=' * 60}"
    )
    print(
        "  THE ROBUST CUT — request-build re-derivable (signed or param/URL assembly):"
    )
    print(f"    request-shape golden possible                  : {pct(len(req))}")
    print(f"      of which carry request SIGNING (HMAC etc.)   : {pct(len(signed))}")
    print(
        "  THE NARROW CUT — parse re-derivable (real local transform, NOT model output):"
    )
    print(f"    parse/cassette golden possible (strict)        : {pct(len(parse))}")
    print(
        f"      excluded: parse is model-generated (LLM/vision): {len(llm_parse_lost)} "
        f"skills had parse-shaped code but emit model output"
    )
    print(f"    BOTH halves (dex-quote-like, strongest)        : {pct(len(both))}")
    print(f"\n  RECLAIMABLE at all (request OR parse)            : {pct(len(reclaim))}")
    print(f"  PASSTHROUGH (verbatim body, reclaim nothing)     : {pct(len(passth))}")
    print(
        f"  no local boundary code detected                  : "
        f"{pct(n - len(reclaim) - len(passth))}"
    )

    print("\n  BOTH-halves skills (request + real local parse — strongest targets):")
    for r in both:
        ev = [
            k
            for k in ("sign", "param", "url_asm", "from_api", "strict_extract")
            if r.get(k)
        ]
        print(f"    + {r['slug']:46s} [{','.join(ev)}]")

    print("\n  request-build-only (request-shape golden, no cassette needed):")
    for r in req_only[:20]:
        ev = [k for k in ("sign", "param", "url_asm") if r.get(k)]
        tag = " (LLM/vision output)" if r.get("llm_out") else ""
        print(f"    + {r['slug']:46s} [{','.join(ev)}]{tag}")

    out = HERE / "NETCUT_SCAN.json"
    out.write_text(
        json.dumps(
            {
                "n": n,
                "rows": rows,
                "summary": {
                    "reclaimable": len(reclaim),
                    "request_rederivable": len(req),
                    "parse_rederivable_strict": len(parse),
                    "both": len(both),
                    "req_only": len(req_only),
                    "signed": len(signed),
                    "passthrough": len(passth),
                    "parse_lost_to_llm_output": len(llm_parse_lost),
                },
            },
            indent=2,
        )
    )
    print(f"\n[wrote {out.name}]")
    print(
        "\nNOTE: structural upper bound (regex over source), not a per-skill re-derivation.\n"
        "dex-quote (BOTH) is the proven existence case — see netcut.py (4/4 mutation kill)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
