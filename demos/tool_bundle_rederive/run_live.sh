#!/usr/bin/env bash
# run_live.sh — exercise the tool-BUNDLE re-derivation gate inside a REAL OpenClaw
# install, end to end.
#
# Unlike rederive_bundle.py (which calls installpolicy.run() in-process), this wires
# relyable-installpolicy in as OpenClaw's security.installPolicy with the consumer's
# json_toolkit_grader, then runs the actual `openclaw skills install` for:
#   (A) the honest clean-json-toolkit from ClawHub      -> expect ALLOW (installs)
#   (B) a locally-staged copy with query.py sabotaged   -> expect BLOCK (a graded
#                                                          tool contradicts its goldens)
#
# The honest skill's query+flatten tools re-derive against the consumer goldens; its
# other 5 tools are unjudgeable (no goldens) and therefore do not block — so the
# bundle installs. The broken copy is blocked because a tool the consumer DOES grade
# (query) no longer reproduces the goldens.
#
# Verified on 2026-06-18 against openclaw 2026.6.8 + veriker 0.1.2 (see LIVE_RUN.md).
#
# Reuses an existing openclaw checkout ($OPENCLAW_DIR, default /tmp/oclive) and venv
# ($VENV, default /tmp/relyenv) when present, else builds fresh scratch. Mutates
# ~/.openclaw/openclaw.json (backed up + restored). Run on a host where executing the
# candidate skill is acceptable.
set -euo pipefail

OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.6.8}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # relyable repo root
GRADER="$REPO/relyable/skills/examples/json_toolkit_grader.py"
OPENCLAW_DIR="${OPENCLAW_DIR:-/tmp/oclive}"
VENV="${VENV:-/tmp/relyenv}"
WORK="$(mktemp -d -t relyable-tb-live-XXXX)"
OCJSON="$HOME/.openclaw/openclaw.json"

cleanup() {
  [ -f "$WORK/openclaw.json.bak" ] && cp "$WORK/openclaw.json.bak" "$OCJSON" 2>/dev/null || true
  echo "[scratch: $WORK]"
}
trap cleanup EXIT

echo "== 0. prerequisites =="
if [ ! -d "$OPENCLAW_DIR/node_modules/openclaw" ]; then
  echo "  building fresh openclaw in $WORK"
  OPENCLAW_DIR="$WORK"
  ( cd "$OPENCLAW_DIR" && npm init -y >/dev/null 2>&1 && npm install "openclaw@$OPENCLAW_VERSION" >npm.log 2>&1 )
fi
OC() { ( cd "$OPENCLAW_DIR" && npx --no-install openclaw "$@" ); }
OC --version
RIP="$VENV/bin/relyable-installpolicy"
test -x "$RIP" || { echo "FAIL: $RIP not found — pip install -e $REPO into $VENV"; exit 1; }
[ -f "$OCJSON" ] && cp "$OCJSON" "$WORK/openclaw.json.bak"

echo "== 1. wire relyable-installpolicy (json_toolkit_grader) as security.installPolicy =="
cat > "$WORK/policy.json5" <<EOF
{ security: { installPolicy: {
  enabled: true, targets: ["skill"],
  exec: {
    source: "exec", command: "$RIP", timeoutMs: 30000,
    env: {
      RELYABLE_INSTALLPOLICY_GRADER: "$GRADER",
      RELYABLE_INSTALLPOLICY_KIND_MAP: "{\"clean-json-toolkit\":\"clean-json-toolkit\",\"clean-json-toolkit-broken\":\"clean-json-toolkit\"}",
      RELYABLE_INSTALLPOLICY_PERMIT_EXECUTION: "1",
      RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE: "block"
    }
  }
}}}
EOF
OC config patch --file "$WORK/policy.json5"

echo "== 2. live: install the HONEST clean-json-toolkit from ClawHub (expect ALLOW) =="
OC skills install clean-json-toolkit --global --force
test -e "$HOME/.openclaw/skills/clean-json-toolkit/scripts/query.py" \
  && echo "  -> honest bundle INSTALLED (query+flatten re-derived; 5 ungraded tools did not block)" \
  || { echo "FAIL: honest bundle not installed"; exit 1; }

echo "== 3. stage a BROKEN copy (sabotage query.py's --raw) =="
MKT="$WORK/marketplace/clean-json-toolkit-broken"
mkdir -p "$MKT"
cp -r "$HOME/.openclaw/skills/clean-json-toolkit/." "$MKT/"
rm -rf "$MKT/scripts/__pycache__"
"$VENV/bin/python" - "$MKT/scripts/query.py" <<'PY'
import sys, pathlib
f = pathlib.Path(sys.argv[1])
src = f.read_text()
broken = src.replace('out.write(r + "\\n")', 'out.write(repr(r) + "\\n")')
assert broken != src, "sabotage pattern not found"
f.write_text(broken)
print("  -> query.py --raw now leaves quotes on string scalars (contradicts goldens)")
PY

echo "== 4. live: install the BROKEN copy (expect BLOCK) =="
set +e
OUT="$(OC skills install "$MKT" --global --force 2>&1)"
RC=$?
set -e
echo "$OUT" | tail -4
if [ $RC -ne 0 ] && [ ! -e "$HOME/.openclaw/skills/clean-json-toolkit-broken" ]; then
  echo "  -> broken bundle BLOCKED and absent from disk (correct)"
else
  echo "FAIL: broken bundle was not blocked / landed on disk (rc=$RC)"; exit 1
fi

echo "== 5. honest bundle still intact on disk (broken --force did not clobber it) =="
grep -q 'out.write(r + "\\n")' "$HOME/.openclaw/skills/clean-json-toolkit/scripts/query.py" \
  && echo "  -> on-disk query.py is the honest one (correct)" \
  || { echo "FAIL: on-disk query.py was modified"; exit 1; }

echo
echo "LIVE SELF-CHECK: PASS (honest tool-bundle installed, broken-tool bundle blocked by real OpenClaw)"
