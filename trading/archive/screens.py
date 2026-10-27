"""
Screening tools: stocks down big, PE multiples, DCA candidates.
Uses Schwab API for real-time data.
"""
from auth import get_client


def screen_positions_down(client, positions, threshold_pct=-10):
    """
    Find positions that are down significantly from their recent highs.
    Good for identifying DCA opportunities in names you already own.
    """
    symbols = []
    pos_map = {}
    for pos in positions:
        sym = pos.get("instrument", {}).get("symbol", "")
        if sym and pos.get("instrument", {}).get("assetType") == "EQUITY":
            symbols.append(sym)
            pos_map[sym] = pos

    if not symbols:
        return []

    quotes = client.get_quotes(symbols)
    quotes.raise_for_status()
    quote_data = quotes.json()

    results = []
    for sym in symbols:
        q = quote_data.get(sym, {}).get("quote", {})
        high_52 = q.get("52WkHigh", 0)
        last = q.get("lastPrice", 0)
        if high_52 > 0 and last > 0:
            pct_from_high = ((last - high_52) / high_52) * 100
            pos = pos_map[sym]
            results.append({
                "symbol": sym,
                "price": last,
                "high_52w": high_52,
                "pct_from_high": pct_from_high,
                "day_change_pct": q.get("netPercentChange", 0),
                "your_avg_cost": pos.get("averagePrice", 0),
                "your_gain_pct": ((last - pos.get("averagePrice", 1)) / pos.get("averagePrice", 1)) * 100 if pos.get("averagePrice", 0) > 0 else 0,
                "market_value": pos.get("marketValue", 0),
                "quantity": pos.get("longQuantity", 0),
            })

    results.sort(key=lambda x: x["pct_from_high"])
    return [r for r in results if r["pct_from_high"] <= threshold_pct]


def screen_pe_multiples(client, symbols=None):
    """
    Pull PE ratios and basic fundamentals for a list of symbols.
    Useful for comparing valuations across your watchlist.
    """
    if symbols is None:
        symbols = [
            "NVDA", "GOOGL", "META", "AMZN", "TSM", "COIN", "AMD",
            "SHOP", "ASML", "NET", "NFLX", "AAPL", "HUBS", "NOW",
        ]

    quotes = client.get_quotes(symbols)
    quotes.raise_for_status()
    quote_data = quotes.json()

    results = []
    for sym in symbols:
        q = quote_data.get(sym, {}).get("quote", {})
        fund = quote_data.get(sym, {}).get("fundamental", {})

        pe = fund.get("peRatio", 0)
        fwd_pe = fund.get("pegRatio", 0)  # Sometimes available
        div_yield = fund.get("divYield", 0)
        eps = fund.get("eps", 0)
        mkt_cap = q.get("lastPrice", 0) * fund.get("sharesOutstanding", 0) if fund.get("sharesOutstanding") else 0

        results.append({
            "symbol": sym,
            "price": q.get("lastPrice", 0),
            "pe_ratio": pe,
            "eps": eps,
            "div_yield": div_yield,
            "day_change_pct": q.get("netPercentChange", 0),
            "high_52w": q.get("52WkHigh", 0),
            "low_52w": q.get("52WkLow", 0),
            "pct_from_high": ((q.get("lastPrice", 0) - q.get("52WkHigh", 1)) / q.get("52WkHigh", 1)) * 100 if q.get("52WkHigh", 0) > 0 else 0,
        })

    results.sort(key=lambda x: x["pe_ratio"] if x["pe_ratio"] > 0 else 9999)
    return results


def screen_dca_candidates(client, positions, *, max_pct_from_high=-15, max_pe=40):
    """
    Combine price-from-high and PE screens to find the best DCA candidates.
    These are stocks you own that are beaten down AND not crazy expensive.
    """
    down_big = screen_positions_down(client, positions, threshold_pct=max_pct_from_high)
    pe_data = screen_pe_multiples(client, [r["symbol"] for r in down_big])
    pe_map = {r["symbol"]: r for r in pe_data}

    results = []
    for r in down_big:
        pe_info = pe_map.get(r["symbol"], {})
        pe = pe_info.get("pe_ratio", 0)
        r["pe_ratio"] = pe
        r["eps"] = pe_info.get("eps", 0)
        if 0 < pe <= max_pe:
            r["dca_score"] = "STRONG"
        elif pe > max_pe:
            r["dca_score"] = "EXPENSIVE"
        else:
            r["dca_score"] = "N/A (no earnings)"
        results.append(r)

    return results


def print_down_screen(results):
    """Print stocks down from 52-week highs."""
    if not results:
        print("\nNo positions down significantly. Everything's near highs.")
        return

    print(f"\n--- Positions Down From 52-Week High ---")
    print(f"{'Symbol':<8} {'Price':>8} {'52w High':>10} {'From High':>10} {'Your Cost':>10} {'Your Gain':>9}")
    print("-" * 60)
    for r in results:
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} ${r['high_52w']:>9.2f} {r['pct_from_high']:>+9.1f}% ${r['your_avg_cost']:>9.2f} {r['your_gain_pct']:>+8.1f}%")


def print_pe_screen(results):
    """Print PE multiples screen."""
    print(f"\n--- PE Multiples (sorted cheapest to most expensive) ---")
    print(f"{'Symbol':<8} {'Price':>8} {'P/E':>8} {'EPS':>8} {'Div%':>6} {'From High':>10}")
    print("-" * 55)
    for r in results:
        pe_str = f"{r['pe_ratio']:.1f}" if r['pe_ratio'] > 0 else "N/A"
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} {pe_str:>8} {r['eps']:>8.2f} {r['div_yield']:>5.2f}% {r['pct_from_high']:>+9.1f}%")


def print_dca_candidates(results):
    """Print DCA candidates with scores."""
    if not results:
        print("\nNo DCA candidates right now (nothing is down enough).")
        return

    print(f"\n--- DCA Candidates (down big + reasonable PE) ---")
    print(f"{'Symbol':<8} {'Price':>8} {'From High':>10} {'P/E':>8} {'Score':<12} {'You Own':>10}")
    print("-" * 60)
    for r in results:
        pe_str = f"{r['pe_ratio']:.1f}" if r['pe_ratio'] > 0 else "N/A"
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} {r['pct_from_high']:>+9.1f}% {pe_str:>8} {r['dca_score']:<12} ${r['market_value']:>9,.0f}")


if __name__ == "__main__":
    from portfolio import get_all_positions

    client = get_client()
    positions = get_all_positions(client)

    print_pe_screen(screen_pe_multiples(client))
    print_down_screen(screen_positions_down(client, positions))
    print_dca_candidates(screen_dca_candidates(client, positions))
