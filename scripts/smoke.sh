#!/usr/bin/env bash
# Basic smoke test for a RUNNING tether server.
#
# Tests the live HTTP surface end to end (not in-process like pytest), so you
# can confirm what you are about to share actually works, and you can point it
# at your proxy URL to test that path too.
#
# Usage:
#   scripts/smoke.sh                         # default http://127.0.0.1:4444
#   scripts/smoke.sh http://127.0.0.1:4444   # direct
#   scripts/smoke.sh https://tether.local    # through your nginx / Tailscale
set -u

BASE="${1:-http://127.0.0.1:4444}"
fail=0

check() {
  local name="$1" expect="$2" got="$3"
  if [ "$got" = "$expect" ]; then
    echo "PASS  $name -> $got"
  else
    echo "FAIL  $name -> expected [$expect], got [$got]"
    fail=1
  fi
}

echo "Smoke testing tether at $BASE"
echo "-----------------------------------------"

code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/health")
check "/health status" "200" "$code"

body=$(curl -s --max-time 5 "$BASE/health")
check "/health body" '{"status":"ok"}' "$body"

shell=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/")
check "/ ui shell status" "200" "$shell"

echo "-----------------------------------------"
if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "SMOKE FAILED (is the server up? is the URL/port right?)"
fi
exit "$fail"
