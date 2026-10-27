"""
Reconcile the trade log against what the 401k account *actually* holds.

The trade log is written by hand during sessions. A recommendation is not a
fill: an order can be logged as "open" and never execute (placed too late, never
sent, rejected). When that happens the phantom position silently locks collateral
and gets excluded from the screener — for as long as nobody notices.

This module is the check that notices. The 401k has read-only Schwab access,
which is all we need: read the live option positions and confirm every logged-open
CSP is really there.

WHY THIS HAS MEMORY
-------------------
A logged-open position that never appeared at the broker differs from one that
was seen live and subsequently disappeared. The latter may have filled its close
order and requires fill reconciliation rather than a "never filled" verdict.

A stateless check cannot tell these two apart, and they demand OPPOSITE responses:

  never in the account       -> the order never filled; fix the log, free the collateral
  was in the account, now gone -> IT CLOSED; log the close, book the P&L

Absence is not evidence of never having existed. So this module now remembers whether
each trade has EVER been seen live (`state/reconcile_state.json`) and reports four
states instead of two. It also refuses to act on a single missing payload: a trade
must be missing on N consecutive checks before we treat it as anything but noise,
because one anomalous response silently unlocking collateral is how the screener
double-sizes into a position that is really still open.

Read-only with respect to the trade log and the broker — it records its own
observations and reports; callers decide. It never mutates the log or places orders.
"""
import json
import os
import re
from datetime import date

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "reconcile_state.json")

# A trade must be missing this many consecutive checks before its absence is treated as
# real. One bad/partial positions payload must not unlock collateral or flip the sizing
# math. 2 = "missing today and the previous check", i.e. absence persisted across a day.
MISSES_BEFORE_BELIEVED = 2

# Verdicts.
CONFIRMED = "confirmed"          # present in the account right now
LIKELY_CLOSED = "likely_closed"  # was confirmed live before, now gone -> a fill, not a phantom
PHANTOM = "phantom"              # never once seen live, and absent long enough to believe
PENDING = "pending"              # never seen live, but not yet missing long enough to judge

# OCC option symbol, e.g. "MU    260626P00565000" -> MU, 2026-06-26, PUT, 565.0
_OCC = re.compile(r"^(?P<root>[A-Z]+)\s*(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_occ_symbol(symbol):
    """Parse an OCC option symbol. Returns dict or None if it isn't one."""
    m = _OCC.match(symbol.strip())
    if not m:
        return None
    return {
        "underlying": m.group("root"),
        "expiration": f"20{m.group('yy')}-{m.group('mm')}-{m.group('dd')}",
        "put_call": "PUT" if m.group("cp") == "P" else "CALL",
        "strike": int(m.group("strike")) / 1000.0,
    }


def account_short_puts(positions):
    """Extract live short-put positions from a Schwab account `positions` list.

    Returns a list of {underlying, expiration, strike, contracts}.
    """
    out = []
    for p in positions or []:
        inst = p.get("instrument", {})
        if inst.get("assetType") != "OPTION":
            continue
        short_qty = p.get("shortQuantity", 0) or 0
        if short_qty <= 0:
            continue
        parsed = parse_occ_symbol(inst.get("symbol", ""))
        # Prefer explicit fields when present; fall back to the parsed OCC symbol.
        put_call = inst.get("putCall") or (parsed and parsed["put_call"])
        if put_call != "PUT":
            continue
        underlying = inst.get("underlyingSymbol") or (parsed and parsed["underlying"])
        if not parsed:
            continue
        out.append({
            "underlying": underlying,
            "expiration": parsed["expiration"],
            "strike": parsed["strike"],
            "contracts": short_qty,
        })
    return out


def _matches(trade, live):
    return (
        trade["symbol"] == live["underlying"]
        and trade["expiration"] == live["expiration"]
        and abs(trade["sell_strike"] - live["strike"]) < 0.01
    )


def load_state(path=STATE_PATH):
    """Per-trade observation history. Keys are trade ids as strings."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"trades": {}}


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def classify(open_trades, positions, state, today=None):
    """Match logged-open CSPs against live account short puts, with memory.

    Returns (results, state). `results` is a list of
    {trade, verdict, ever_confirmed, consecutive_misses, last_seen}, one per
    logged-open CSP. `state` is the updated observation history — the caller
    saves it (so a dry run can classify without recording).

    The verdict distinguishes a position that never existed (PHANTOM) from one
    that existed and is now gone (LIKELY_CLOSED). See the module docstring for
    why conflating them is the bug this exists to prevent.
    """
    today = today or date.today().isoformat()
    live = account_short_puts(positions)
    state = {"trades": dict(state.get("trades", {}))}
    results = []

    for t in open_trades:
        if t.get("strategy") != "cash_secured_put":
            continue
        key = str(t.get("id"))
        rec = dict(state["trades"].get(key, {}))
        present = any(_matches(t, l) for l in live)

        if present:
            rec["ever_confirmed"] = True
            rec["last_seen"] = today
            rec["consecutive_misses"] = 0
            verdict = CONFIRMED
        else:
            rec["ever_confirmed"] = rec.get("ever_confirmed", False)
            # Count one miss per distinct day, so re-running the scan doesn't inflate it.
            if rec.get("last_miss") != today:
                rec["consecutive_misses"] = rec.get("consecutive_misses", 0) + 1
                rec["last_miss"] = today
            believed = rec["consecutive_misses"] >= MISSES_BEFORE_BELIEVED
            if rec["ever_confirmed"]:
                # It was really there and now it isn't. That is a fill, not a phantom.
                # No miss threshold here: a position that vanishes after being confirmed
                # is the single most important thing to surface, immediately.
                verdict = LIKELY_CLOSED
            else:
                verdict = PHANTOM if believed else PENDING

        state["trades"][key] = rec
        results.append({
            "trade": t,
            "verdict": verdict,
            "ever_confirmed": rec.get("ever_confirmed", False),
            "consecutive_misses": rec.get("consecutive_misses", 0),
            "last_seen": rec.get("last_seen"),
        })

    return results, state


def collateral_locked(results):
    """Cash the account still has committed, per the results of `classify`.

    Everything except a believed PHANTOM keeps its collateral locked. A PENDING trade
    might be real and simply not have propagated; a LIKELY_CLOSED trade needs a human
    to confirm and book the close before we spend the money twice. Only a trade we are
    confident never existed releases its cash. Erring toward locked means the screener
    under-deploys; erring the other way means it double-sizes into a live position.
    """
    return sum(r["trade"]["sell_strike"] * 100 * r["trade"]["contracts"]
               for r in results if r["verdict"] != PHANTOM)


def by_verdict(results, verdict):
    return [r["trade"] for r in results if r["verdict"] == verdict]


def warn(results):
    """Print one loud block per problem class. No-op when everything is confirmed."""
    closed = [r for r in results if r["verdict"] == LIKELY_CLOSED]
    phantom = [r for r in results if r["verdict"] == PHANTOM]
    pending = [r for r in results if r["verdict"] == PENDING]

    if closed:
        print("=" * 60)
        print(f"!!! {len(closed)} position(s) CLOSED — confirmed live before, now gone:")
        for r in closed:
            t = r["trade"]
            print(f"    #{t.get('id')} {t['symbol']} ${t['sell_strike']:.0f} put exp {t['expiration']} "
                  f"— last seen {r['last_seen']}.")
        print("    This is a FILL, not a phantom. Pull the fill price from Schwab order status")
        print("    and close it in trade_log.json (trade_log.log_trade_close) so the P&L books.")
        print("    EXCEPTION: if the put expired IN the money, the 'close' was an ASSIGNMENT —")
        print("    shares landed in the account. Book it with `python wheel.py assign <id>`")
        print("    instead, which starts the wheel cycle and floors future call strikes at")
        print("    cost basis (RULES.md §13).")
        print("=" * 60)

    if phantom:
        print("=" * 60)
        print(f"!!! {len(phantom)} logged-open position(s) NEVER seen in the 401k account:")
        for r in phantom:
            t = r["trade"]
            print(f"    #{t.get('id')} {t['symbol']} ${t['sell_strike']:.0f} put exp {t['expiration']} "
                  f"— missing {r['consecutive_misses']} consecutive checks, never confirmed.")
        print("    Collateral for these is NOT locked. The order most likely never filled;")
        print("    verify, then set status to 'cancelled' in trade_log.json.")
        print("=" * 60)

    if pending:
        for r in pending:
            t = r["trade"]
            print(f"[reconcile] #{t.get('id')} {t['symbol']} ${t['sell_strike']:.0f} put not in the account "
                  f"({r['consecutive_misses']}/{MISSES_BEFORE_BELIEVED} checks) — collateral still locked "
                  f"until the absence persists.")


def reconcile(open_trades, positions):
    """Backwards-compatible two-list view: (confirmed, absent).

    Prefer `classify` — this shape is what conflated "never filled" with "closed"
    in the first place. Kept only so older callers keep working.
    """
    results, _ = classify(open_trades, positions, {"trades": {}})
    confirmed = by_verdict(results, CONFIRMED)
    absent = [r["trade"] for r in results if r["verdict"] != CONFIRMED]
    return confirmed, absent


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from shared.auth import get_client
    from shared.accounts import account_by_suffix, configured_account_suffix
    from trade_log import load_log
    from schwab import client as sc

    client = get_client()
    acct = account_by_suffix(client, configured_account_suffix())
    resp = client.get_account(acct["hashValue"], fields=[sc.Client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    positions = resp.json().get("securitiesAccount", {}).get("positions", [])

    open_trades = [t for t in load_log().get("trades", []) if t.get("status") == "open"]
    results, state = classify(open_trades, positions, load_state())
    save_state(state)

    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    summary = " | ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nothing open"
    print(f"Open CSPs in log: {len(results)} — {summary}")
    for r in results:
        t = r["trade"]
        print(f"  {r['verdict']:<14} #{t.get('id')} {t['symbol']} ${t['sell_strike']:.0f} put exp {t['expiration']}")
    warn(results)
    print(f"Collateral treated as locked: ${collateral_locked(results):,.0f}")
