"""
grade.py — the scorecard (FUND.md §6, the compounding loop).

Two feedback loops, kept strictly apart:

1. REALIZED — per-sleeve performance from CLOSED trades (scorecard/run). The honest
   loop: a sleeve earns its allocation on evidence, not vibes. With only a couple of
   closed trades it reports "insufficient sample" — that IS the correct answer.

2. RECOMMENDED (hypothetical) — every morning fund_engine journals each gated
   candidate + what it recommended (state/brief_journal.jsonl). Once a
   recommendation's own expiration passes, grade_recommendations() marks it to
   outcome from price history and appends to state/rec_grades.jsonl (idempotent).
   This compounds ~100x faster than the live book, BUT it grades hold-to-expiration,
   not managed exits (the live rules take profit at ~50%) — a labeled bias, never to
   be conflated with realized results.

Thresholds come from fund_rules.py (MIN_TRADES_FOR_EDGE, SLEEVE_KILL_EXPECTANCY).
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
import fund_rules as R

# Realized fills live in per-sleeve trade logs with the same schema. Aggregate
# all configured logs and group by strategy, including legacy entries stored in
# a different sleeve's journal.
TRADE_LOGS = [
    _ROOT / "strategies" / "csp_401k" / "state" / "trade_log.json",
    _ROOT / "strategies" / "index_vrp" / "state" / "trade_log.json",
]
TRADE_LOG = TRADE_LOGS[0]  # legacy name; csp-specific readers still use it
JOURNAL = _ROOT / "state" / "brief_journal.jsonl"
REC_GRADES = _ROOT / "state" / "rec_grades.jsonl"


def closed_trades():
    trades = []
    for log in TRADE_LOGS:
        if log.exists():
            trades += json.loads(log.read_text()).get("trades", [])
    return [t for t in trades if t.get("status") == "closed" and t.get("pnl") is not None]


def scorecard(trades=None):
    """Per-strategy realized stats + a verdict against the canonical thresholds."""
    trades = closed_trades() if trades is None else trades
    by_strategy = {}
    for t in trades:
        by_strategy.setdefault(t.get("strategy", "?"), []).append(t)

    rows = []
    for strat, ts in sorted(by_strategy.items()):
        n = len(ts)
        wins = sum(1 for t in ts if t["pnl"] > 0)
        total = sum(t["pnl"] for t in ts)
        expectancy = total / n
        if n < R.MIN_TRADES_FOR_EDGE:
            verdict = f"insufficient sample ({n}/{R.MIN_TRADES_FOR_EDGE})"
        elif expectancy <= R.SLEEVE_KILL_EXPECTANCY:
            verdict = "KILL — expectancy below floor"
        else:
            verdict = "trusted"
        rows.append({"strategy": strat, "n": n, "wins": wins, "win_pct": round(wins / n * 100),
                     "total_pnl": round(total), "expectancy": round(expectancy), "verdict": verdict})
    return rows


def run():
    rows = scorecard()
    print("=== SCORECARD (realized, closed trades) ===")
    if not rows:
        print("  no closed trades yet")
        return rows
    for r in rows:
        print(f"  {r['strategy']:18} n={r['n']:>3} win {r['win_pct']:>3}%  "
              f"P&L ${r['total_pnl']:>+6,}  exp ${r['expectancy']:>+5}/trade  — {r['verdict']}")
    return rows


# ----------------------------------------------------------------------
# Recommendation grading (hypothetical, hold-to-expiration)
# ----------------------------------------------------------------------

def grade_csp_at_expiry(strike, premium_dollars, spot_at_expiry):
    """Hypothetical P&L of one recommended cash-secured put held to expiration.
    OTM -> keep the premium; ITM -> premium minus the assignment shortfall
    (approximate mark-to-outcome: assumes assignment at expiry, no management)."""
    if spot_at_expiry >= strike:
        return round(premium_dollars)
    return round(premium_dollars - (strike - spot_at_expiry) * 100)


def grade_put_spread_at_expiry(short_strike, long_strike, credit_dollars, max_risk,
                               spot_at_expiry):
    """Hypothetical P&L of one recommended put spread held to expiration:
    above short strike -> keep credit; below long strike -> max loss; between -> partial."""
    if spot_at_expiry >= short_strike:
        return round(credit_dollars)
    if spot_at_expiry <= long_strike:
        return round(-max_risk)
    return round(credit_dollars - (short_strike - spot_at_expiry) * 100)


def grade_pead_at_horizon(entry_spot, position_dollars, spot_at_horizon,
                          spy_entry=None, spy_exit=None):
    """Hypothetical P&L of one recommended PEAD long at its hold horizon.
    pnl is the absolute move on the suggested position; excess vs SPY over the
    same window is recorded too (the drift claim is about excess return)."""
    ret = (spot_at_horizon - entry_spot) / entry_spot
    row = {"pnl": round((position_dollars or 0) * ret), "win": ret > 0,
           "return_pct": round(ret * 100, 1), "spot_at_expiry": spot_at_horizon}
    if spy_entry and spy_exit:
        spy_ret = (spy_exit - spy_entry) / spy_entry
        row["excess_vs_spy_pct"] = round((ret - spy_ret) * 100, 1)
    return row


def grade_rec(rec, spot_at_expiry, spy_entry=None, spy_exit=None):
    """Grade one journaled recommendation against the spot at its expiration
    (for PEAD: the hold horizon). Returns the graded row, or None for strategies
    without a grader yet."""
    strat = rec.get("strategy")
    if strat == "cash_secured_put":
        pnl = grade_csp_at_expiry(rec["strike"], rec.get("premium") or 0, spot_at_expiry)
    elif strat == "put_spread":
        pnl = grade_put_spread_at_expiry(rec["short_strike"], rec["long_strike"],
                                         rec.get("premium_dollars") or 0,
                                         rec.get("collateral") or 0, spot_at_expiry)
    elif strat == "pead_long":
        entry = rec.get("spot")
        if not entry:
            return None
        return grade_pead_at_horizon(entry, rec.get("collateral") or 0,
                                     spot_at_expiry, spy_entry, spy_exit)
    else:
        return None
    return {"pnl": pnl, "win": pnl > 0, "spot_at_expiry": spot_at_expiry}


def rec_key(entry_date, rec):
    """Idempotency key: one grade per (morning, contract)."""
    strike = rec.get("strike") or f"{rec.get('short_strike')}/{rec.get('long_strike')}"
    return f"{entry_date}|{rec.get('symbol')}|{rec.get('strategy')}|{strike}|{rec.get('expiration')}"


def _parse_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def close_on_date(candles, target):
    """Close on the target date, or the last close before it (early close/holiday).
    None if the history doesn't cover the date at all."""
    best = None
    for c in candles:
        # Candle stamps decoded as UTC — local-time decoding shifts a midnight-UTC
        # stamp to the previous day in California.
        d = datetime.fromtimestamp(c["datetime"] / 1000, tz=timezone.utc).date()
        if d <= target and (best is None or d > best[0]):
            best = (d, c["close"])
    # Require coverage reasonably near expiry — a series that ends weeks early
    # would silently grade against a stale price.
    if best is None or (target - best[0]).days > 5:
        return None
    return best[1]


def _read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def grade_recommendations(client, today=None, journal_path=JOURNAL,
                          grades_path=REC_GRADES):
    """Grade every journaled recommendation whose expiration has passed and that
    hasn't been graded yet. Appends to rec_grades.jsonl; idempotent by rec_key.
    Returns the newly graded rows."""
    today = today or date.today()
    done = {g["key"] for g in _read_jsonl(grades_path)}
    pending = []
    for entry in _read_jsonl(journal_path):
        for rec in entry.get("recommended", []):
            exp = _parse_date(rec.get("expiration"))
            if exp is None or exp >= today:
                continue  # not matured yet (grade strictly after expiration day)
            key = rec_key(entry.get("date"), rec)
            if key not in done:
                pending.append((key, entry.get("date"), exp, rec))
                done.add(key)  # dedupe within this run too
    if not pending or client is None:
        return []

    spot_cache = {}

    def candles_for(sym):
        if sym not in spot_cache:
            try:
                r = client.get_price_history_every_day(symbol=sym)
                r.raise_for_status()
                spot_cache[sym] = r.json().get("candles", [])
            except Exception:
                spot_cache[sym] = []
        return spot_cache[sym]

    new_rows = []
    for key, entry_date, exp, rec in pending:
        sym = rec.get("symbol")
        spot = close_on_date(candles_for(sym), exp)
        if spot is None:
            continue  # no usable price — leave ungraded, retry next run
        spy_entry = spy_exit = None
        if rec.get("strategy") == "pead_long":  # drift is an EXCESS-return claim
            spy = candles_for("SPY")
            rec_day = _parse_date(entry_date)
            spy_entry = close_on_date(spy, rec_day) if rec_day else None
            spy_exit = close_on_date(spy, exp)
        graded = grade_rec(rec, spot, spy_entry, spy_exit)
        if graded is None:
            continue
        new_rows.append({
            "key": key, "recommended_on": entry_date, "graded_at": str(today),
            "sleeve": rec.get("sleeve"), "strategy": rec.get("strategy"),
            "symbol": sym, "rank": rec.get("rank"), "verdict": rec.get("verdict"),
            "expiration": str(exp), **graded,
        })
    if new_rows:
        grades_path.parent.mkdir(exist_ok=True)
        with grades_path.open("a") as f:
            for row in new_rows:
                f.write(json.dumps(row) + "\n")
    return new_rows


def rec_scorecard(grades=None):
    """Per-strategy stats over graded recommendations (hypothetical, to-expiration)."""
    grades = _read_jsonl(REC_GRADES) if grades is None else grades
    by_strategy = {}
    for g in grades:
        by_strategy.setdefault(g.get("strategy", "?"), []).append(g)
    rows = []
    for strat, gs in sorted(by_strategy.items()):
        n = len(gs)
        wins = sum(1 for g in gs if g["win"])
        total = sum(g["pnl"] for g in gs)
        rows.append({"strategy": strat, "n": n, "wins": wins,
                     "win_pct": round(wins / n * 100), "total_pnl": round(total),
                     "expectancy": round(total / n),
                     "sample": f"{n}/{R.MIN_TRADES_FOR_EDGE}"})
    return rows


def run_recommendations(client=None):
    """Grade matured recommendations, then print the hypothetical scorecard."""
    new = grade_recommendations(client) if client else []
    rows = rec_scorecard()
    print("=== RECOMMENDED (hypothetical, held-to-expiration — NOT realized) ===")
    if not rows:
        print("  no matured recommendations graded yet (journal accrues daily)")
        return rows
    if new:
        print(f"  +{len(new)} newly graded this run")
    for r in rows:
        print(f"  {r['strategy']:18} n={r['n']:>3} win {r['win_pct']:>3}%  "
              f"P&L ${r['total_pnl']:>+6,}  exp ${r['expectancy']:>+5}/rec  "
              f"— sample {r['sample']}; bias: assumes hold to expiry, real rules exit at 50%")
    return rows


if __name__ == "__main__":
    run()
    run_recommendations()
