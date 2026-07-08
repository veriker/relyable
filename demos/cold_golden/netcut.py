#!/usr/bin/env python3
"""netcut.py — boundary-pinning re-derivation for NETWORK skills.

The cold_golden runs classified ~69% of code-bearing ClawHub skills as NETWORK and
abstained on all of them ("behaviour is exogenous to the code"). That verdict is too
coarse. A network skill is a *pipeline*:

    build_request(input)  ->  call(remote)  ->  parse/transform(response)  ->  output
        ^deterministic         ^exogenous        ^deterministic

Only the middle arrow lives off-box. The two ends are ordinary local functions — and
that is where the auth-signing, param-encoding, amount-conversion and field-extraction
logic (and the bugs) live. This harness pins the two deterministic ends by treating the
network boundary as frozen:

  CUT 1 — request shape (NO recorded response needed). Freeze the clock + a fixed dummy
          secret, intercept the HTTP call, and capture the exact request the code builds
          (method, host, path, sorted query, signature). Re-run -> byte-identical means
          the request is a deterministic function of (inputs, clock, key). Re-derivation
          = "does the code build the request the docs claim", checkable offline.

  CUT 2 — response parse (boundary-pinned / cassette). Feed ONE recorded (request,
          response) pair; check the parse/transform produces the documented output.
          Deterministic given the frozen response.

Both goldens carry an anti-vacuity (mutation) gate: a golden that survives a mutation of
the code it supposedly checks is not load-bearing. Same doctrine as cold_golden /
relyable's prove gate — kills-mutants proves NON-VACUOUS, not correct-spec.

HONEST CEILING (state it on the call):
  * This does NOT prove the live service is up / authentic / still returns that shape —
    that is provenance + a contract test, a different axis (ClawHub `verify`).
  * The cassette is author-attested input, exactly like a Tier-0 golden. Re-derivation
    proves the code transforms the recorded boundary as claimed, never that the recording
    is representative.
  * Pure passthroughs (`return requests.get(url).json()`) reclaim nothing — no local
    function to re-derive; they stay in provenance's lane.

This file demonstrates the mechanism end-to-end on one clean network skill (`dex-quote`,
an OKX DEX aggregator client with HMAC-signed requests + pure parsers). `netscan.py`
sizes how many of the 62 sampled network skills carry a re-derivable boundary skeleton.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

POOL = Path("/tmp/clawhub_pool")
DEX = POOL / "dex-quote" / "scripts" / "dex_quote.py"

# A frozen instant so the HMAC timestamp (the one exogenous input to request-build) is
# pinned and the whole request becomes a pure function of the inputs + the dummy secret.
FROZEN = datetime(2026, 6, 21, 12, 0, 0, 123000, tzinfo=timezone.utc)

# Deterministic dummy credentials — never a real key. The point is reproducibility, not
# auth: a fixed secret makes the HMAC signature itself re-derivable.
DUMMY = dict(api_key="AKID-TEST", secret_key="SECRET-TEST", passphrase="PASS-TEST")

# Fixed call inputs for the demonstration (1 ETH -> USDC on Ethereum).
CALL = dict(
    chain_index="1",
    from_token="0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    to_token="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    human_amount=1.0,
    from_decimals=18,
)

# ONE recorded OKX response (cassette). Author-attested input; pins the parse boundary.
CASSETTE = {
    "code": "0",
    "data": [
        {
            "chainIndex": "1",
            "fromToken": {
                "tokenSymbol": "ETH",
                "tokenContractAddress": "0xeeee...",
                "decimal": "18",
                "tokenUnitPrice": "3500.0",
                "isHoneyPot": False,
                "taxRate": "0",
            },
            "toToken": {
                "tokenSymbol": "USDC",
                "tokenContractAddress": "0xa0b8...",
                "decimal": "6",
                "tokenUnitPrice": "1.0",
                "isHoneyPot": False,
                "taxRate": "0",
            },
            "fromTokenAmount": "1000000000000000000",
            "toTokenAmount": "3498200000",
            "tradeFee": "2.10",
            "estimateGasFee": "120000",
            "priceImpactPercent": "0.05",
            "swapMode": "exactIn",
            "dexRouterList": [
                {
                    "dexProtocol": {"dexName": "Uniswap V3", "percent": "100"},
                    "fromToken": {"tokenSymbol": "ETH"},
                    "toToken": {"tokenSymbol": "USDC"},
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Boundary harness: freeze clock + intercept the one network call.
# ---------------------------------------------------------------------------


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D401 - shim
        return FROZEN if tz is None else FROZEN.astimezone(tz)


@dataclass
class CapturedRequest:
    method: str
    host: str
    path: str
    query: list  # sorted (k, v) pairs — order-independent
    signature: str | None
    has_sign_header: bool

    def shape(self) -> dict:
        """The re-derivable request descriptor (what we pin)."""
        return {
            "method": self.method,
            "host": self.host,
            "path": self.path,
            "query_keys": sorted(k for k, _ in self.query),
            "query": self.query,
            "signature": self.signature,
        }


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self):
        return copy.deepcopy(self._payload)

    def raise_for_status(self):
        return None


def load_module(path: Path, name: str = "dex_quote") -> types.ModuleType:
    """Import a skill module from a file path, isolated (fresh each call for mutation)."""
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_boundary(source: str, *, cassette: dict | None = None):
    """Execute dex-quote's get_quote() with the clock frozen and the net intercepted.

    Returns (CapturedRequest, QuoteResult-or-None, summary-or-None). No bytes leave the
    process. `source` is the (possibly mutated) module source.
    """
    # Write the (possibly mutated) source to a throwaway file and import it.
    tmp = POOL / "dex-quote" / "scripts" / "_netcut_tmp.py"
    tmp.write_text(source)
    try:
        mod = load_module(tmp, name="dex_quote_under_test")
    finally:
        tmp.unlink(missing_ok=True)

    # Freeze the clock the request signer reads.
    mod.datetime = _FrozenDateTime

    captured: dict = {}

    def fake_get(self, url, headers=None, timeout=None, **kw):
        parts = urlsplit(url)
        sign = (headers or {}).get("OK-ACCESS-SIGN")
        captured["req"] = CapturedRequest(
            method="GET",
            host=parts.netloc,
            path=parts.path,
            query=sorted(parse_qsl(parts.query)),
            signature=sign,
            has_sign_header=sign is not None,
        )
        return _FakeResponse(
            cassette if cassette is not None else {"code": "0", "data": [{}]}
        )

    # Intercept the only exogenous arrow.
    import requests

    orig = requests.Session.get
    requests.Session.get = fake_get
    try:
        client = mod.OKXDexQuoteClient(**DUMMY)
        result = None
        summary = None
        if cassette is not None:
            result = client.get_quote(**CALL)
            summary = result.summary()
        else:
            try:
                client.get_quote(**CALL)
            except Exception:
                pass  # request was captured before any parse failure
        return captured.get("req"), result, summary
    finally:
        requests.Session.get = orig


# ---------------------------------------------------------------------------
# Independent re-derivation of the request signature (trust nothing the code does).
# ---------------------------------------------------------------------------


def independent_signature(request_path: str) -> str:
    """Re-derive the OKX HMAC signature from the docs' stated algorithm, in OUR code.

    The skill docs (and OKX public API docs) state: sign = base64(HMAC-SHA256(secret,
    timestamp + method + requestPath)). We recompute it independently and check the
    skill produced the same bytes — a request-shape golden with real teeth.
    """
    prehash = (
        (FROZEN.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z") + "GET" + request_path
    )
    mac = hmac.new(DUMMY["secret_key"].encode(), prehash.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


# ---------------------------------------------------------------------------
# Mutations — the anti-vacuity gate. Each must break a golden, or that golden is vacuous.
# ---------------------------------------------------------------------------

MUTATIONS = [
    # (label, find, replace, which golden it should break)
    (
        "sign_drop_method",
        "prehash = timestamp + method + request_path",
        "prehash = timestamp + request_path",
        "request.signature",
    ),
    (
        "amount_off_by_10x",
        "raw = int(integer_part) * (10 ** decimals) + int(decimal_part)",
        "raw = int(integer_part) * (10 ** (decimals + 1)) + int(decimal_part)",
        "request.query.amount",
    ),
    (
        "parse_swap_symbols",
        'symbol=data.get("tokenSymbol", "UNKNOWN"),',
        'symbol=data.get("toTokenSymbol", "UNKNOWN"),',
        "response.summary",
    ),
    (
        "parse_drop_fee",
        'trade_fee_usd=quote_data.get("tradeFee", "0"),',
        'trade_fee_usd="0",',
        "response.summary",
    ),
]


def main() -> int:
    print(f"netcut — boundary re-derivation demo on dex-quote\n{'=' * 64}")
    src = DEX.read_text()

    # ---- CUT 1: request shape, no cassette ---------------------------------
    req1, _, _ = run_boundary(src)
    req2, _, _ = run_boundary(src)  # determinism: same inputs+clock -> same request
    assert req1 is not None, "no request captured"

    det = req1.shape() == req2.shape()
    expected_path = "/api/v6/dex/aggregator/quote"
    doc_host_ok = req1.host == "web3.okx.com"
    doc_path_ok = req1.path == expected_path
    doc_params_ok = req1.shape()["query_keys"] == sorted(
        ["chainIndex", "fromTokenAddress", "toTokenAddress", "amount", "swapMode"]
    )
    sig_ok = req1.signature == independent_signature(
        f"{expected_path}?{_qs(req1.query)}"
    )

    print("\nCUT 1 — request-shape golden (offline, no recorded response):")
    print(f"  request-build deterministic (2 runs identical)  : {_p(det)}")
    print(f"  hits documented host  web3.okx.com              : {_p(doc_host_ok)}")
    print(f"  hits documented path  {expected_path} : {_p(doc_path_ok)}")
    print(
        f"  builds documented params {{chainIndex,from,to,amount,swapMode}}: {_p(doc_params_ok)}"
    )
    print(f"  HMAC signature matches independent re-derivation : {_p(sig_ok)}")
    print(f"  captured query: {dict(req1.query)}")
    print(f"  captured signature: {req1.signature}")

    # ---- CUT 2: response parse, with cassette ------------------------------
    _, result, summary = run_boundary(src, cassette=CASSETTE)
    parse_ok = (
        result is not None
        and result.from_token.symbol == "ETH"
        and result.to_token.symbol == "USDC"
        and abs(result.from_amount_human - 1.0) < 1e-9
        and abs(result.to_amount_human - 3498.2) < 1e-6
        and result.trade_fee_usd == "2.10"
    )
    print("\nCUT 2 — response-parse golden (boundary-pinned to one cassette):")
    print(f"  parses cassette -> documented QuoteResult        : {_p(parse_ok)}")
    print("  summary():")
    for line in (summary or "").splitlines():
        print(f"    | {line}")

    # ---- Anti-vacuity: mutate the code, the goldens must break --------------
    print("\nANTI-VACUITY — mutate the skill code; a real golden must DIVERGE:")
    base_req = req1.shape()
    base_sig = req1.signature
    base_amount = dict(req1.query).get("amount")
    base_summary = summary
    killed = 0
    for label, find, repl, target in MUTATIONS:
        if find not in src:
            print(f"  [{label}] SKIP (pattern not found)")
            continue
        msrc = src.replace(find, repl, 1)
        try:
            mreq, _mres, msum = run_boundary(
                msrc, cassette=CASSETTE if target.startswith("response") else None
            )
        except Exception as e:
            # A mutation that crashes the parse is also "caught" (golden would fail).
            print(f"  [{label}] -> {target:24s} CAUGHT (raised {type(e).__name__})")
            killed += 1
            continue
        if target == "request.signature":
            diverged = mreq.signature != base_sig
        elif target == "request.query.amount":
            diverged = dict(mreq.query).get("amount") != base_amount
        else:  # response.summary
            diverged = msum != base_summary
        print(
            f"  [{label}] -> {target:24s} {'KILLED (golden diverged)' if diverged else 'SURVIVED (vacuous!)'}"
        )
        killed += int(diverged)

    n = sum(1 for _l, f, _r, _t in MUTATIONS if f in src)
    print(
        f"\n  mutation kill rate: {killed}/{n}  "
        f"(>0 => goldens are load-bearing, not vacuous)"
    )

    verdict = (
        all([det, doc_host_ok, doc_path_ok, doc_params_ok, sig_ok, parse_ok])
        and killed >= 1
    )
    print(
        f"\n{'=' * 64}\nVERDICT: {'RE-DERIVED (request + parse, load-bearing)' if verdict else 'INCOMPLETE'}"
    )
    print(
        "Reclaimed offline: the request the skill builds (incl. HMAC signing & amount\n"
        "conversion) and its response parsing. NOT reclaimed: whether OKX is live or\n"
        "returns honest prices — that is provenance, a different axis."
    )
    return 0 if verdict else 1


def _qs(pairs):
    from urllib.parse import urlencode

    # reproduce the skill's insertion order for the path used in signing
    order = ["chainIndex", "fromTokenAddress", "toTokenAddress", "amount", "swapMode"]
    d = dict(pairs)
    return urlencode([(k, d[k]) for k in order if k in d])


def _p(b: bool) -> str:
    return "PASS" if b else "FAIL"


if __name__ == "__main__":
    raise SystemExit(main())
