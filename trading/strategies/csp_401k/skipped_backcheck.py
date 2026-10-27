"""
Back-check the screener's skipped/considered candidates.

The screener logs every candidate it surfaces to `state/skipped_log.jsonl`.
The judgment layer (Claude + the account owner) then trades zero, one, or some of them.
This script revisits each logged candidate after enough time has passed to
know how it would have played out — did the stock stay above the strike
(put would have expired worthless = we collected the premium had we sold it)
or break through (we'd have been assigned, with the realized P&L depending
on how far below the strike it ended up)?

It cross-references `state/trade_log.json` to label each candidate as
TRADED or SKIPPED, so over time we can ask:
- Of the candidates we skipped, what fraction would have won?
- Of the ones we traded, did we pick the best of the day's list?
- Does the bad-news filter let through losers or screen out winners?

Output is summary stats + a per-candidate verdict. Run weekly or on-demand.

Usage:
  python3 skipped_backcheck.py            # back-check all candidates past their expiration
  python3 skipped_backcheck.py --csv      # also write a flat CSV for spreadsheet analysis
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client

STATE_DIR = Path(__file__).resolve().parent / "state"
SKIPPED_LOG_PATH = STATE_DIR / "skipped_log.jsonl"
TRADE_LOG_PATH = STATE_DIR / "trade_log.json"
BACKCHECK_CSV_PATH = STATE_DIR / "skipped_backcheck.csv"


def load_skipped():
    if not SKIPPED_LOG_PATH.exists():
        return []
    with SKIPPED_LOG_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def load_traded_keys():
    """Set of (symbol, strike, expiration) for trades that were actually opened.
    Lets us label each logged candidate as TRADED vs SKIPPED.
    """
    if not TRADE_LOG_PATH.exists():
        return set()
    log = json.loads(TRADE_LOG_PATH.read_text())
    keys = set()
    for t in log.get("trades", []):
        exp = (t.get("expiration") or "")[:10]
        keys.add((t["symbol"], float(t["sell_strike"]), exp))
    return keys


def fetch_close_at_or_after(client, symbol, target_date):
    """The closing price on `target_date` (or the next trading day if that
    date wasn't a session). Used to find what the stock did on the expiration.
    """
    try:
        r = client.get_price_history_every_day(symbol=symbol)
        r.raise_for_status()
        candles = r.json().get("candles", [])
        for c in candles:
            dt = datetime.fromtimestamp(c["datetime"] / 1000).date()
            if dt >= target_date:
                return c["close"], dt
        return None, None
    except Exception:
        return None, None


def verdict_for(candidate, traded_keys, client):
    exp_str = candidate["expiration"][:10]
    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
    today = date.today()

    key = (candidate["symbol"], float(candidate["strike"]), exp_str)
    status = "TRADED" if key in traded_keys else "SKIPPED"

    if today < exp_date:
        return {
            "status": status,
            "outcome": "PENDING",
            "spot_at_exp": None,
            "would_have_won": None,
            "hypothetical_pnl": None,
            "exp_date": exp_str,
        }

    close, close_date = fetch_close_at_or_after(client, candidate["symbol"], exp_date)
    if close is None:
        return {
            "status": status,
            "outcome": "NO_DATA",
            "spot_at_exp": None,
            "would_have_won": None,
            "hypothetical_pnl": None,
            "exp_date": exp_str,
        }

    strike = candidate["strike"]
    premium = candidate["premium_dollars"]
    if close >= strike:
        # Put expired worthless — full premium would have been kept.
        return {
            "status": status,
            "outcome": "EXPIRED_OTM",
            "spot_at_exp": round(close, 2),
            "would_have_won": True,
            "hypothetical_pnl": premium,
            "exp_date": exp_str,
        }
    # Put would have been ITM at expiration. Assigned: own 100 shares at strike,
    # mark-to-market loss = (strike - close) × 100, offset by premium received.
    intrinsic_loss = (strike - close) * 100
    net = premium - intrinsic_loss
    return {
        "status": status,
        "outcome": "ASSIGNED_ITM",
        "spot_at_exp": round(close, 2),
        "would_have_won": net > 0,
        "hypothetical_pnl": round(net),
        "exp_date": exp_str,
    }


def run(write_csv=False):
    candidates = load_skipped()
    if not candidates:
        print("No skipped candidates logged yet. Run screener.py at least once.")
        return

    traded_keys = load_traded_keys()
    client = get_client()

    rows = []
    for c in candidates:
        v = verdict_for(c, traded_keys, client)
        rows.append({**c, **v})

    # Roll up by outcome × status.
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r["status"], r["outcome"])].append(r)

    print(f"\n=== SKIPPED-CANDIDATE BACK-CHECK {date.today()} ===")
    print(f"Total candidates logged: {len(rows)}")
    print(f"  TRADED: {sum(1 for r in rows if r['status'] == 'TRADED')}")
    print(f"  SKIPPED: {sum(1 for r in rows if r['status'] == 'SKIPPED')}\n")

    for (status, outcome), items in sorted(buckets.items()):
        wins = sum(1 for r in items if r["would_have_won"])
        pnl = sum(r["hypothetical_pnl"] or 0 for r in items)
        print(f"  {status:7} {outcome:13}  n={len(items):3}  wins={wins:3}  sum_hypothetical_pnl=${pnl:+,}")

    # The headline numbers the account owner actually cares about.
    settled = [r for r in rows if r["outcome"] in ("EXPIRED_OTM", "ASSIGNED_ITM")]
    skipped_settled = [r for r in settled if r["status"] == "SKIPPED"]
    if skipped_settled:
        skipped_wins = sum(1 for r in skipped_settled if r["would_have_won"])
        skipped_pnl = sum(r["hypothetical_pnl"] or 0 for r in skipped_settled)
        print(f"\nMissed-edge headline:")
        print(f"  {len(skipped_settled)} candidates we passed on are now settled.")
        print(f"  {skipped_wins}/{len(skipped_settled)} would have won "
              f"({100*skipped_wins/len(skipped_settled):.0f}%).")
        print(f"  Cumulative hypothetical P&L of skips: ${skipped_pnl:+,}")
        print(f"  If this number is consistently large + positive over time, the")
        print(f"  judgment layer is too conservative. If it's near zero or negative,")
        print(f"  the judgment layer is correctly filtering noise.")

    if write_csv:
        with BACKCHECK_CSV_PATH.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {len(rows)} rows to {BACKCHECK_CSV_PATH}")


if __name__ == "__main__":
    run(write_csv="--csv" in sys.argv)
