"""
Paper trading journal.

Since Schwab's API doesn't support paper trading, we track simulated trades
locally using real market prices from the API.
"""
import json
import os
from datetime import datetime
from auth import get_client

JOURNAL_PATH = os.path.join(os.path.dirname(__file__), "paper_trades.json")


def load_journal():
    """Load the paper trade journal from disk."""
    if os.path.exists(JOURNAL_PATH):
        with open(JOURNAL_PATH) as f:
            return json.load(f)
    return {"trades": [], "open_positions": {}}


def save_journal(journal):
    """Save the paper trade journal to disk."""
    with open(JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=2, default=str)


def paper_buy(client, symbol, quantity, *, order_type="market", limit_price=None, notes=""):
    """Record a paper buy using real market prices."""
    quotes = client.get_quotes([symbol])
    quotes.raise_for_status()
    quote_data = quotes.json()[symbol]["quote"]
    fill_price = limit_price if order_type == "limit" else quote_data["lastPrice"]

    journal = load_journal()

    trade = {
        "id": len(journal["trades"]) + 1,
        "timestamp": datetime.now().isoformat(),
        "action": "BUY",
        "symbol": symbol,
        "quantity": quantity,
        "price": fill_price,
        "total": fill_price * quantity,
        "order_type": order_type,
        "notes": notes,
    }
    journal["trades"].append(trade)

    # Update open positions
    pos = journal["open_positions"].get(symbol, {"quantity": 0, "avg_cost": 0, "total_cost": 0})
    new_total_cost = pos["total_cost"] + (fill_price * quantity)
    new_qty = pos["quantity"] + quantity
    pos["quantity"] = new_qty
    pos["avg_cost"] = new_total_cost / new_qty if new_qty > 0 else 0
    pos["total_cost"] = new_total_cost
    journal["open_positions"][symbol] = pos

    save_journal(journal)
    print(f"PAPER BUY: {quantity} {symbol} @ ${fill_price:.2f} = ${fill_price * quantity:,.2f}")
    return trade


def paper_sell(client, symbol, quantity, *, order_type="market", limit_price=None, notes=""):
    """Record a paper sell using real market prices."""
    journal = load_journal()
    pos = journal["open_positions"].get(symbol)

    if not pos or pos["quantity"] < quantity:
        print(f"Cannot sell {quantity} {symbol} — only have {pos['quantity'] if pos else 0}")
        return None

    quotes = client.get_quotes([symbol])
    quotes.raise_for_status()
    quote_data = quotes.json()[symbol]["quote"]
    fill_price = limit_price if order_type == "limit" else quote_data["lastPrice"]

    trade = {
        "id": len(journal["trades"]) + 1,
        "timestamp": datetime.now().isoformat(),
        "action": "SELL",
        "symbol": symbol,
        "quantity": quantity,
        "price": fill_price,
        "total": fill_price * quantity,
        "order_type": order_type,
        "realized_pnl": (fill_price - pos["avg_cost"]) * quantity,
        "notes": notes,
    }
    journal["trades"].append(trade)

    # Update position
    pos["quantity"] -= quantity
    pos["total_cost"] = pos["avg_cost"] * pos["quantity"]
    if pos["quantity"] <= 0:
        del journal["open_positions"][symbol]
    else:
        journal["open_positions"][symbol] = pos

    save_journal(journal)
    print(f"PAPER SELL: {quantity} {symbol} @ ${fill_price:.2f} = ${fill_price * quantity:,.2f} (P&L: ${trade['realized_pnl']:+,.2f})")
    return trade


def show_paper_portfolio(client):
    """Show current paper portfolio with live P&L."""
    journal = load_journal()
    positions = journal["open_positions"]

    if not positions:
        print("\nNo open paper positions.")
        return

    symbols = list(positions.keys())
    quotes = client.get_quotes(symbols)
    quotes.raise_for_status()
    quote_data = quotes.json()

    print(f"\n{'Symbol':<8} {'Qty':>8} {'Avg Cost':>10} {'Current':>10} {'Value':>12} {'P&L':>10} {'%':>8}")
    print("-" * 70)

    total_value = 0
    total_cost = 0

    for symbol, pos in sorted(positions.items()):
        current = quote_data[symbol]["quote"]["lastPrice"]
        value = current * pos["quantity"]
        cost = pos["avg_cost"] * pos["quantity"]
        pnl = value - cost
        pct = (pnl / cost * 100) if cost > 0 else 0

        total_value += value
        total_cost += cost

        print(f"{symbol:<8} {pos['quantity']:>8.1f} ${pos['avg_cost']:>9.2f} ${current:>9.2f} ${value:>11,.2f} ${pnl:>9,.0f} {pct:>+7.1f}%")

    total_pnl = total_value - total_cost
    total_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    print("-" * 70)
    print(f"{'TOTAL':<8} {'':>8} {'':>10} {'':>10} ${total_value:>11,.2f} ${total_pnl:>9,.0f} {total_pct:>+7.1f}%")


if __name__ == "__main__":
    client = get_client()
    show_paper_portfolio(client)
