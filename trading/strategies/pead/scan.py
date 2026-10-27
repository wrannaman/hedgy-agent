"""
pead/scan.py — the post-earnings-announcement-drift sleeve scanner.

Pulls the recent earnings calendar (shared/earnings.py, Finnhub), keeps universe
names that beat estimates decisively inside the entry window, enriches with live
spot via the Schwab client, and writes ranked long-only candidates to
state/last_screen.json (strategy="pead_long") for the morning engine to gate.

select_candidates() is pure (canned-payload testable); this wrapper does the I/O.
Fail-soft: a missing FINNHUB_API_KEY writes an empty screen with the reason —
the morning run never breaks on a feed problem.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

# Package import, NOT the sleeves' usual bare `import rules`: a bare import would
# shadow another sleeve's rules module when two sleeves load in one process
# (fund_engine, tests). Works standalone too since the repo root is on sys.path.
from strategies.pead import rules
from shared.universe import UNIVERSE

STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_PATH = STATE_DIR / "last_screen.json"


def surprise_pct(actual, estimate):
    """EPS surprise as % of |estimate|, or None when it can't be computed."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return round((actual - estimate) / abs(estimate) * 100, 1)


def select_candidates(calendar_rows, today, universe=None):
    """Pure selection: decisive positive surprises from universe names that
    reported within the entry window. Ranked by surprise %, capped per day."""
    universe = set(UNIVERSE if universe is None else universe)
    out = []
    for row in calendar_rows:
        sym = row.get("symbol")
        if sym not in universe:
            continue
        try:
            reported = date.fromisoformat(str(row.get("date"))[:10])
        except ValueError:
            continue
        days_since = (today - reported).days
        if not (0 <= days_since <= rules.ENTRY_WINDOW_DAYS):
            continue
        spct = surprise_pct(row.get("epsActual"), row.get("epsEstimate"))
        if spct is None or spct < rules.MIN_SURPRISE_PCT:
            continue
        out.append({
            "symbol": sym,
            "strategy": "pead_long",
            "report_date": str(reported),
            "days_since_report": days_since,
            "eps_actual": row.get("epsActual"),
            "eps_estimate": row.get("epsEstimate"),
            "surprise_pct": spct,
            # The grading horizon doubles as the rec's maturity date, so the
            # rec-grading loop treats it exactly like an option expiration.
            "expiration": str(reported + timedelta(days=rules.HOLD_DAYS)),
        })
    out.sort(key=lambda c: c["surprise_pct"], reverse=True)
    return out[:rules.MAX_CANDIDATES_PER_DAY]


def reaction_pct(candles, report_date, spot):
    """% move from the last close BEFORE the report date to the current spot —
    the market's verdict on the whole report. None if no pre-report close found."""
    pre = None
    for c in candles:
        d = datetime.fromtimestamp(c["datetime"] / 1000, tz=timezone.utc).date()
        if d < report_date and (pre is None or d > pre[0]):
            pre = (d, c["close"])
    if pre is None or not pre[1]:
        return None
    return round((spot - pre[1]) / pre[1] * 100, 1)


def enrich_with_quotes(client, candidates):
    """Attach live spot + post-report reaction; drop names under the penny floor
    or whose reaction fails the gate (rejects are kept in the output for
    visibility — a day-0 rejection is provisional, the name can resurface
    within the entry window if the market turns)."""
    if not candidates:
        return candidates, []
    resp = client.get_quotes([c["symbol"] for c in candidates])
    resp.raise_for_status()
    q = resp.json()
    kept, rejected = [], []
    for c in candidates:
        quote = q.get(c["symbol"], {}).get("quote", {})
        spot = quote.get("lastPrice") or quote.get("closePrice")
        if not spot or spot < rules.MIN_PRICE:
            continue
        c["spot"] = round(spot, 2)
        try:
            r = client.get_price_history_every_day(symbol=c["symbol"])
            r.raise_for_status()
            candles = r.json().get("candles", [])
        except Exception:
            candles = []
        c["reaction_pct"] = reaction_pct(
            candles, date.fromisoformat(c["report_date"]), spot)
        if c["reaction_pct"] is None or c["reaction_pct"] < rules.MIN_REACTION_PCT:
            c["rejected"] = (f"market reaction {c['reaction_pct']}% since the "
                             f"pre-report close — drift follows the reaction, not the EPS line")
            rejected.append(c)
        else:
            kept.append(c)
    return kept, rejected


def run_scan():
    from datetime import datetime
    today = date.today()
    out = {"timestamp": datetime.now().isoformat(), "candidates": [], "note": None}
    try:
        from shared.earnings import earnings_calendar, EarningsFeedError
        try:
            rows = earnings_calendar(today - timedelta(days=rules.ENTRY_WINDOW_DAYS), today)
            cands = select_candidates(rows, today)
            rejected = []
            if cands:
                from shared.auth import get_client
                cands, rejected = enrich_with_quotes(get_client(), cands)
            out["candidates"] = cands
            out["rejected_on_reaction"] = rejected
            out["reports_in_window"] = len(rows)
        except EarningsFeedError as e:
            out["note"] = str(e)
    except Exception as e:  # never break the morning pipeline
        out["note"] = f"pead scan failed: {e}"
    STATE_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(out, indent=2, default=str))
    return out


def print_report(out):
    print(f"=== PEAD SCREEN ===")
    if out.get("note"):
        print(f"  feed unavailable: {out['note']}")
        return
    for c in out.get("rejected_on_reaction", []):
        print(f"  ✗ {c['symbol']:6} beat by {c['surprise_pct']:+.0f}% BUT {c['rejected']}")
    if not out["candidates"]:
        print(f"  no candidates clear the gates "
              f"({out.get('reports_in_window', 0)} universe-adjacent reports checked)")
        return
    for c in out["candidates"]:
        print(f"  BUY-DRIFT {c['symbol']:6} beat by {c['surprise_pct']:+.0f}%, "
              f"market reaction {c['reaction_pct']:+.1f}% "
              f"(EPS {c['eps_actual']} vs {c['eps_estimate']} est, reported {c['report_date']}) "
              f"spot ${c.get('spot', '?')} — hold to ~{c['expiration']}")


if __name__ == "__main__":
    print_report(run_scan())
