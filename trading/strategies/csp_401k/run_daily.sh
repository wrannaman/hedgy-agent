#!/bin/bash
# csp_401k pipeline. Spawns claude headless with CRON_PROMPT.md so the judgment
# happens as designed; THIS SCRIPT owns the one normal Slack post (via post_once.py).
# The agent decides and writes state/agent_decision.json — it never posts anything.
# One posting authority prevents duplicate notifications. Runs in two modes:
#   morning  (default, 6:35 AM PT)  — full run; guarantees the account owner ONE Slack message:
#       a trade ticket, a daily recap, or a failure alert.
#   intraday (--intraday, midday)   — re-runs the hunt + position monitor so we
#       catch intraday candidates (to justify rotating out of a winner) and
#       intraday risk exits on open positions. Stays SILENT unless the agent
#       wrote a real trade/risk ticket — no "nothing found" chatter.
# Once-a-day was insufficient: the keep-vs-redeploy gate could only see the
# open-bell candidate snapshot, and a position could blow a risk exit unseen
# until the next morning.
#
# the account owner should never have to check a log or wonder whether it ran.

set -u
MODE="${1:-morning}"   # "morning" | "intraday"

# Resolve the repo root from this script's own location so the job works no
# matter where the repo lives on disk (it has moved before). PATH, the venv,
# and REPO_ROOT all derive from this — nothing below is a hardcoded path.
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"

# Use this checkout's environment; no shell-profile credential scraping.
PYTHON="${HEDGY_PYTHON:-$REPO_ROOT/../.venv/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$REPO_ROOT/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
export PATH="$(dirname "$PYTHON"):$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# Use the authenticated CLI's own default unless the operator opts into a model.
CLAUDE_MODEL="${CLAUDE_MODEL:-}"
CLAUDE_CMD=("${CLAUDE_BIN:-claude}")
[ -z "$CLAUDE_MODEL" ] || CLAUDE_CMD+=(--model "$CLAUDE_MODEL")
export PYTHONPATH="$REPO_ROOT"

mkdir -p logs state
DAY="$(date +%Y-%m-%d)"
LOG="logs/cron-$DAY.log"
SCAN_LOG="logs/$DAY.jsonl"

slack_post() {
  printf '%s' "$1" | "$PYTHON" -m shared.notifications || true
}

# Kill a pid and every descendant, depth-first. Used by the claude timeout
# below: killing only the agent's pid leaves its python/zsh grandchildren
# orphaned, so walk the whole tree.
kill_tree() {
  local p="$1" c
  for c in $(pgrep -P "$p" 2>/dev/null); do kill_tree "$c"; done
  kill -KILL "$p" 2>/dev/null
}

{
  echo "=== $(date) ==="

  # ---- Guard 0: has a morning pass already completed today? ----
  # RunAtLoad catches a calendar trigger missed while the machine was powered
  # off. A positive completion stamp prevents duplicate scans/recaps on login.
  MORNING_STAMP="state/last_morning_run.txt"
  if [ "$MODE" = "morning" ] && [ "$(cat "$MORNING_STAMP" 2>/dev/null)" = "$DAY" ]; then
    echo "morning pass already completed today ($DAY) — nothing to do"
    echo "=== done exit=0 (already ran) ==="
    exit 0
  fi

  # ---- Guard 1: Schwab auth health ----
  # Retried 3x. A boot catch-up run (Guard 0) can start seconds after login, before
  # Wi-Fi has associated, and "network isn't up yet" is indistinguishable here from
  # "the refresh token is dead". ~40s of retries is cheap; a false ":rotating_light:
  # Schwab access expired" that sends the account owner to re-login for nothing is not.
  AUTH_OK=0
  for _try in 1 2 3; do
    if PYTHONPATH="$REPO_ROOT" python3 -c \
        "from shared.auth import get_client; c = get_client(); r = c.get_account_numbers(); r.raise_for_status()" 2>&1; then
      AUTH_OK=1; break
    fi
    echo "auth attempt $_try failed"
    [ "$_try" -lt 3 ] && sleep 20
  done
  if [ "$AUTH_OK" -eq 0 ]; then
    echo "AUTH FAILED — pipeline skipped"
    slack_post ":rotating_light: csp_401k can't log in — Schwab access expired. Run \`hedgy auth\` to fix it. No scan today ($DAY)."
    exit 1
  fi
  echo "auth: OK"

  # ---- Token-expiry early-warning ----
  # The Schwab REFRESH token lasts 7 days; when it dies, every call fails until a
  # manual re-login (shared/login.py) and the system goes blind mid-session — which
  # is exactly what happened the day this was added (token died right after the 6:42
  # run). login.py stamps state/last_schwab_login.txt with the login DATE (date only,
  # never token material), so warn once the token is 6+ days old, before it expires.
  # Only the morning run warns, to avoid repeating it every intraday pass.
  LOGIN_STAMP="$REPO_ROOT/state/last_schwab_login.txt"
  if [ "$MODE" = "morning" ] && [ -f "$LOGIN_STAMP" ]; then
    LOGIN_AGE_DAYS=$(( ( $(date +%s) - $(date -j -f %Y-%m-%d "$(cat "$LOGIN_STAMP")" +%s 2>/dev/null || echo "$(date +%s)") ) / 86400 ))
    if [ "$LOGIN_AGE_DAYS" -ge 6 ]; then
      slack_post ":warning: csp_401k Schwab login is ${LOGIN_AGE_DAYS}d old — the 7-day token expires within ~1 day and the system will go blind mid-session. Re-auth now: \`hedgy auth\`"
    fi
  fi

  # ---- Guard: is the market open today? (holiday / weekend) ----
  # launchd fires Mon-Fri but knows nothing about market holidays.
  if ! "$PYTHON" market_open.py >/dev/null 2>&1; then
    echo "MARKET CLOSED $DAY — no scan today"
    echo "=== done exit=0 (market closed) ==="
    exit 0
  fi
  echo "market: open"

  # ---- Guard: late fire? (laptop was shut through the market open) ----
  # Market closes 1 PM PT. A scan that fires after the close can't act on
  # anything — skip the hunt, tell the account owner it missed the open, keep watchdog quiet.
  if [ "$(date +%H)" -ge 13 ]; then
    echo "LATE FIRE $(date +%H:%M) — market closed, skipping the trade hunt"
    [ "$MODE" = "morning" ] && slack_post ":sleeping: csp_401k didn't run at the open today ($DAY) — laptop was closed. Market's now closed, so no scan. Back tomorrow at 6:35am PT."
    echo "=== done exit=0 (late fire, mode=$MODE) ==="
    exit 0
  fi

  # ---- Book hygiene: reconcile the log against the account, then re-render the journal ----
  # reconcile.py is the check that catches a logged-open trade the account doesn't hold.
  # Distinguish a never-filled entry from a previously observed position that
  # disappeared after a close. Persist each reconciliation verdict for review.
  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/strategies/csp_401k/reconcile.py" > "logs/reconcile-$DAY.log" 2>&1 \
    || echo "reconcile failed (non-fatal) — cause in logs/reconcile-$DAY.log"
  if grep -q "CLOSED —" "logs/reconcile-$DAY.log" 2>/dev/null; then
    slack_post ":receipt: csp_401k: a position that was live is now gone from the 401k — that's a FILL. Pull the fill price from Schwab order status and book the close. Details: \`strategies/csp_401k/logs/reconcile-$DAY.log\`"
  fi
  # POSITIONS.md is generated from state/trade_log.json — never hand-edited.
  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/strategies/csp_401k/render_journal.py" >/dev/null 2>&1 \
    || echo "render_journal failed (non-fatal)"

  # ---- Cross-account portfolio context (recommendation-only) ----
  # Reads latest CSV exports in positions/ and writes portfolio_watch/state/latest.*.
  # This never places orders; it gives the morning agent context about what the account owner
  # already owns outside the 401k options strategy.
  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/strategies/portfolio_watch/sweep.py" || echo "portfolio_watch failed (non-fatal)"

  # Tax-aware de-gross lens: cheapest-tax way to raise cash + trailing-stop on
  # concentrated winners. Pure defaults (no flags); writes state for the agent.
  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/strategies/portfolio_watch/rebalance.py" || echo "rebalance failed (non-fatal)"

  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/strategies/csp_401k/covered_calls.py" || echo "covered_calls failed (non-fatal)"

  # ---- Dry-day idea generation + worldview hygiene (morning only; recommendation-only) ----
  # laggard_scan surfaces willing-owner quality names the market is hating (the idea the
  # system used to wait for the account owner to hand it). worldview flags any belief past its
  # review-by date so a stale thesis can't quietly keep tilting the hunt. Both non-fatal.
  if [ "$MODE" = "morning" ]; then
    PYTHONPATH="$REPO_ROOT" "$PYTHON" \
      "$REPO_ROOT/strategies/csp_401k/laggard_scan.py" > "logs/laggards-$DAY.log" 2>&1 \
      || echo "laggard_scan failed (non-fatal) — cause in logs/laggards-$DAY.log"
    PYTHONPATH="$REPO_ROOT" "$PYTHON" \
      "$REPO_ROOT/worldview.py" || echo "worldview review failed (non-fatal)"
  fi

  # ---- Mini hedge fund: extra sleeves + the unified morning brief ----
  # Evidence-based sleeves beyond single-name puts (FUND.md). Every line is
  # non-fatal: a sleeve hiccup must NEVER block the core csp_401k run. The brief
  # (all sleeves, gated + ranked) is written to state/morning_brief.txt for the agent.
  mkdir -p "$REPO_ROOT/state"
  # Each scanner's full output (incl. tracebacks) goes to its own dated log so a
  # failure always has its exact cause on disk — never swallowed by /dev/null.
  for s in index_vrp trend factor pead; do
    PYTHONPATH="$REPO_ROOT" "$PYTHON" \
      "$REPO_ROOT/strategies/$s/scan.py" > "logs/scan-$s-$DAY.log" 2>&1 \
      || echo "$s scan failed (non-fatal) — cause in logs/scan-$s-$DAY.log"
  done
  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
    "$REPO_ROOT/fund_engine.py" > "$REPO_ROOT/state/morning_brief.txt" 2>&1 \
    || echo "fund_engine failed (non-fatal)"

  # ---- Guard: the brief MUST be today's ----
  # fund_engine is non-fatal above, so a crash (or a partial write) would otherwise
  # leave YESTERDAY's brief on disk and the agent would act on stale sleeve
  # candidates. That actually happened: a stale brief surfaced an index spread that
  # today's FOMC blackout should have killed. fund_engine stamps "BRIEF DATE: $DAY";
  # if that line isn't present for today, the brief is stale/broken — overwrite it
  # with a loud marker so NO sleeve trade can surface, and alert the account owner.
  BRIEF="$REPO_ROOT/state/morning_brief.txt"
  if ! grep -q "^BRIEF DATE: $DAY$" "$BRIEF" 2>/dev/null; then
    echo "STALE/MISSING BRIEF — fund_engine did not produce a fresh brief for $DAY"
    printf 'BRIEF UNAVAILABLE for %s — fund_engine did not produce a fresh brief.\nDo NOT surface any sleeve trade today (index / PEAD / covered-call / factor / trend).\nThe csp_401k put sleeve still runs from its own fresh screener.\n' "$DAY" > "$BRIEF"
    [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k brief is STALE/missing for $DAY — the fund engine didn't refresh it. Neutralized it so no stale index/PEAD trade can surface; the put hunt still runs. Check logs/cron-$DAY.log"
  else
    echo "brief: fresh ($DAY)"
  fi

	  # Build a best-effort decision from the most recent screener/trade/portfolio
	  # state before the agent refreshes them. Do not run catalyst_check here: that
	  # verdict must be tied to the fresh screener candidate selected after the
	  # agent run below.
	  PYTHONPATH="$REPO_ROOT" "$PYTHON" \
	    "$REPO_ROOT/strategies/morning_decision/decide.py" || echo "morning_decision preflight failed (non-fatal)"

  # ---- Run the pipeline via headless claude ----
  # --dangerously-skip-permissions: required so the headless agent can actually run
  #   the python scripts / web searches the CRON_PROMPT mandates. Safety against rogue
  #   trades is enforced by CRON_PROMPT.md + repo CLAUDE.md (no orders in automated
  #   sessions, ever) + the pipeline scripts being read-only.
  # Bound wall-clock duration because launchd will not start a second instance
  # while a prior job is stuck. Kill the process tree on timeout and retry only
  # within the configured attempt limit; report failure after the final attempt.
  # The per-attempt cap keeps bounded retries inside the trading window.
  #
  # ---- Guard: headless claude auth health (fast preflight) ----
  # Authenticate the optional CLI explicitly before enabling this scheduler.
  # A bounded probe prevents an unavailable agent from blocking the pipeline.
  RC=0; TIMED_OUT=0
  CLAUDE_AUTH_OK=1
  "${CLAUDE_CMD[@]}" -p "reply with exactly: PONG" > "logs/claude-probe-$DAY.log" 2>&1 &
  PROBE_PID=$!
  ( sleep 60; kill -0 "$PROBE_PID" 2>/dev/null && kill_tree "$PROBE_PID"; ) &
  PROBE_KILLER=$!
  wait "$PROBE_PID"; PROBE_RC=$?
  kill "$PROBE_KILLER" 2>/dev/null
  if [ "$PROBE_RC" -ne 0 ] || ! grep -qx 'PONG' "logs/claude-probe-$DAY.log"; then
    CLAUDE_AUTH_OK=0
    RC=1
    echo "CLAUDE PREFLIGHT FAILED (rc=$PROBE_RC) — expected PONG; see logs/claude-probe-$DAY.log"
    [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k Claude preflight failed today ($DAY). Check logs/claude-probe-$DAY.log for the actual error; a failed probe alone does not establish expired credentials. No fresh recommendation."
  else
    echo "claude auth: OK"
  fi

  CLAUDE_TIMEOUT=1200        # 20 min per attempt — screener (~3 min) + monitor + judgment fit easily
  CLAUDE_MAX_ATTEMPTS=2      # 1 retry; worst case 40 min, still before the 1pm PT close
  CLAUDE_RETRY_BACKOFF=15    # brief pause between attempts (rides out a transient API/rate-limit blip)

  # Runs claude once under a hard wall-clock cap. Sets globals RC and TIMED_OUT.
  run_claude_once() {
    local CLAUDE_CMD=("${CLAUDE_BIN:-claude}")
    [ -z "${CLAUDE_MODEL:-}" ] || CLAUDE_CMD+=(--model "$CLAUDE_MODEL")
    local flag="${TMPDIR:-/tmp}/csp_401k-claude-timeout-$DAY-$$-$1"
    rm -f "$flag"
    local started
    started="$(python3 -c 'import time; print(time.time())')"
    "${CLAUDE_CMD[@]}" --dangerously-skip-permissions -p \
      "Execute the scheduled csp_401k run now. Read CRON_PROMPT.md from this directory and carry out its runbook to completion in this turn. Run the scans in the foreground and write the fresh decision to $REPO_ROOT/state/agent_decision.json. This is an execution request, not background context. Do not ask what to do. Do not place orders or send any messages. Do not change code, configuration, strategy rules, or this runbook. If blocked, report the exact failed command and error." &
    local pid=$!
    (
      sleep "$CLAUDE_TIMEOUT"
      # Re-check liveness before marking timeout. This avoids false timeout alerts
      # and reduces the chance of killing a process after the agent already exited.
      if kill -0 "$pid" 2>/dev/null; then
        touch "$flag"
        kill_tree "$pid"
      fi
    ) &
    local killer=$!
    wait "$pid"
    RC=$?
    # Agent finished on its own — cancel the killer so it doesn't linger 20 min.
    kill "$killer" 2>/dev/null
    if [ -f "$flag" ]; then TIMED_OUT=1; else TIMED_OUT=0; fi
    rm -f "$flag"
    # A greeting, partial run, or stale same-day files must never count as success.
    if [ "$RC" -eq 0 ] && ! python3 verify_run.py "$started"; then
      echo "claude exited successfully but did not complete fresh scan/screen/decision outputs"
      RC=1
    fi
  }

  if [ "$CLAUDE_AUTH_OK" -eq 1 ]; then
  ATTEMPT=1
  while : ; do
    run_claude_once "$ATTEMPT"
    if [ "$TIMED_OUT" -eq 1 ]; then
      echo "claude TIMED OUT (>${CLAUDE_TIMEOUT}s) — killed, RC=$RC (attempt $ATTEMPT/$CLAUDE_MAX_ATTEMPTS)"
    else
      echo "claude exit=$RC (attempt $ATTEMPT/$CLAUDE_MAX_ATTEMPTS)"
    fi
    # RC 0 now requires fresh outputs from this attempt, not just process success.
    if [ "$TIMED_OUT" -eq 0 ] && [ "$RC" -eq 0 ]; then
      break
    fi
    if [ "$ATTEMPT" -ge "$CLAUDE_MAX_ATTEMPTS" ]; then
      if [ "$TIMED_OUT" -eq 1 ]; then
        echo "claude exhausted $CLAUDE_MAX_ATTEMPTS attempts — last one TIMED OUT"
        [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k agent hung past ${CLAUDE_TIMEOUT}s on all $CLAUDE_MAX_ATTEMPTS tries today ($DAY) and was killed — no fresh scan. Check logs/cron-$DAY.log"
      else
        echo "claude exhausted $CLAUDE_MAX_ATTEMPTS attempts — last exit=$RC"
        [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k agent failed (exit $RC) on all $CLAUDE_MAX_ATTEMPTS tries today ($DAY). Check logs/cron-$DAY.log"
      fi
      break
    fi
    echo "retrying claude in ${CLAUDE_RETRY_BACKOFF}s (attempt $((ATTEMPT+1))/$CLAUDE_MAX_ATTEMPTS)…"
    sleep "$CLAUDE_RETRY_BACKOFF"
    ATTEMPT=$((ATTEMPT+1))
  done
  fi

  # ---- Guard 2: positive confirmation the scan actually ran ----
	  if [ "$RC" -ne 0 ] || [ ! -s "$SCAN_LOG" ]; then
	    echo "INCOMPLETE RUN — no verified fresh scan, screen, and decision; refusing stale recommendations"
	    [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k did not complete a fresh scan and decision today ($DAY). No recommendation was published. Check logs/cron-$DAY.log"
	    exit 1
	  fi

	  # ---- Deterministic final decision from fresh agent state ----
	  # Each catalyst check can demote the current top candidate and promote the
	  # next one, so run a short bounded loop instead of a single check.
	  find "$REPO_ROOT/strategies/catalyst_check/state" -maxdepth 1 -type f \
	    \( -name '*.json' -o -name 'latest_summary.txt' \) -delete 2>/dev/null || true
	  FINAL_DECISION_FAILED=0
	  for _ in 1 2 3; do
	    if ! PYTHONPATH="$REPO_ROOT" "$PYTHON" \
	      "$REPO_ROOT/strategies/morning_decision/decide.py"; then
	      echo "morning_decision final pass failed"
	      FINAL_DECISION_FAILED=1
	      break
	    fi
	    if ! PYTHONPATH="$REPO_ROOT" "$PYTHON" \
	      "$REPO_ROOT/strategies/catalyst_check/check.py"; then
	      echo "catalyst_check final pass failed"
	      FINAL_DECISION_FAILED=1
	      break
	    fi
	  done
	  if [ "$FINAL_DECISION_FAILED" -eq 0 ]; then
	    if ! PYTHONPATH="$REPO_ROOT" "$PYTHON" \
	      "$REPO_ROOT/strategies/morning_decision/decide.py"; then
	      echo "morning_decision catalyst refresh failed"
	      FINAL_DECISION_FAILED=1
	    fi
	  fi
	  if [ "$FINAL_DECISION_FAILED" -ne 0 ]; then
	    [ "$MODE" = "morning" ] && slack_post ":rotating_light: csp_401k could not refresh the final morning decision today ($DAY) — no recommendation should be used. Check logs/cron-$DAY.log"
	    exit 1
	  fi

  # ---- The one Slack post ----
  # post_once.py is the SINGLE posting authority: it renders the agent's decision
  # and sends it, dedup'd by decision signature. Morning always posts exactly one
  # combined message (recap + any portfolio review); intraday posts only a fresh
  # trade/risk ticket. The agent writes decision data only, so a separate raw
  # webhook call cannot bypass the poster's deduplication record.
  if ! python3 post_once.py "$MODE"; then
    [ "$MODE" = "morning" ] && slack_post ":warning: csp_401k ran ($DAY) but couldn't post the daily recap — check logs/cron-$DAY.log"
    exit 1
  fi

  # ---- Optional locally configured price watch (never blocks the pipeline) ----
  # The legacy filename invokes the generic opt-in watcher. No config means no
  # request or notification; configured zones notify only on a new crossing.
  python3 hubs_watch.py || echo "hubs_watch failed (non-fatal)"

  # ---- Positive record that a morning pass got all the way to the Slack post ----
  # Read by Guard 0 (don't re-run on the next login) and by watchdog.sh, whose
  # absence alarm demands this stamp rather than matching failure strings from
  # a potentially unrelated run. Only completed notification delivery counts.
  [ "$MODE" = "morning" ] && echo "$DAY" > "$MORNING_STAMP"

  echo "=== done exit=$RC ==="
} >> "$LOG" 2>&1
