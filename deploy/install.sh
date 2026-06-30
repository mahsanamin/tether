#!/usr/bin/env bash
# Install tether as durable launchd user agents: the server and the shell routine.
# After this, tether runs 24/7 on its own, independent of any terminal or Claude
# Code session, and survives logout/reboot. Re-run any time to reload new code.
#
# It renders the committed plist TEMPLATES (deploy/*.plist) with real values:
#   __REPO__  this checkout's absolute path
#   __UV__    your uv binary
#   __PATH__  your current PATH (so the routine can find your own commands)
# so nothing personal is hardcoded in the repo.
#
# Usage:  bash deploy/install.sh
set -euo pipefail

# Repo root = the parent of this script's directory, resolved to an absolute path.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LA="$HOME/Library/LaunchAgents"
AGENTS=(com.tether.server com.tether.routine)

# Locate uv; fall back to the common install location.
UV="$(command -v uv || true)"
[ -z "$UV" ] && UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then
  echo "uv not found (looked on PATH and at $UV). Install uv first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

# PATH the agents run with: uv's dir first, then your current PATH, so any custom
# commands you expose in the chat resolve. launchd otherwise gives a bare PATH.
AGENT_PATH="$(dirname "$UV"):$PATH"

mkdir -p "$LA"

# Render each template into LaunchAgents with the real values filled in.
for a in "${AGENTS[@]}"; do
  sed -e "s|__UV__|$UV|g" -e "s|__REPO__|$REPO|g" -e "s|__PATH__|$AGENT_PATH|g" \
    "$REPO/deploy/$a.plist" > "$LA/$a.plist"
done

# Stop any session-tethered instances so launchd can bind :4444 and own the stack.
pkill -f "uv run tether" 2>/dev/null || true
pkill -f "shell_routine.py" 2>/dev/null || true
sleep 1

# Reload cleanly (unload an older copy first, ignore "not loaded").
for a in "${AGENTS[@]}"; do
  launchctl unload "$LA/$a.plist" 2>/dev/null || true
  launchctl load "$LA/$a.plist"
done

sleep 2
echo "== launchd agents =="
launchctl list | grep -i tether || echo "(none listed yet; check the logs below)"
echo "== health =="
curl -fsS -m 4 http://127.0.0.1:4444/health || echo "(server not answering yet; tail $REPO/tether.err.log)"
echo
echo "logs: $REPO/tether.{out,err}.log  and  $REPO/routine.{out,err}.log"
