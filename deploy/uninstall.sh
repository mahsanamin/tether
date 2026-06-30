#!/usr/bin/env bash
# Remove the tether launchd user agents (server + routine) and stop them.
# Usage:  bash deploy/uninstall.sh
set -euo pipefail

LA="$HOME/Library/LaunchAgents"
for a in com.tether.server com.tether.routine; do
  launchctl unload "$LA/$a.plist" 2>/dev/null || true
  rm -f "$LA/$a.plist"
done
echo "tether launchd agents removed."
