"""
Pull live portfolio positions and balances from Schwab.
"""
import json
from auth import get_client


def get_all_accounts(client):
    """Get all linked account numbers (hashed)."""
    resp = client.get_account_numbers()
    resp.raise_for_status()
    return resp.json()


def get_positions(client, account_hash, *, fields=None):
    """Get positions for a specific account."""
    resp = client.get_account(account_hash, fields=fields)
    resp.raise_for_status()
    return resp.json()


def get_all_positions(client):
    """Get positions across all linked accounts."""
    accounts = get_all_accounts(client)
    all_positions = []
    for acct in accounts:
        data = get_positions(client, acct["hashValue"])
        positions = data.get("securitiesAccount", {}).get("positions", [])
        for pos in positions:
            pos["_account"] = acct.get("accountNumber", "unknown")
        all_positions.extend(positions)
    return all_positions


def print_portfolio(positions):
    """Print a formatted portfolio summary."""
    print(f"\n{'Symbol':<8} {'Qty':>10} {'Avg Cost':>10} {'Mkt Value':>12} {'Gain/Loss':>10} {'%':>8}")
    print("-" * 62)

    total_value = 0
    total_cost = 0

    for pos in sorted(positions, key=lambda p: p.get("marketValue", 0), reverse=True):
        inst = pos.get("instrument", {})
        symbol = inst.get("symbol", "???")
        qty = pos.get("longQuantity", 0) or pos.get("shortQuantity", 0)
        avg_cost = pos.get("averagePrice", 0)
        mkt_value = pos.get("marketValue", 0)
        cost_basis = avg_cost * qty

        gain = mkt_value - cost_basis if cost_basis > 0 else 0
        pct = (gain / cost_basis * 100) if cost_basis > 0 else 0

        total_value += mkt_value
        total_cost += cost_basis

        print(f"{symbol:<8} {qty:>10.2f} {avg_cost:>10.2f} ${mkt_value:>11,.2f} ${gain:>9,.0f} {pct:>7.1f}%")

    total_gain = total_value - total_cost
    total_pct = (total_gain / total_cost * 100) if total_cost > 0 else 0
    print("-" * 62)
    print(f"{'TOTAL':<8} {'':>10} {'':>10} ${total_value:>11,.2f} ${total_gain:>9,.0f} {total_pct:>7.1f}%")


if __name__ == "__main__":
    client = get_client()
    positions = get_all_positions(client)
    print_portfolio(positions)
