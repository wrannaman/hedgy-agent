#!/bin/bash
# Independent absence-detection watchdog. Runs weekdays at 8:00 AM PT — 75 min
# after the main scan should have fired. Catches the cases run_daily.sh can't
# self-report: cron disabled, machine asleep at 6:45, script deleted, or a crash
# so early that nothing got logged.
#
# Two checks:
#   1. cron log for today exists & non-empty  — proves run_daily.sh started
#   2. scan jsonl for today exists & non-empty — proves the pipeline actually ran
# If run_daily.sh already alerted (AUTH DEAD / NO SCAN LOG / LATE FIRE), don't double-ping.

set -u
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
PYTHON="${HEDGY_PYTHON:-$REPO_ROOT/../.venv/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$REPO_ROOT/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
export PATH="$(dirname "$PYTHON"):/usr/local/bin:/usr/bin:/bin"
export PYTHONPATH="$REPO_ROOT"
DAY="$(date +%Y-%m-%d)"
CRON_LOG="logs/cron-$DAY.log"
SCAN_LOG="logs/$DAY.jsonl"
slack_alert() {
  printf '%s' "$1" | "$PYTHON" -m shared.notifications || true
}

# Market holiday / weekend — nothing was supposed to run today; don't alarm.
if ! "$PYTHON" market_open.py >/dev/null 2>&1; then
  exit 0
fi

# The ONLY thing that counts as a clean morning: run_daily.sh stamped the day
# after it posted. Everything else is an absence and gets a ping.
#
# A cron log can contain output from a manual or failed invocation. Matching a
# failure string cannot prove that the scheduled run posted its recap. Require
# positive completion; a missing stamp remains an absence worth reporting.
if [ "$(cat state/last_morning_run.txt 2>/dev/null)" = "$DAY" ]; then
  exit 0
fi

# ...with one exception: a morning pass still in flight is not an absence. The
# agent gets up to 2 x 20min, so a boot catch-up that started at 07:40 is still
# legitimately working at 08:00. Match the morning invocation only — launchd
# passes no argument, intraday passes --intraday, so anchoring on end-of-args
# separates them.
if ps -Ao args= | grep -E 'run_daily\.sh( morning)?$' | grep -qv grep; then
  exit 0
fi

if [ ! -s "$CRON_LOG" ]; then
  slack_alert ":rotating_light: csp_401k MORNING SCAN NEVER STARTED today ($DAY) — no cron log at all. The 6:35 job did not fire. Check \`launchctl print gui/$(id -u)/hedgy-agent.morning-roam\` (runs=0 means launchd skipped it — usually the Mac was powered off at 6:35; launchd does not backfill a missed calendar interval). Kick it now: \`strategies/csp_401k/run_daily.sh morning\`"
elif [ ! -s "$SCAN_LOG" ]; then
  slack_alert ":rotating_light: csp_401k started today ($DAY) but produced NO scan and no morning recap. Check logs/cron-$DAY.log, then rerun \`strategies/csp_401k/run_daily.sh morning\`"
else
  slack_alert ":rotating_light: csp_401k scanned today ($DAY) but never completed a morning pass — no recap was posted. Check logs/cron-$DAY.log, then rerun \`strategies/csp_401k/run_daily.sh morning\`"
fi
exit 1
