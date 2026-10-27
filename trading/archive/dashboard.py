"""
Main dashboard — run this for a full picture of your portfolio + opportunities.

Usage: python dashboard.py
"""
from auth import get_client
from portfolio import get_all_positions, print_portfolio
from quotes import get_quotes, print_quotes, WATCHLIST
from screens import (
    screen_pe_multiples, screen_positions_down, screen_dca_candidates,
    print_pe_screen, print_down_screen, print_dca_candidates,
)
from options import find_covered_calls, print_covered_calls


# Positions where you own 100+ shares (eligible for covered calls)
COVERED_CALL_CANDIDATES = {
    "NVDA": 501,
    "AMZN": 514,
    "GOOGL": 393,
    "META": 174,
    "COIN": 273,
    "SHOP": 250,
    "AMD": 195,
    "NFLX": 200,
    "TSM": 160,
}


def run_dashboard():
    client = get_client()

    # 1. Portfolio overview
    print("=" * 70)
    print("  PORTFOLIO OVERVIEW")
    print("=" * 70)
    positions = get_all_positions(client)
    print_portfolio(positions)

    # 2. Real-time quotes
    print("\n" + "=" * 70)
    print("  WATCHLIST QUOTES")
    print("=" * 70)
    quotes = get_quotes(client, WATCHLIST)
    print_quotes(quotes)

    # 3. PE multiples
    print("\n" + "=" * 70)
    print("  VALUATION SCREEN")
    print("=" * 70)
    print_pe_screen(screen_pe_multiples(client))

    # 4. Stocks down from highs (DCA opportunities)
    print("\n" + "=" * 70)
    print("  DCA OPPORTUNITIES (positions down >10% from 52w high)")
    print("=" * 70)
    print_down_screen(screen_positions_down(client, positions, threshold_pct=-10))
    print_dca_candidates(screen_dca_candidates(client, positions))

    # 5. Top covered call opportunities
    print("\n" + "=" * 70)
    print("  COVERED CALL INCOME OPPORTUNITIES")
    print("=" * 70)
    for symbol, shares in COVERED_CALL_CANDIDATES.items():
        try:
            results = find_covered_calls(client, symbol, shares, min_days=14, max_days=45)
            if results:
                print_covered_calls(symbol, results, top_n=3)
        except Exception as e:
            print(f"  {symbol}: Error fetching options — {e}")

    print("\n" + "=" * 70)
    print("  Done. Run `python paper_trade.py` to track simulated trades.")
    print("=" * 70)


if __name__ == "__main__":
    run_dashboard()
