#!/bin/bash
# Install the fund's launchd cron from the REPO copies — the repo is the single
# source of truth for the cron. The plists here are COPIED into
# ~/Library/LaunchAgents (where launchd loads user agents) and reloaded, so editing
# a plist in the repo and re-running this is how the live schedule changes.
#
# No sudo — these are per-user agents (gui/<uid>).
# Idempotent: safe to run repeatedly. Run after editing any plist in this dir.
#   bash trading/deploy/launchd/install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
TRADING_ROOT="$(cd "$HERE/../.." && pwd)"
mkdir -p "$TRADING_ROOT/strategies/csp_401k/logs"
mkdir -p "$AGENTS"

for plist in "$HERE"/hedgy-agent.*.plist; do
  label="$(basename "$plist" .plist)"
  dest="$AGENTS/$label.plist"

  # Tear down the currently-loaded job (ignore "not loaded") before reinstalling.
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true

  # rm first so a copy never writes back through an old symlink to the repo file.
  rm -f "$dest"
  python3 - "$plist" "$dest" "$TRADING_ROOT" <<'PYPLIST'
import pathlib, plistlib, sys
src, dest, root = sys.argv[1:]
data = plistlib.loads(pathlib.Path(src).read_bytes())
def expand(value):
    if isinstance(value, str):
        return value.replace("__TRADING_ROOT__", root)
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    return value
pathlib.Path(dest).write_bytes(plistlib.dumps(expand(data)))
PYPLIST
  launchctl enable "gui/$UID_NUM/$label"
  launchctl bootstrap "gui/$UID_NUM" "$dest"
  echo "installed + loaded: $label (copied from $plist)"
done

echo "--- loaded hedgy-agent jobs ---"
launchctl list | grep -E '^[0-9-]+[[:space:]]+[0-9-]+[[:space:]]+hedgy-agent\.' || echo "(none reported by launchctl list)"
