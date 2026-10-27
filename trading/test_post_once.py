"""Exactly one morning message must be delivered, even when decision data changes.

The invariants that stop the double-post from coming back:
  1. the morning run posts exactly once, even if its decision changes
  2. an intraday run with no ticket posts nothing
  3. an intraday run with a NEW ticket still posts, even after the morning recap
  4. `watch` names are not an action — they never turn a no-trade day into a post
  5. `daily_summary` fills in a missing hunt_reason without eating the agent's keys
  6. a decision left over from yesterday never renders as today's trade
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "strategies" / "csp_401k"))

import daily_summary  # noqa: E402
import post_once  # noqa: E402
import slack_format  # noqa: E402

DAY = datetime.now().strftime("%Y-%m-%d")


class FakeSlack:
    """Stands in for requests.post — counts what actually reached the account owner."""

    def __init__(self):
        self.sent = []

    def __call__(self, url, json=None, timeout=None):
        self.sent.append(json["text"])
        return type("R", (), {"ok": True, "status_code": 200})()


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A csp_401k desk with isolated state — no live files, no live webhook."""
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "logs").mkdir()
    decision = state / "agent_decision.json"

    monkeypatch.setattr(daily_summary, "HERE", tmp_path)
    monkeypatch.setattr(daily_summary, "FUND_STATE", state)
    monkeypatch.setattr(daily_summary, "DECISION", decision)
    monkeypatch.setattr(post_once, "SENTINEL", state / "posted_today.json")
    monkeypatch.setattr(post_once, "_webhook", lambda: "https://slack.test/hook")
    monkeypatch.setattr(slack_format, "DECISION", decision)
    monkeypatch.setattr(slack_format, "SCAN_LOG", tmp_path / "logs" / f"{DAY}.jsonl")
    monkeypatch.setattr(slack_format, "BRIEF", tmp_path / "state" / "brief.json")

    slack = FakeSlack()
    monkeypatch.setattr(post_once.requests, "post", slack)

    def write(**decision_keys):
        decision.write_text(json.dumps({"date": DAY, **decision_keys}))

    return type("Desk", (), {"slack": slack, "write": staticmethod(write),
                             "decision": decision})()


def test_morning_posts_exactly_once_however_many_times_it_runs(desk):
    desk.write(new_trades=[], hunt_reason="Screened 169 names, none rich enough.")

    assert post_once.main("morning") == 0
    assert post_once.main("morning") == 0  # a re-run must not double up

    assert len(desk.slack.sent) == 1


def test_morning_does_not_repost_when_decision_changes(desk):
    desk.write(new_trades=[], hunt_reason="First decision.")
    assert post_once.main("morning") == 0

    desk.write(new_trades=[], hunt_reason="Changed after a retry.",
               portfolio_review=["REVIEW in taxable account: IWM put spread."])
    assert post_once.main("morning") == 0

    assert len(desk.slack.sent) == 1


def test_portfolio_review_renders_inside_the_one_morning_message(desk):
    desk.write(new_trades=[], hunt_reason="No 401k put cleared.",
               portfolio_review=[
                   "REVIEW in taxable account: IWM 289/276 put spread; maximum risk $7,742."
               ])

    assert post_once.main("morning") == 0

    assert len(desk.slack.sent) == 1
    assert "PORTFOLIO — taxable account, review-only" in desk.slack.sent[0]
    assert "IWM 289/276 put spread" in desk.slack.sent[0]


def test_intraday_portfolio_review_alone_stays_silent(desk):
    desk.write(new_trades=[], hunt_reason="No 401k put cleared.",
               portfolio_review=["REVIEW in taxable account: IWM put spread."])

    assert post_once.main("intraday") == 0

    assert desk.slack.sent == []


def test_intraday_without_a_ticket_stays_silent(desk):
    desk.write(new_trades=[], hunt_reason="Screened 169 names, none rich enough.")
    post_once.main("morning")

    assert post_once.main("intraday") == 0

    assert len(desk.slack.sent) == 1  # only the morning recap


def test_intraday_risk_exit_posts_even_after_the_morning_recap(desk):
    desk.write(new_trades=[], hunt_reason="Screened 169 names, none rich enough.")
    post_once.main("morning")

    # Position blows a risk exit at 11:30 — the agent rewrites the decision.
    desk.write(new_trades=["Buy to close 9 MARA (MARA) $8 puts · limit $0.11."],
               hunt_reason="Screened 169 names, none rich enough.")
    assert post_once.main("intraday") == 0

    assert len(desk.slack.sent) == 2
    assert "Buy to close" in desk.slack.sent[1]
    # ...but the 12:30 re-run sees the same ticket and shuts up.
    assert post_once.main("intraday") == 0
    assert len(desk.slack.sent) == 2


def test_intraday_ticket_before_morning_does_not_suppress_morning_recap(desk):
    desk.write(new_trades=["Buy to close 1 MARA (MARA) $8 put."],
               hunt_reason="Risk exit.")
    assert post_once.main("intraday") == 0

    desk.write(new_trades=[], hunt_reason="Morning hunt found nothing.")
    assert post_once.main("morning") == 0

    assert len(desk.slack.sent) == 2
    assert "Buy to close" in desk.slack.sent[0]
    assert "Morning hunt found nothing" in desk.slack.sent[1]


def test_watch_names_alone_do_not_trigger_an_intraday_post(desk):
    """Watch names without a trade remain a no-trade day and do not trigger a post."""
    desk.write(new_trades=[], hunt_reason="Screened 169 names, none rich enough.",
               watch=["Netflix (NFLX) — near its 52-week low."])
    post_once.main("morning")
    desk.slack.sent.clear()

    assert post_once.main("intraday") == 0

    assert desk.slack.sent == []


def test_morning_recap_carries_the_agents_watch_list(desk):
    """daily_summary used to overwrite the decision, silently eating `watch`."""
    desk.write(new_trades=[], hunt_reason="Screened 169 names, none rich enough.",
               watch=["Netflix (NFLX) — near its 52-week low."])

    post_once.main("morning")

    assert "WATCH — near lows (discuss, not a trade)" in desk.slack.sent[0]
    assert "Netflix (NFLX)" in desk.slack.sent[0]


def test_missing_hunt_reason_is_filled_without_dropping_the_agents_keys(desk):
    desk.write(new_trades=[], watch=["Oracle (ORCL) — near its 52-week low."])

    decision = daily_summary.ensure_decision()

    assert decision["hunt_reason"]  # a fallback reason appeared
    assert decision["watch"] == ["Oracle (ORCL) — near its 52-week low."]


def test_yesterdays_ticket_never_renders_as_todays(desk):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    desk.decision.write_text(json.dumps(
        {"date": yesterday, "new_trades": ["Sell to open 1 CleanSpark (CLSK) $10 put."]}))

    out = slack_format.build()

    assert "CleanSpark" not in out
    assert "• none" in out
