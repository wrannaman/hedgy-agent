"""
Options chain lookup and analysis.

Fetch option chains for any symbol, filter by strategy, and identify
interesting plays (covered calls, cash-secured puts, etc.)
"""
import json
from datetime import datetime, timedelta
from auth import get_client


def get_option_chain(client, symbol, *, contract_type="ALL", strike_count=10,
                     from_date=None, to_date=None):
    """
    Fetch the option chain for a symbol.

    Args:
        symbol: Ticker symbol (e.g., "NVDA")
        contract_type: "CALL", "PUT", or "ALL"
        strike_count: Number of strikes above/below ATM to return
        from_date: Earliest expiration (datetime.date)
        to_date: Latest expiration (datetime.date)
    """
    kwargs = {
        "symbol": symbol,
        "contract_type": client.Options.ContractType(contract_type),
        "strike_count": strike_count,
    }
    if from_date:
        kwargs["from_date"] = from_date
    if to_date:
        kwargs["to_date"] = to_date

    resp = client.get_option_chain(**kwargs)
    resp.raise_for_status()
    return resp.json()


def find_covered_calls(client, symbol, shares_owned, *, min_days=7, max_days=45,
                       min_premium_pct=0.5):
    """
    Find attractive covered call candidates for a position you own.

    Returns calls that are OTM with decent premium relative to the stock price.
    """
    today = datetime.now().date()
    chain = get_option_chain(
        client, symbol,
        contract_type="CALL",
        strike_count=15,
        from_date=today + timedelta(days=min_days),
        to_date=today + timedelta(days=max_days),
    )

    underlying_price = chain.get("underlyingPrice", 0)
    if not underlying_price:
        print(f"Could not get underlying price for {symbol}")
        return []

    contracts_sellable = int(shares_owned // 100)
    if contracts_sellable == 0:
        print(f"Need at least 100 shares to sell covered calls. You have {shares_owned}.")
        return []

    results = []
    call_map = chain.get("callExpDateMap", {})

    for exp_date, strikes in call_map.items():
        for strike_str, contracts in strikes.items():
            for contract in contracts:
                strike = contract.get("strikePrice", 0)
                bid = contract.get("bid", 0)
                ask = contract.get("ask", 0)
                mid = (bid + ask) / 2
                delta = contract.get("delta", 0)
                theta = contract.get("theta", 0)
                iv = contract.get("volatility", 0)
                dte = contract.get("daysToExpiration", 0)
                otm_pct = (strike - underlying_price) / underlying_price * 100

                # Only OTM calls with real bids
                if strike <= underlying_price or bid <= 0:
                    continue

                premium_pct = mid / underlying_price * 100
                annualized = (premium_pct / max(dte, 1)) * 365

                if premium_pct >= min_premium_pct:
                    results.append({
                        "symbol": contract.get("symbol", ""),
                        "strike": strike,
                        "expiration": contract.get("expirationDate", ""),
                        "dte": dte,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "delta": delta,
                        "theta": theta,
                        "iv": iv,
                        "otm_pct": otm_pct,
                        "premium_per_contract": mid * 100,
                        "total_premium": mid * 100 * contracts_sellable,
                        "premium_pct": premium_pct,
                        "annualized_pct": annualized,
                        "contracts_sellable": contracts_sellable,
                    })

    results.sort(key=lambda x: x["annualized_pct"], reverse=True)
    return results


def print_covered_calls(symbol, results, top_n=10):
    """Pretty-print covered call candidates."""
    if not results:
        print(f"No covered call candidates found for {symbol}")
        return

    print(f"\n--- Covered Call Candidates for {symbol} (top {top_n}) ---")
    print(f"{'Strike':>8} {'DTE':>5} {'Bid':>7} {'Ask':>7} {'OTM%':>7} {'Prem%':>7} {'Ann%':>7} {'Delta':>7} {'$/Contract':>12} {'Total$':>10}")
    print("-" * 95)

    for r in results[:top_n]:
        print(f"{r['strike']:>8.1f} {r['dte']:>5} {r['bid']:>7.2f} {r['ask']:>7.2f} "
              f"{r['otm_pct']:>6.1f}% {r['premium_pct']:>6.2f}% {r['annualized_pct']:>6.1f}% "
              f"{r['delta']:>7.3f} ${r['premium_per_contract']:>10,.0f} ${r['total_premium']:>9,.0f}")


if __name__ == "__main__":
    client = get_client()

    # Example: find covered calls for NVDA (501 shares)
    symbol = "NVDA"
    shares = 501

    print(f"\nLooking up option chain for {symbol}...")
    results = find_covered_calls(client, symbol, shares)
    print_covered_calls(symbol, results)
