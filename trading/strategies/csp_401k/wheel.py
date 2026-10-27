"""
Wheel cycles — an assignment is the START of a cycle, not a standalone bag.

The wheel: sell a cash-secured put -> assigned -> own 100 shares/contract at
(strike - premium) basis -> sell covered calls against the shares -> called
away -> back to cash. csp_401k already runs the put half and covered_calls.py
the call half (IDEAS.md #2: "we already have ~80% of it"); this module is the
plumbing that connects them into ONE tracked cycle, plus the one discipline
rule that makes wheeling survivable (RULES.md §13):

    NEVER sell a call struck below the cycle's cost basis.
    The canonical wheel trap: assigned on a falling name, sell calls at/below
    basis "to keep the income coming", and a bounce calls the shares away at a
    locked-in loss. covered_calls.py enforces the floor via min_call_strikes().

State lives in trade_log.json under "wheels" — next to the trades it links —
so one file still holds the whole P&L story. Cycle P&L is a VIEW, not a second
book: each linked trade's pnl stays authoritative (circuit breaker, receipts);
the cycle adds only the share leg (exit price vs put strike) and sums.

    cost basis = put strike - credit / shares
    share_pnl  = (share exit price - put strike) * shares
    cycle_pnl  = put pnl + call pnls + share_pnl
    (share_pnl is vs STRIKE, not vs basis — the credit already lives in the
     put trade's pnl; measuring vs basis would double-count it.)

Recommendation-only, like everything here: nothing in this module places
orders or reads the broker. Assignments and dispositions are logged from
Schwab confirms in a live session with the account owner, same as every close.

CLI:
    python wheel.py                              # list cycles
    python wheel.py assign <trade_id>            # confirmed assignment -> start cycle
    python wheel.py call <wheel_id> <trade_id>   # link a covered-call trade to a cycle
    python wheel.py close <wheel_id> <price> [called_away|sold]
"""
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    from . import trade_log  # package import — SAME module object as the tests patch
except ImportError:
    import trade_log  # script / sys.path import


def load_wheels(log=None):
    log = log if log is not None else trade_log.load_log()
    return log.setdefault("wheels", [])


def active_cycles(log=None):
    return [w for w in load_wheels(log) if w["status"] == "holding_shares"]


def min_call_strikes(log=None):
    """{symbol: cost basis} for every cycle still holding shares — the strike FLOOR
    covered_calls.py must respect (RULES.md §13). Max basis wins if a symbol somehow
    has two cycles (it shouldn't: MAX_POSITIONS_PER_UNDERLYING)."""
    floors = {}
    for w in active_cycles(log):
        floors[w["symbol"]] = max(floors.get(w["symbol"], 0), w["cost_basis"])
    return floors


def start_cycle(put_trade_id, notes=""):
    """A confirmed assignment on an open CSP: close the put trade as 'assigned'
    (pnl = the credit — the option leg realized in full; the share leg belongs to
    the cycle) and open a wheel cycle holding the shares at (strike - premium) basis.
    """
    log = trade_log.load_log()
    trade = next((t for t in log["trades"] if t["id"] == put_trade_id), None)
    if trade is None:
        raise ValueError(f"no trade #{put_trade_id} in the log")
    if trade.get("strategy") != "cash_secured_put":
        raise ValueError(f"trade #{put_trade_id} is {trade.get('strategy')}, not a cash_secured_put")
    if trade.get("status") != "open":
        raise ValueError(f"trade #{put_trade_id} is {trade.get('status')}, not open")

    shares = trade["contracts"] * 100
    strike = trade["sell_strike"]
    credit = trade["credit"]
    basis = round(strike - credit / shares, 4)

    trade["status"] = "closed"
    trade["closed"] = datetime.now().isoformat()
    trade["result"] = "assigned"
    trade["pnl"] = credit
    trade["close_notes"] = (
        f"Assigned: bought {shares} {trade['symbol']} @ ${strike:g} "
        f"(basis ${basis:g} after credit). Wheel cycle started. " + notes
    ).strip()

    wheels = load_wheels(log)
    wheel = {
        "id": len(wheels) + 1,
        "symbol": trade["symbol"],
        "opened": datetime.now().isoformat(),
        "put_trade_id": put_trade_id,
        "shares": shares,
        "strike": strike,
        "put_credit": credit,
        "cost_basis": basis,
        "call_trade_ids": [],
        "status": "holding_shares",
        "closed": None,
        "exit": None,
        "notes": notes,
    }
    wheels.append(wheel)
    trade_log.save_log(log)
    print(f"Wheel #{wheel['id']}: {shares} {trade['symbol']} assigned @ ${strike:g}, "
          f"basis ${basis:g} — call strikes floor at basis (RULES.md §13)")
    return wheel


def record_call(wheel_id, call_trade_id):
    """Link an opened covered-call trade to its cycle so the cycle P&L sees it."""
    log = trade_log.load_log()
    wheel = next((w for w in load_wheels(log) if w["id"] == wheel_id), None)
    if wheel is None:
        raise ValueError(f"no wheel cycle #{wheel_id}")
    trade = next((t for t in log["trades"] if t["id"] == call_trade_id), None)
    if trade is None:
        raise ValueError(f"no trade #{call_trade_id} in the log")
    if trade["symbol"] != wheel["symbol"]:
        raise ValueError(f"trade #{call_trade_id} is {trade['symbol']}, cycle is {wheel['symbol']}")
    if trade["sell_strike"] < wheel["cost_basis"]:
        raise ValueError(
            f"call strike ${trade['sell_strike']:g} is BELOW cycle basis "
            f"${wheel['cost_basis']:g} — the locked-in-loss trap RULES.md §13 exists to prevent")
    if call_trade_id not in wheel["call_trade_ids"]:
        wheel["call_trade_ids"].append(call_trade_id)
    trade_log.save_log(log)
    return wheel


def close_cycle(wheel_id, share_exit_price, how="called_away", notes=""):
    """Shares left the account (called away at the call strike, or sold outright).
    Books the share leg vs the put strike and stamps the cycle closed."""
    log = trade_log.load_log()
    wheel = next((w for w in load_wheels(log) if w["id"] == wheel_id), None)
    if wheel is None:
        raise ValueError(f"no wheel cycle #{wheel_id}")
    if wheel["status"] != "holding_shares":
        raise ValueError(f"wheel #{wheel_id} is {wheel['status']}, not holding_shares")

    share_pnl = round((share_exit_price - wheel["strike"]) * wheel["shares"], 2)
    wheel["status"] = "closed"
    wheel["closed"] = datetime.now().isoformat()
    wheel["exit"] = {
        "how": how,  # "called_away" | "sold"
        "share_exit_price": share_exit_price,
        "share_pnl": share_pnl,
        "notes": notes,
    }
    trade_log.save_log(log)
    total = cycle_pnl(wheel, log)
    print(f"Wheel #{wheel_id} closed ({how} @ ${share_exit_price:g}): "
          f"share leg ${share_pnl:+,.2f}, full cycle ${total:+,.2f}")
    return wheel


def cycle_pnl(wheel, log=None):
    """Put credit + realized call pnls + share leg. None-pnl (still open) trades
    count 0 — the number grows as legs realize."""
    log = log if log is not None else trade_log.load_log()
    by_id = {t["id"]: t for t in log["trades"]}
    trade_ids = [wheel["put_trade_id"], *wheel["call_trade_ids"]]
    total = sum((by_id[i].get("pnl") or 0) for i in trade_ids if i in by_id)
    if wheel.get("exit"):
        total += wheel["exit"]["share_pnl"]
    return round(total, 2)


def show():
    log = trade_log.load_log()
    wheels = load_wheels(log)
    if not wheels:
        print("No wheel cycles. (No CSP has ever been assigned — 'assign <trade_id>' starts one.)")
        return
    for w in wheels:
        line = (f"#{w['id']} {w['symbol']} {w['status']}: {w['shares']} sh @ ${w['strike']:g} strike, "
                f"basis ${w['cost_basis']:g}, calls {w['call_trade_ids'] or 'none'}, "
                f"cycle P&L ${cycle_pnl(w, log):+,.2f}")
        if w.get("exit"):
            line += f" ({w['exit']['how']} @ ${w['exit']['share_exit_price']:g})"
        print(line)


def main(argv):
    if not argv:
        show()
    elif argv[0] == "assign":
        start_cycle(int(argv[1]))
    elif argv[0] == "call":
        record_call(int(argv[1]), int(argv[2]))
    elif argv[0] == "close":
        how = argv[3] if len(argv) > 3 else "called_away"
        close_cycle(int(argv[1]), float(argv[2]), how)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
