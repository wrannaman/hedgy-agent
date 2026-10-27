"""
Is the US equity market open for regular trading today?

launchd fires the morning pipeline Mon-Fri but knows nothing about market
holidays — without this, the bot would wake on Memorial Day / Thanksgiving /
etc., scan stale data, and possibly Slack a bogus alert. run_daily.sh and
watchdog.sh call this first and bail quietly when the market is closed.

Exit 0 = market trades today.  Exit 1 = closed today (holiday or weekend).
On any error the check fails OPEN (exit 0) — a real run with other guards
beats silently skipping a trading day.

Run:  python3 market_open.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.auth import get_client
from schwab.client import Client


def market_trades_today():
    """True if the equity market has a regular session today."""
    client = get_client()
    r = client.get_market_hours(Client.MarketHours.Market.EQUITY, date=date.today())
    r.raise_for_status()
    # A trading day's equity entry carries a 'regularMarket' session; a holiday
    # or weekend has an empty sessionHours. The entry key varies ('EQ' vs
    # 'equity'), so scan the values.
    for entry in r.json().get("equity", {}).values():
        if "regularMarket" in (entry.get("sessionHours") or {}):
            return True
    return False


if __name__ == "__main__":
    try:
        is_open = market_trades_today()
    except Exception as e:
        print(f"market_open check failed ({e}) — assuming open", file=sys.stderr)
        sys.exit(0)
    print("OPEN" if is_open else "CLOSED")
    sys.exit(0 if is_open else 1)
