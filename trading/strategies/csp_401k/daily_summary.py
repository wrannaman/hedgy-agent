#!/usr/bin/env python3
"""Fills in the parts of today's decision the agent didn't write, then renders it.

This does NOT own the message format. The shape (CURRENT / NEW / WATCH / NEAR MISS /
PAPER) lives in exactly ONE place — `trading/slack_format.py`.

It also does NOT own the decision. If the agent already wrote today's
`state/agent_decision.json`, every key it set is preserved — this script only
supplies a `hunt_reason` derived from the scan log when the agent left one out
(it died, or it took a no-action path that only touched the scan log). The old
behavior — rewrite the whole file — silently ate the agent's `watch` list on
2026-07-09.

Posting is `post_once.py`'s job. Nothing here sends Slack.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FUND_STATE = HERE.parents[1] / "state"
DECISION = FUND_STATE / "agent_decision.json"

DAY = datetime.now().strftime("%Y-%m-%d")


def _scan_log_reason():
    """(reason, daily_scan_entry) from today's scan log — agent's reason over the system's."""
    scan_log = HERE / "logs" / f"{DAY}.jsonl"
    if not scan_log.exists():
        return None, None
    daily = agent_reason = system_reason = None
    for line in scan_log.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("scan_type") == "daily_scan":
            daily = e
        if e.get("type") == "NO_ACTION" and e.get("reason"):
            # Prefer the agent's reason; an intraday scan logs a terse system
            # reason LATER in the file, so "last wins" alone would lose it.
            if e.get("source") == "agent":
                agent_reason = e["reason"]
            else:
                system_reason = e["reason"]
    return (agent_reason or system_reason), daily


def today_decision():
    """The agent's decision if it's from today, else {} — never yesterday's trade."""
    try:
        d = json.loads(DECISION.read_text())
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    stamped = d.get("date")
    if stamped:
        return d if stamped == DAY else {}
    try:
        written = datetime.fromtimestamp(DECISION.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return {}
    return d if written == DAY else {}


def ensure_decision():
    """Merge a fallback `hunt_reason` into today's decision. Returns it."""
    decision = today_decision()
    if not decision.get("hunt_reason"):
        reason, daily = _scan_log_reason()
        decision["hunt_reason"] = reason or (
            "looked at " + ", ".join(daily["dca_candidates"]) + ", nothing cleared"
            if daily and daily.get("dca_candidates")
            else "quiet, nothing dropped enough to clear the gates" if daily is not None
            else "today's scan data is missing — check the logs"
        )
    decision.setdefault("new_trades", [])
    decision["date"] = DAY
    FUND_STATE.mkdir(exist_ok=True)
    DECISION.write_text(json.dumps(decision))
    return decision


def build():
    ensure_decision()
    sys.path.insert(0, str(HERE.parents[1]))
    import slack_format  # noqa: E402
    return slack_format.build()


if __name__ == "__main__":
    print(build())
