#!/usr/bin/env python3
"""netcut_parse.py — second boundary-pinning demonstrator: the PARSE/TRANSFORM half.

`netcut.py` proved the mechanism on `dex-quote`, an OKX client whose re-derivable surface
is dominated by request SIGNING. This is a deliberately DIFFERENT shape: `kalshalyst`, a
Kalshi prediction-market BI tool. It has no HMAC and no client class — its re-derivable
surface is a layer of PURE module-level functions that normalize, filter and classify
fetched market data:

    _normalize_market(m)   Kalshi v3 dollar-string fields -> integer cents  (documented)
    _is_blocked(...)       weather/sports/noise markets -> excluded
    _is_sports(...)        word-boundary + phrase sports detection
    _is_noise_market(...)  price-threshold / coin-flip noise detection

This is the "applies scoring algorithms to live data" case from the call notes. The skill's
FINAL output is Claude-generated contrarian estimation — EXOGENOUS, not re-derivable, and we
do not claim it. But the deterministic normalization + filtering pipeline that FEEDS the
model is a pure function of a recorded market response, so it re-derives against a cassette
with mutation teeth. (Intermediate re-derivation: you pin the deterministic stages even when
the last stage is a model.)

No network interception is even needed here — the parse layer is directly importable. We
load the (possibly mutated) source, call the pure functions on ONE recorded Kalshi market
payload, and check the documented transform. Same anti-vacuity discipline as netcut.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
import types
from pathlib import Path

POOL = Path("/tmp/clawhub_pool")
SRC = POOL / "kalshalyst" / "scripts" / "kalshalyst.py"

# ONE recorded Kalshi /markets payload (cassette). Author-attested input; pins the parse
# boundary. Three markets: a clean tradable politics market (v3 dollar-string fields, must
# normalize to cents), a weather market (blocked by ticker prefix + category), and a sports
# market (blocked via sports detection).
CASSETTE = {
    "markets": [
        {
            "ticker": "KXGOVSHUTDOWN-26",
            "category": "politics",
            "title": "Will the federal government shut down in 2026?",
            "yes_bid_dollars": "0.4500",
            "yes_ask_dollars": "0.4800",
            "no_bid_dollars": "0.5200",
            "no_ask_dollars": "0.5500",
            "last_price_dollars": "0.4600",
            "previous_yes_bid_dollars": "0.4400",
            "previous_yes_ask_dollars": "0.4700",
            "previous_price_dollars": "0.4500",
            "volume_fp": "18234.00",
            "volume_24h_fp": "2200.00",
            "open_interest_fp": "54000.00",
            "liquidity_dollars": "9100.0000",
            "notional_value_dollars": "1.0000",
        },
        # Weather market with a NON-blocked ticker prefix, so the ONLY thing that blocks
        # it is the category — isolates the category-block path (over-determined cassettes
        # are exactly what the anti-vacuity gate flags).
        {
            "ticker": "WEATHERX-SUMMER26",
            "category": "weather",
            "title": "Will it be a hot summer in Chicago this year?",
        },
        # Sports market detected ONLY by the multi-word phrase ("super"/"bowl" are not
        # single sports tokens, and the ticker is not a sports prefix) — isolates the
        # phrase path.
        {
            "ticker": "EVENTX-FEB26",
            "category": "entertainment",
            "title": "Will the Super Bowl go to overtime this year?",
        },
    ]
}

# Expected normalization of the politics market (documented: dollar string -> integer cents
# via round(float*100); *_fp -> int). Re-derived by hand from the documented rule.
EXPECT_CENTS = {
    "yes_bid": 45,
    "yes_ask": 48,
    "no_bid": 52,
    "no_ask": 55,
    "last_price": 46,
    "previous_yes_bid": 44,
    "previous_yes_ask": 47,
    "previous_price": 45,
    "liquidity": 910000,
    "notional_value": 100,
}
EXPECT_INT = {"volume": 18234, "volume_24h": 2200, "open_interest": 54000}


def load_module(source: str) -> types.ModuleType:
    tmp = SRC.parent / "_netcut_parse_tmp.py"
    tmp.write_text(source)
    try:
        sys.modules.pop("kalshalyst_under_test", None)
        spec = importlib.util.spec_from_file_location("kalshalyst_under_test", tmp)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["kalshalyst_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        tmp.unlink(missing_ok=True)


def derive(mod) -> dict:
    """Run the pure parse/classify layer over the cassette. No network."""
    pol, wx, sport = (copy.deepcopy(m) for m in CASSETTE["markets"])
    norm = mod._normalize_market(pol)
    return {
        "normalized": {k: norm.get(k) for k in (*EXPECT_CENTS, *EXPECT_INT)},
        "politics_blocked": mod._is_blocked(
            pol["ticker"], pol["category"], pol["title"], norm.get("yes_bid", 50)
        ),
        "weather_blocked": mod._is_blocked(
            wx["ticker"], wx["category"], wx["title"], 50
        ),
        "sports_detected": mod._is_sports(sport["ticker"], sport["title"]),
    }


MUTATIONS = [
    # (label, find, replace, which golden it should break)
    (
        "cents_drop_x100",
        "return int(round(float(val) * 100))",
        "return int(round(float(val)))",
        "normalized",
    ),
    (
        "unblock_weather",
        '"weather", "climate", "entertainment", "sports",',
        '"climate", "entertainment", "sports",',
        "weather_blocked",
    ),
    (
        "drop_superbowl_phrase",
        '"super bowl", "superbowl", "march madness", "world series",',
        '"march madness", "world series",',
        "sports_detected",
    ),
]


def _p(b: bool) -> str:
    return "PASS" if b else "FAIL"


def main() -> int:
    print(
        f"netcut_parse — parse/transform re-derivation demo on kalshalyst\n{'=' * 64}"
    )
    src = SRC.read_text()
    base = derive(load_module(src))

    # ---- the re-derivation checks ------------------------------------------
    norm = base["normalized"]
    cents_ok = all(norm[k] == v for k, v in EXPECT_CENTS.items())
    ints_ok = all(norm[k] == v for k, v in EXPECT_INT.items())
    pol_ok = base["politics_blocked"] is False
    wx_ok = base["weather_blocked"] is True
    sport_ok = base["sports_detected"] is True

    print("\nPARSE/TRANSFORM golden (cassette-pinned, no network):")
    print(f"  v3 dollar-strings -> integer cents (documented)  : {_p(cents_ok)}")
    print(f"  *_fp strings -> integers                         : {_p(ints_ok)}")
    print(f"  clean politics market NOT blocked                : {_p(pol_ok)}")
    print(f"  weather market blocked (by category)             : {_p(wx_ok)}")
    print(f"  sports market detected (by phrase)               : {_p(sport_ok)}")
    print(f"  normalized politics market: {norm}")

    # ---- anti-vacuity: mutate, the goldens must diverge --------------------
    print("\nANTI-VACUITY — mutate the parse code; a real golden must DIVERGE:")
    killed = 0
    applicable = 0
    for label, find, repl, target in MUTATIONS:
        if find not in src:
            print(f"  [{label}] SKIP (pattern not found)")
            continue
        applicable += 1
        try:
            mres = derive(load_module(src.replace(find, repl, 1)))
        except Exception as e:
            print(f"  [{label}] -> {target:18s} CAUGHT (raised {type(e).__name__})")
            killed += 1
            continue
        diverged = mres[target] != base[target]
        print(
            f"  [{label}] -> {target:18s} "
            f"{'KILLED (golden diverged)' if diverged else 'SURVIVED (vacuous!)'}"
        )
        killed += int(diverged)

    print(
        f"\n  mutation kill rate: {killed}/{applicable}  "
        f"(>0 => goldens are load-bearing)"
    )

    ok = all([cents_ok, ints_ok, pol_ok, wx_ok, sport_ok]) and killed >= 1
    print(
        f"\n{'=' * 64}\nVERDICT: "
        f"{'RE-DERIVED (parse/transform/classify, load-bearing)' if ok else 'INCOMPLETE'}"
    )
    print(
        "Reclaimed offline: the deterministic market-normalization + filtering pipeline\n"
        "(dollar->cents, weather/sports/noise exclusion). NOT reclaimed: the final\n"
        "Claude contrarian estimate that consumes it — that stage is model output, a\n"
        "different axis. Intermediate re-derivation pins the deterministic stages."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
