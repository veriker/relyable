#!/usr/bin/env bash
# collect_clawhub_sample.sh — fetch a real ClawHub skill sample and run the funnel.
#
# We do NOT vendor third-party skill bodies into this repo (licensing + bloat). This
# installs a real sample from ClawHub into a scratch OpenClaw skills dir, then runs
# funnel.py over it. The sample is a fixed, broad slug list (prose-ish + executable-ish)
# so the funnel numbers are reproducible-ish — ClawHub content can change upstream.
#
# Captured run: see FUNNEL_RUN.md (2026-06-18, openclaw 2026.6.8).
# Requires: node/npm (for `openclaw`), python3 with relyable importable.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d -t clawhub-sample-XXXX)"
export HOME="$WORK"           # isolate ~/.openclaw so we never touch a real install
SKILLS_DIR="$WORK/.openclaw/skills"

SLUGS=(json sql markdown csv image scrape expanso-csv-to-json csv-analyzer
       data-format-converter json-formatter markdown-converter pandoc-convert-openclaw
       convert-units case-convert json-linter markdown-table-generator sql-toolkit
       clean-json-toolkit)

echo "== installing ${#SLUGS[@]} ClawHub skills into $SKILLS_DIR =="
( cd "$WORK" && npm init -y >/dev/null 2>&1 && npm install openclaw >/dev/null 2>&1 )
# Gate OFF for collection — we are sampling the directory, not gating installs.
echo '{ security: { installPolicy: { enabled: false } } }' > "$WORK/off.json5"
( cd "$WORK" && npx openclaw config patch --file "$WORK/off.json5" >/dev/null 2>&1 )
ok=0
for s in "${SLUGS[@]}"; do
  if ( cd "$WORK" && npx openclaw skills install "$s" --global --force ) >/dev/null 2>&1; then
    ok=$((ok+1))
  else
    echo "  (skip: $s — install failed)"
  fi
done
echo "  installed $ok/${#SLUGS[@]}"

echo "== funnel =="
"$PY" "$REPO/demos/directory_funnel/funnel.py" "$SKILLS_DIR"
echo "[scratch: $WORK]"
