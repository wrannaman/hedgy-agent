"""Behaviors the ONE renderer must hold (plan §Validation):
  1. a LIVE sleeve PASS (agent decision) renders under NEW
  2. a PAPER sleeve PASS renders under PAPER, never NEW
  3. the CURRENT table renders one labeled row per open position, with the
     stock / cushion / P&L columns kept distinct (the old "down 4%" merge bug).
  4. a position the NEW section says to close never still reads plain HOLD in
     the DO column; the displayed position and proposed action must agree.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slack_format  # noqa: E402


def _section(out, header):
    """Lines belonging to `header`, up to the next blank line or section break."""
    lines = out.splitlines()
    i = lines.index(header)
    body = []
    for line in lines[i + 1:]:
        if line == "" or line == "```":
            break
        body.append(line)
    return body


def test_live_sleeve_pass_renders_under_new():
    trade = "Sell to open 1 CleanSpark (CLSK) $10 put · limit $0.20 · day order. Trade it."
    out = slack_format.render({}, {"new_trades": [trade]}, {})
    new = _section(out, "NEW")
    assert any(trade in line for line in new)
    assert "PAPER — proving out, NOT actionable (tracking only)" not in out


def test_structured_ticket_renders_as_table_with_note():
    trade = {"do": "SELL 1 RBLX $45 put 8/21", "open": "limit $1.40 day",
             "collect": "$140", "frozen": "$4,500 (4.9%)",
             "buy_price": "$45 = 21% below · ~1-in-6",
             "note": "on fill set GTC buy-to-close $0.70, end 7/31. Trade it."}
    out = slack_format.render({}, {"new_trades": [trade]}, {})
    new = _section(out, "NEW")
    assert new[0].startswith("WHAT TO DO")
    assert "OPEN" in new[0] and "COLLECT" in new[0] and "FROZEN" in new[0] and "BUY PRICE" in new[0]
    row = new[1]
    assert row.startswith("SELL 1 RBLX $45 put 8/21")
    assert "limit $1.40 day" in row and "$140" in row
    assert "$4,500 (4.9%)" in row and "1-in-6" in row
    assert new[2].startswith("  - on fill set GTC")
    assert not any(line.startswith("• ") for line in new)  # table, not bullets


def test_paper_sleeve_pass_renders_under_paper_never_new():
    paper_line = "pead: MU buy-drift — sleeve unvalidated (0/100 forward trades)"
    out = slack_format.render({}, {}, {"paper": [paper_line]})

    paper = _section(out, "PAPER — proving out, NOT actionable (tracking only)")
    assert any(paper_line in line for line in paper)

    # NEW must show the no-trade line, NOT the paper pick.
    new = _section(out, "NEW")
    assert all(paper_line not in line for line in new)
    assert any(line.startswith("• none") for line in new)


def test_current_table_one_row_per_position_with_distinct_columns():
    positions = {
        "WDC": {"symbol": "WDC", "strike": 470, "expiration": "2026-07-17",
                "stock_change": 9.8, "stock_price": 620, "pct_of_max": 33,
                "position_pnl": 130, "do": "HOLD"},
    }
    out = slack_format.render(positions, {}, {})
    rows = _section(out, "OPEN POSITIONS — what to do")
    # header row + exactly one position row
    assert len(rows) == 2
    row = rows[1]
    assert row.startswith("WDC")
    assert "$470p 7/17" in row          # POSITION column
    assert "+9.8%" in row               # STOCK TODAY (the underlying's day move)
    assert "24% below" in row           # STRIKE IS = (620-470)/620 -> distinct from P&L
    assert "+$130 (+33% of max)" in row # IF CLOSED NOW: dollars + % of max, kept together
    assert row.rstrip().endswith("HOLD")


def _hubs_position(do="HOLD"):
    return {"HUBS": {"symbol": "HUBS", "strike": 170, "expiration": "2026-09-18",
                     "stock_change": -0.7, "stock_price": 210.36, "pct_of_max": -30,
                     "position_pnl": -105, "do": do}}


def test_close_ticket_marks_the_position_row_as_overridden():
    """A proposed close must visibly override the synthetic position's HOLD verdict.
    The override has no field on the position, so the renderer reconciles the two.
    """
    trade = {"do": "BUY TO CLOSE 1 HUBS $170 put 9/18", "open": "limit $4.60 day",
             "collect": "-$460 cost", "frozen": "frees $17,000",
             "buy_price": "n/a — this closes the position", "note": "Cut it."}
    out = slack_format.render(_hubs_position(), {"new_trades": [trade]}, {})
    row = _section(out, "OPEN POSITIONS — what to do")[1]
    assert not row.rstrip().endswith("HOLD"), "DO column still contradicts the NEW ticket"
    assert "overridden, see NEW" in row
    assert "HOLD" in row, "monitor's mechanical verdict must stay visible"


def test_unrelated_new_trade_leaves_the_position_row_alone():
    """A sell-to-open on a DIFFERENT name must not mark an open position overridden."""
    trade = {"do": "SELL 1 RBLX $45 put 8/21", "open": "limit $1.40 day",
             "collect": "$140", "frozen": "$4,500", "buy_price": "$45", "note": "Trade it."}
    out = slack_format.render(_hubs_position(), {"new_trades": [trade]}, {})
    row = _section(out, "OPEN POSITIONS — what to do")[1]
    assert row.rstrip().endswith("HOLD")
    assert "overridden" not in row


def test_agreeing_close_verdict_is_not_double_labelled():
    """When monitor ALREADY says CLOSE there is no contradiction to flag, but the
    pointer to the ticket is still correct — what must never happen is a bare HOLD."""
    trade = {"do": "BUY TO CLOSE 1 HUBS $170 put 9/18", "open": "limit $1.75 day",
             "collect": "-$175", "frozen": "frees $17,000", "buy_price": "n/a", "note": "50% mark."}
    out = slack_format.render(_hubs_position(do="CLOSE"), {"new_trades": [trade]}, {})
    row = _section(out, "OPEN POSITIONS — what to do")[1]
    assert "CLOSE" in row
    assert "HOLD" not in row
