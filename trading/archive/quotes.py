"""
Real-time and historical quotes from Schwab.
"""
from auth import get_client


def get_quotes(client, symbols):
    """Get real-time quotes for a list of symbols."""
    resp = client.get_quotes(symbols)
    resp.raise_for_status()
    return resp.json()


def print_quotes(quotes):
    """Pretty-print quotes."""
    print(f"\n{'Symbol':<8} {'Last':>10} {'Change':>8} {'%':>7} {'Bid':>10} {'Ask':>10} {'Volume':>12}")
    print("-" * 70)

    for symbol, data in sorted(quotes.items()):
        q = data.get("quote", {})
        last = q.get("lastPrice", 0)
        change = q.get("netChange", 0)
        pct = q.get("netPercentChange", 0)
        bid = q.get("bidPrice", 0)
        ask = q.get("askPrice", 0)
        vol = q.get("totalVolume", 0)
        print(f"{symbol:<8} ${last:>9.2f} {change:>+7.2f} {pct:>+6.2f}% ${bid:>9.2f} ${ask:>9.2f} {vol:>11,}")


# the account owner's watchlist — the stocks he knows well
WATCHLIST = [
    "NVDA", "GOOGL", "META", "AMZN", "TSM",
    "COIN", "AMD", "SHOP", "ASML", "NET",
    "NFLX", "AAPL", "HUBS", "VERI", "IBIT",
]


if __name__ == "__main__":
    client = get_client()
    quotes = get_quotes(client, WATCHLIST)
    print_quotes(quotes)
