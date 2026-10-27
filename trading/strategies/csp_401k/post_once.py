#!/usr/bin/env python3
"""The ONE place the cron's normal morning notification is posted to Slack.

Before 2026-07-09 two things could post the same message: the agent (told to
render `slack_format.py` and send it whenever it had something to say) and
`run_daily.sh` (which fell back to its own recap whenever `alerts_today.json`
showed no trade alert). The agent's raw webhook call never wrote that file, so
the fallback fired too — the account owner got the same recap twice, a minute apart. Making
the agent "stay silent harder" was never going to hold; the agent now only
*decides* (writes `state/agent_decision.json`) and this script *posts*.

  morning   — always posts exactly one combined message: the options recap plus any
              portfolio-review item. Every later morning call that day is a no-op.
  intraday  — silent unless today's decision carries a `new_trades` ticket that
              hasn't gone out yet, so there's no "nothing found" chatter midday.

Morning uses a once-per-day flag. Intraday uses decision signatures, so a risk
exit ("Buy to close …") still reaches the account owner after the morning recap while an
unchanged ticket does not repeat.
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SENTINEL = HERE / "state" / "posted_today.json"

DAY = datetime.now().strftime("%Y-%m-%d")

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))
import daily_summary  # noqa: E402


from shared.notifications import webhook as _webhook


def _sent_today():
    try:
        s = json.loads(SENTINEL.read_text())
    except Exception:
        return {}
    return s if s.get("date") == DAY else {}


def _record(sent, signature, mode):
    sent.setdefault("date", DAY)
    sent.setdefault("signatures", [])
    sent["signatures"].append(signature)
    sent["version"] = 2
    if mode == "morning":
        sent["morning_posted"] = True
    SENTINEL.parent.mkdir(exist_ok=True)
    SENTINEL.write_text(json.dumps(sent))


def main(mode):
    decision = daily_summary.ensure_decision()
    new_trades = decision.get("new_trades") or []
    sent = _sent_today()

    if mode != "morning" and not new_trades:
        print("intraday, no ticket — staying silent")
        return 0

    # Morning means one notification, period. The decision can change during a
    # retry or manual rerun; that must not turn into another morning post. Old
    # sentinels predate version 2/morning_posted and came from the morning recap,
    # so their signature serves as the backwards-compatible guard. Version 2
    # distinguishes an unusual intraday-before-morning post correctly.
    legacy_morning = not sent.get("version") and sent.get("signatures")
    if mode == "morning" and (sent.get("morning_posted") or legacy_morning):
        print("morning message already posted today — skipping")
        return 0

    # The header carries a wall-clock time, so hash the decision, not the render.
    payload = json.dumps(
        [new_trades, decision.get("hunt_reason"), decision.get("watch"),
         decision.get("portfolio_review"), decision.get("notes")],
        sort_keys=True,
    )
    signature = hashlib.sha256(payload.encode()).hexdigest()[:16]
    if signature in sent.get("signatures", []):
        print(f"already posted this decision today ({signature}) — skipping")
        return 0

    import slack_format
    message = slack_format.build()
    hook = _webhook()
    if not hook:
        print("no SLACK_TRADING_WEBHOOK — not posting")
        return 1
    try:
        r = requests.post(hook, json={"text": message}, timeout=20)
    except requests.RequestException:
        print("Slack delivery failed; check network and local webhook configuration")
        return 1
    if not r.ok:
        print(f"slack post failed: {r.status_code}")
        return 1
    _record(sent, signature, mode)
    print(f"posted to Slack ({mode}, {len(new_trades)} ticket(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "morning"))
