"""
Decision journal — the compounding loop.

Every hold-vs-close-vs-open fork gets a snapshot of the state of the world at
the moment the call was made: the position's remaining $/day, its cushion, the
best alternative the screener offered (or the idle-cash floor), the ratio that
drove the decision, plus VIX and free cash. Later, once the underlying reaches
the decision's expiration, `--grade` resolves each call into a winner or loser
by checking what the stock actually did.

This is the piece shadow_tracker.py and skipped_backcheck.py don't cover: those
grade closed trades and skipped screener candidates. This grades the *judgment*
itself — was holding the winner the right call vs the alternative we measured it
against? Over time the headline tells us whether the keep-vs-redeploy gate is
calibrated or whether we're systematically holding too long / closing too early.

Usage:
  record(...)                          # called inline by the cron agent at each fork
  python3 decision_journal.py --list   # show logged decisions
  python3 decision_journal.py --grade  # resolve decisions past their expiration
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

STATE_DIR = Path(__file__).resolve().parent / "state"
LOG_PATH = STATE_DIR / "decision_log.jsonl"


def record(kind, symbol, strike, expiration, decision, rationale, trigger="", **world):
    """Append one decision fork to the journal.

    kind:       "hold" | "close" | "open" | "no_trade"
    symbol/strike/expiration: the position (or candidate) the call is about
    decision:   the action taken, in plain words
    rationale:  why — the one-line justification, ideally with the $/day numbers
    trigger:    what surfaced the fork ("profit-velocity", "75%", "screener", ...)
    **world:    the state-of-the-world numbers — pass whatever you computed:
                stock_price, cushion_pct, dte, pct_of_max, position_remaining_per_day,
                best_alt_per_day, best_alt_label, ratio, vix, free_cash,
                screener_candidates. Stored verbatim so the call is auditable later.
    """
    STATE_DIR.mkdir(exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "date": str(date.today()),
        "kind": kind,
        "symbol": symbol,
        "strike": float(strike),
        "expiration": str(expiration)[:10],
        "trigger": trigger,
        "decision": decision,
        "rationale": rationale,
        "world": world,
        "grade": None,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Logged {kind} decision: {symbol} ${strike} — {decision}")
    return entry


def _load():
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _save(entries):
    with LOG_PATH.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _close_at_or_after(client, symbol, target):
    r = client.get_price_history_every_day(symbol=symbol)
    r.raise_for_status()
    for c in r.json().get("candles", []):
        d = datetime.fromtimestamp(c["datetime"] / 1000).date()
        if d >= target:
            return c["close"], d
    return None, None


def grade():
    """Resolve every ungraded decision whose expiration has passed.

    For a HOLD: if the stock finished at/above the strike the held put expired
    worthless — holding captured the remaining premium at no cost, so the call
    was RIGHT. If it finished below, the cushion was breached — flag it (the
    hold took on assignment we could have sidestepped by closing).

    For a CLOSE/OPEN/NO_TRADE we record the stock outcome for context; full
    grading of a rotation needs the redeploy leg, which shadow_tracker covers.
    """
    from shared.auth import get_client

    entries = _load()
    if not entries:
        print("No decisions logged yet.")
        return

    client = None
    today = date.today()
    graded_now = 0

    for e in entries:
        if e.get("grade"):
            continue
        if not e.get("expiration"):
            continue  # no-trade / undated forks aren't gradeable by expiration
        exp = datetime.strptime(e["expiration"], "%Y-%m-%d").date()
        if today < exp:
            continue
        if client is None:
            client = get_client()
        close, close_date = _close_at_or_after(client, e["symbol"], exp)
        if close is None:
            continue

        strike = e["strike"]
        safe = close >= strike
        rem = (e.get("world") or {}).get("position_remaining_per_day")

        if e["kind"] == "hold":
            if safe:
                verdict = "RIGHT_HOLD"
                note = (f"{e['symbol']} finished ${close:.2f} ≥ ${strike:.0f} — held put expired "
                        f"worthless, captured the remaining ~${rem}/day at no risk. Hold was correct.")
            else:
                verdict = "HOLD_BREACHED"
                note = (f"{e['symbol']} finished ${close:.2f} < ${strike:.0f} — cushion breached. "
                        f"Holding took on assignment a close would have avoided.")
        else:
            verdict = "OUTCOME_OTM" if safe else "OUTCOME_ITM"
            note = (f"{e['symbol']} finished ${close:.2f} vs ${strike:.0f} strike "
                    f"({'above' if safe else 'below'}).")

        e["grade"] = {
            "verdict": verdict,
            "stock_at_exp": round(close, 2),
            "exp_close_date": str(close_date),
            "note": note,
        }
        graded_now += 1
        print(f"  [{verdict}] {e['date']} {e['kind']} {e['symbol']} ${strike:.0f} — {note}")

    _save(entries)

    graded = [e for e in entries if e.get("grade")]
    holds = [e for e in graded if e["kind"] == "hold"]
    if holds:
        right = sum(1 for e in holds if e["grade"]["verdict"] == "RIGHT_HOLD")
        print(f"\nHeadline: {right}/{len(holds)} graded HOLD calls were correct "
              f"(stock stayed above strike).")
        if right < len(holds):
            print("  Some holds breached the cushion — review whether the gate is holding too long.")
    print(f"\nGraded {graded_now} new decision(s). {len(graded)}/{len(entries)} total resolved.")


def show():
    for e in _load():
        w = e.get("world") or {}
        g = e.get("grade")
        tag = g["verdict"] if g else "PENDING"
        rem = w.get("position_remaining_per_day", "?")
        alt = w.get("best_alt_per_day", "?")
        print(f"  [{tag:13}] {e['date']} {e['kind']:8} {e['symbol']} ${e['strike']:.0f} "
              f"(exp {e['expiration']}) | pos ${rem}/day vs alt ${alt}/day | {e['decision']}")


if __name__ == "__main__":
    if "--grade" in sys.argv:
        grade()
    elif "--list" in sys.argv:
        show()
    else:
        print(__doc__)
