#!/usr/bin/env python3
"""THE single renderer for the morning Slack message — one source of truth for shape.

The judgment agent only records its call in state/agent_decision.json. After the
agent exits, run_daily.sh invokes post_once.py, which renders this output and sends
it. No other normal cron path renders or posts a message.

Inputs (all optional; render degrades cleanly):
  - logs/<DAY>.jsonl  — open-position monitor entries (same source as daily_summary.py)
  - state/agent_decision.json — trades, hunt, watch, and portfolio-review decisions
  - state/brief.json — {dial, near_misses: [str], paper: [str]} from fund_engine.py
Output: the exact Slack text. Running this module prints a local preview; only
post_once.py sends it.
"""
import json
import textwrap
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

DAY = datetime.now().strftime("%Y-%m-%d")
SCAN_LOG = HERE / "strategies" / "csp_401k" / "logs" / f"{DAY}.jsonl"
DECISION = HERE / "state" / "agent_decision.json"
BRIEF = HERE / "state" / "brief.json"
TRADE_LOG = HERE / "strategies" / "csp_401k" / "state" / "trade_log.json"


def _open_symbols():
    """Symbols with an open trade in trade_log.json, or None if unreadable.
    A position closed intraday keeps its stale monitor entries in today's log;
    without this filter it renders as still-open (CVNA, 2026-07-14)."""
    try:
        trades = json.loads(TRADE_LOG.read_text())
        if isinstance(trades, dict):
            trades = trades.get("trades", [])
        return {t["symbol"] for t in trades if t.get("status") == "open"}
    except Exception:
        return None


def _load_positions():
    positions = {}
    if SCAN_LOG.exists():
        for line in SCAN_LOG.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("scan_type") == "monitor" and e.get("symbol"):
                positions[e["symbol"]] = e
    still_open = _open_symbols()
    if still_open is not None:
        positions = {s: e for s, e in positions.items() if s in still_open}
    return positions


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _load_decision():
    """Today's agent decision, or {} if it's from a previous day.

    Without this, a morning where the agent dies before writing would render
    yesterday's `new_trades` as today's ticket. The agent stamps `date`; fall
    back to the file's mtime for decisions written before that was required.
    """
    d = _load_json(DECISION, {})
    if not d:
        return {}
    stamped = d.get("date")
    if stamped:
        return d if stamped == DAY else {}
    try:
        written = datetime.fromtimestamp(DECISION.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return {}
    return d if written == DAY else {}


def _row(e, override=False):
    """One CURRENT-table row. Three labeled facts, never merged (the old 'down 4%' bug).

    Column semantics (the 2026-07-08 MARA confusion — these answer DIFFERENT questions):
      STOCK TODAY   — the underlying's move today. Health of the stock, not the trade.
      STRIKE IS     — how far the stock can fall before the short put is at the money.
                      Big number = safe trade, regardless of what P&L says today.
      IF CLOSED NOW — buy-back cost vs the credit collected (% of max profit). Negative
                      early in a trade is normal IV/mark noise on a fat-cushion put;
                      the number that matters is progress toward the +50% close.
    """
    sym = e.get("symbol", "?")
    strike = e.get("strike")
    chg = e.get("stock_change")
    spot = e.get("stock_price")
    pct = e.get("pct_of_max")
    pnl = e.get("position_pnl")
    do = e.get("do", "HOLD")
    # An agent override (CRON_PROMPT: confirmed bad news may escalate HOLD->CUT)
    # lands in new_trades as a buy-to-close, and used to leave THIS column showing
    # monitor.py's stale HOLD — so one message told the account owner both "HOLD" and "BUY TO
    # CLOSE" for the same position (2026-08-10, HUBS, third session running).
    # The override has no field on the position to write to, so reconcile it here:
    # keep monitor's mechanical verdict (the rules require transcribing it) and say
    # plainly that it was overridden, with the ticket in NEW carrying the detail.
    if override:
        do = f"{do} → overridden, see NEW"
    pos = f"${strike:g}p" if strike is not None else "?"
    exp = e.get("expiration")
    if exp:
        try:
            d = datetime.fromisoformat(exp)
            pos += f" {d.month}/{d.day}"
        except Exception:
            pass
    stock = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else "?"
    cushion = (f"{(spot - strike) / spot * 100:.0f}% below"
               if isinstance(spot, (int, float)) and isinstance(strike, (int, float)) and spot else "?")
    if isinstance(pct, (int, float)):
        money = (f"{'-' if pnl < 0 else '+'}${abs(pnl):,.0f} " if isinstance(pnl, (int, float)) else "")
        pnl_s = f"{money}({pct:+.0f}% of max)"
    else:
        pnl_s = "?"
    return f"{sym:<7} {pos:<14} {stock:<12} {cushion:<12} {pnl_s:<20} {do}"


def _new_row(t):
    """One NEW-table row: actionable facts in columns, additional context in a short note."""
    return (f"{t.get('do', '?'):<26} {t.get('open', '?'):<16} {t.get('collect', '?'):<8} "
            f"{t.get('frozen', '?'):<15} {t.get('buy_price', '?')}")


def _closing_overrides(new, symbols):
    """Symbols in the OPEN table that a NEW ticket tells the account owner to close.

    Matches by looking for each open symbol inside the ticket's `do` string
    rather than parsing the string's shape — the wording drifts ("BUY TO CLOSE
    1 HUBS $170 put 9/18", "CUT HUBS"), the ticker doesn't.
    """
    out = set()
    for t in new:
        if not isinstance(t, dict):
            continue
        do = str(t.get("do", "")).upper()
        if "CLOSE" not in do and "CUT" not in do:
            continue
        for sym in symbols:
            if sym.upper() in do:
                out.add(sym)
    return out


def _new_table(trades):
    out = [f"{'WHAT TO DO':<26} {'OPEN':<16} {'COLLECT':<8} {'FROZEN':<15} BUY PRICE"]
    for t in trades:
        out.append(_new_row(t))
        note = " ".join(str(t.get("note", "")).split())
        if note:
            out += textwrap.wrap(note, 92, initial_indent="  - ",
                                 subsequent_indent="    ")
    return out


def _bullets(items, width=92):
    """Render items as wrapped Slack bullets. One item -> one '•' bullet; newlines inside
    an item become indented continuation lines; anything past `width` wraps with a hanging
    indent. This is what turns a 900-char agent paragraph into something readable — the
    2026-07-02 recap crammed the whole hunt + watch list into one run-on line."""
    out = []
    for item in items:
        first = True
        for line in str(item).splitlines():
            line = " ".join(line.split())
            if not line:
                continue
            prefix = "• " if first else "  - "
            out += textwrap.wrap(line, width, initial_indent=prefix,
                                 subsequent_indent=" " * len(prefix))
            first = False
    return out


def render(positions, decision, brief):
    when = datetime.now().strftime("%a %-I:%M%p").replace("AM", "am").replace("PM", "pm")
    dial = (brief or {}).get("dial")
    head = f"*fund* · {when}"
    if dial:
        head += f"   ·   RISK DIAL: {dial.get('label','?').upper()} ({dial.get('floors','')})"
    new = (decision or {}).get("new_trades") or []
    overridden = _closing_overrides(new, positions or {})
    out = [head, "", "```", "OPEN POSITIONS — what to do"]
    if positions:
        out.append(f"{'TICKER':<7} {'POSITION':<14} {'STOCK TODAY':<12} {'STRIKE IS':<12} {'IF CLOSED NOW':<20} DO")
        for sym in sorted(positions):
            out.append(_row(positions[sym], override=sym in overridden))
    else:
        out.append("(no open positions — book is flat, nothing at risk)")

    out += ["", "NEW"]
    if new:
        # Structured tickets (dicts) render as a table; legacy strings stay bullets
        # so an old agent_decision.json never breaks the morning post.
        table = [t for t in new if isinstance(t, dict)]
        if table:
            out += _new_table(table)
        legacy = [t for t in new if not isinstance(t, dict)]
        if legacy:
            out += _bullets(legacy)
    else:
        reason = (decision or {}).get("hunt_reason") or "nothing cleared the gates"
        out += _bullets([f"none — {reason}"])

    # Discuss-tier names (RULES.md §1b): surfaced for a look, never trades. Their own
    # section so they can't get crammed into the hunt-reason bullet again.
    watch = (decision or {}).get("watch") or []
    if watch:
        out += ["", "WATCH — near lows (discuss, not a trade)"]
        out += _bullets(watch)

    # Taxable-account and cross-sleeve recommendations share this ONE rendered
    # notification with the options recap. Keeping them in a clearly labeled
    # section preserves the mandate boundary without creating a second poster.
    portfolio = (decision or {}).get("portfolio_review") or []
    if isinstance(portfolio, str):
        portfolio = [portfolio]
    if portfolio:
        out += ["", "PORTFOLIO — taxable account, review-only"]
        out += _bullets(portfolio)

    # Trend-flip exits are ACTION tickets (close open spreads), not commentary — they
    # outrank every informational section below.
    exits = (brief or {}).get("exit_tickets") or []
    if exits:
        out += ["", "🚪 TREND-FLIP EXITS — close open spreads (risk_off)"]
        out += _bullets(exits)

    near = (brief or {}).get("near_misses") or []
    if near:
        out += ["", "NEAR MISS — cleared the sleeve but blocked"]
        out += _bullets(near)

    paper = (brief or {}).get("paper") or []
    if paper:
        out += ["", "PAPER — proving out, NOT actionable (tracking only)"]
        out += _bullets(paper)

    # System notes (worldview-staleness nags, etc.) — meta lines that aren't a position,
    # a trade, or a name-specific watch. Kept out of hunt_reason so it stays about the hunt.
    notes = (decision or {}).get("notes") or []
    if notes:
        out += ["", "NOTES"]
        out += _bullets(notes)

    out.append("```")
    return "\n".join(out)


def build():
    return render(_load_positions(), _load_decision(), _load_json(BRIEF, {}))


if __name__ == "__main__":
    print(build())
