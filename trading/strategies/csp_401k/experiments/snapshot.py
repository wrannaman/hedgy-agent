"""
Daily market snapshot for replay + variant testing.

Dumps prices, changes, fundamentals, earnings distance, and ATM-30DTE implied
volatility for the watchlist. After ~60 days, experiments/replay.py can test
any new variant's entry rules against accumulated history. After ~250 days,
IV Rank becomes computable per name.

One file per trading day: state/market_snapshots/YYYY-MM-DD.json.

Usage: python3 experiments/snapshot.py
"""
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

_STRATEGY_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_STRATEGY_DIR))
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from event_scanner import EARNINGS_CALENDAR

WATCHLIST = [
    "NVDA", "GOOGL", "META", "AMZN", "TSM", "COIN", "AMD",
    "SHOP", "ASML", "NET", "NFLX", "AAPL", "HUBS", "MSFT", "IBIT",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(ROOT, "state", "market_snapshots")


def fetch_atm_iv(client, symbol, target_dte=30):
    """ATM-30DTE implied volatility for a symbol, from the put chain."""
    today = date.today()
    try:
        resp = client.get_option_chain(
            symbol=symbol,
            contract_type=client.Options.ContractType.PUT,
            strike_count=3,
            from_date=today + timedelta(days=max(target_dte - 7, 1)),
            to_date=today + timedelta(days=target_dte + 14),
        )
        resp.raise_for_status()
        chain = resp.json()
        underlying = chain.get("underlyingPrice", 0)
        if not underlying:
            return None

        best = None
        best_score = float("inf")
        for exp, strikes in chain.get("putExpDateMap", {}).items():
            for _, contracts in strikes.items():
                for c in contracts:
                    iv = c.get("volatility")
                    if iv is None or iv <= 0:
                        continue
                    strike = c["strikePrice"]
                    dte = c["daysToExpiration"]
                    score = abs(strike - underlying) / underlying + abs(dte - target_dte) * 0.005
                    if score < best_score:
                        best_score = score
                        best = {"strike": strike, "dte": dte, "iv": iv}
        return best
    except Exception as e:
        print(f"  IV fetch failed for {symbol}: {e}", file=sys.stderr)
        return None


def fetch_vix(client):
    """VIX tickers in Schwab vary; try a few known formats."""
    for sym in ("$VIX.X", "$VIX", "VIX", "$VIX.XO"):
        try:
            r = client.get_quotes([sym])
            r.raise_for_status()
            data = r.json().get(sym, {})
            price = data.get("quote", {}).get("lastPrice", 0)
            if price and price > 0:
                return {"symbol": sym, "price": price}
        except Exception:
            continue
    return None


def snapshot_market():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    client = get_client()
    today = date.today()
    now = datetime.now()

    all_symbols = ["SPY", "QQQ"] + WATCHLIST
    resp = client.get_quotes(all_symbols)
    resp.raise_for_status()
    data = resp.json()

    vix_info = fetch_vix(client)
    spy_q = data.get("SPY", {}).get("quote", {})
    qqq_q = data.get("QQQ", {}).get("quote", {})

    snapshot = {
        "date": str(today),
        "timestamp": now.isoformat(),
        "spy": spy_q.get("lastPrice"),
        "spy_change": spy_q.get("netPercentChange"),
        "qqq": qqq_q.get("lastPrice"),
        "qqq_change": qqq_q.get("netPercentChange"),
        "vix": vix_info["price"] if vix_info else None,
        "vix_source": vix_info["symbol"] if vix_info else None,
        "names": {},
    }

    for symbol in WATCHLIST:
        q = data.get(symbol, {}).get("quote", {})
        f = data.get(symbol, {}).get("fundamental", {})
        earnings_str = EARNINGS_CALENDAR.get(symbol)
        days_from_earnings = None
        if earnings_str:
            earnings = datetime.strptime(earnings_str, "%Y-%m-%d").date()
            days_from_earnings = (today - earnings).days

        iv = fetch_atm_iv(client, symbol)

        snapshot["names"][symbol] = {
            "price": q.get("lastPrice"),
            "change_pct": q.get("netPercentChange"),
            "52w_high": q.get("52WkHigh"),
            "52w_low": q.get("52WkLow"),
            "pe": f.get("peRatio"),
            "earnings": earnings_str,
            "days_from_earnings": days_from_earnings,
            "atm_iv_30d": iv["iv"] if iv else None,
            "iv_strike": iv["strike"] if iv else None,
            "iv_dte": iv["dte"] if iv else None,
        }

    path = os.path.join(SNAPSHOT_DIR, f"{today}.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)

    names_with_iv = sum(1 for n in snapshot["names"].values() if n["atm_iv_30d"])
    vix_str = f"{snapshot['vix']:.2f} ({snapshot['vix_source']})" if snapshot["vix"] else "None"
    spy_c = snapshot['spy_change'] or 0
    qqq_c = snapshot['qqq_change'] or 0
    print(f"Snapshot written: {path}")
    print(f"  SPY {spy_c:+.2f}% | QQQ {qqq_c:+.2f}% | VIX {vix_str}")
    print(f"  {len(snapshot['names'])} names, {names_with_iv} with ATM IV")
    return snapshot


if __name__ == "__main__":
    snapshot_market()
