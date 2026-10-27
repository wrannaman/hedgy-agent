"""
Paper options journal — simulate option trades with real Schwab quotes.

Mirror of trade_log.py + shadow_tracker.py but for imaginary trades.
Lets us test strategy variants (shorter DTE, looser entry rules) without
risking capital. Storage: paper_options.json.

Usage:
    python paper_options.py open NVDA 160 2026-05-15 3.80
    python paper_options.py open NVDA 160 2026-05-15 3.80 --contracts 1 --rules shortdte --notes "test"
    python paper_options.py close 1 1.50 "50% profit"
    python paper_options.py snapshot
    python paper_options.py resolve
    python paper_options.py show
    python paper_options.py list
    python paper_options.py stats
"""
import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.auth import get_client

PAPER_PATH = os.path.join(os.path.dirname(__file__), "state", "paper_options.json")
STARTING_CASH = 20000  # paper account starting balance

# --- Fill realism -----------------------------------------------------------
# A paper engine that hands out perfect fills promotes losers to real money.
# Every assumption below is deliberately pessimistic so a variant has to be
# good enough to survive real frictions before it earns live capital.
COMMISSION_PER_CONTRACT = 0.65   # Schwab options commission, each leg
MAX_REL_SPREAD = 0.35            # reject if (ask-bid)/mid exceeds this — untradeable
MIN_BID = 0.10                   # reject if no real bid — there's no buyer to sell into
SLIPPAGE_PER_SHARE = 0.0         # extra haircut beyond crossing the spread; bid-fill
                                 # already embeds the half-spread, raise this to model worse.


def _expiry_close(client, symbol, exp_date):
    """The stock's closing price on the expiration date (or the next session if
    that day wasn't a trading day). Real expiry price, not whatever it is today."""
    try:
        r = client.get_price_history_every_day(symbol=symbol)
        r.raise_for_status()
        for c in r.json().get("candles", []):
            d = datetime.fromtimestamp(c["datetime"] / 1000).date()
            if d >= exp_date:
                return c["close"]
    except Exception:
        pass
    return None


def load_paper():
    if os.path.exists(PAPER_PATH):
        with open(PAPER_PATH) as f:
            return json.load(f)
    return {
        "positions": [],
        "config": {"starting_cash": STARTING_CASH},
    }


def save_paper(data):
    with open(PAPER_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _option_snapshot(client, symbol, strike, expiration):
    """Fetch current bid/ask/mid for a specific put strike + expiration.

    Returns dict with stock_price, option_bid/ask/mid, dte — or None if not found.
    """
    today = date.today()
    exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    days_out = (exp_date - today).days

    q_resp = client.get_quotes([symbol])
    q_resp.raise_for_status()
    stock_price = q_resp.json()[symbol]["quote"]["lastPrice"]

    chain_resp = client.get_option_chain(
        symbol=symbol,
        contract_type=client.Options.ContractType.PUT,
        strike_count=40,
        from_date=today,
        to_date=today + timedelta(days=max(days_out + 2, 1)),
    )
    chain_resp.raise_for_status()
    chain = chain_resp.json()

    for exp, strikes_data in chain.get("putExpDateMap", {}).items():
        for _, contract_list in strikes_data.items():
            for c in contract_list:
                contract_exp = c.get("expirationDate", "")[:10]
                if c["strikePrice"] == strike and contract_exp == expiration:
                    bid = c["bid"]
                    ask = c["ask"]
                    return {
                        "stock_price": stock_price,
                        "option_bid": bid,
                        "option_ask": ask,
                        "option_mid": round((bid + ask) / 2, 2),
                        "dte": c["daysToExpiration"],
                    }
    return None


def open_paper_put(symbol, strike, expiration, limit_price, contracts=1,
                   rule_set="default", notes="", client=None):
    """Open a paper cash-secured put with a CONSERVATIVE fill.

    limit_price is only what the variant *wanted* — we ignore it as the fill and
    instead re-fetch the live book and fill the way a seller crossing the spread
    actually fills: at the bid, minus optional slippage, minus commission. If the
    contract is illiquid (no bid) or the spread is untradeable, we refuse the fill
    and return None (the variant simply doesn't get the trade — exactly like real
    life). This is the whole point: no variant gets to assume it sold at the price
    it hoped for.
    """
    if client is None:
        client = get_client()

    snap = _option_snapshot(client, symbol, strike, expiration)
    if snap is None:
        print(f"PAPER OPEN REJECTED: {symbol} ${strike} {expiration} — contract not found")
        return None

    bid, ask, mid = snap["option_bid"], snap["option_ask"], snap["option_mid"]
    if bid < MIN_BID:
        print(f"PAPER OPEN REJECTED: {symbol} ${strike} — no real bid (${bid:.2f}), can't sell into it")
        return None
    rel_spread = (ask - bid) / mid if mid > 0 else 1.0
    if rel_spread > MAX_REL_SPREAD:
        print(f"PAPER OPEN REJECTED: {symbol} ${strike} — spread too wide "
              f"({rel_spread*100:.0f}% of mid), untradeable")
        return None

    # Conservative fill: cross to the bid. If the variant was willing to sell for
    # even less than the bid, honor that lower price. Never above the bid.
    fill = min(limit_price, bid) - SLIPPAGE_PER_SHARE
    fill = round(fill, 2)
    open_fee = round(COMMISSION_PER_CONTRACT * contracts, 2)
    credit_total = round(fill * 100 * contracts - open_fee)
    max_loss = strike * 100 * contracts  # collateral at risk
    slippage = round(limit_price - fill, 2)  # what the variant's hope cost it

    paper = load_paper()
    position = {
        "id": len(paper["positions"]) + 1,
        "opened": datetime.now().isoformat(),
        "symbol": symbol,
        "strategy": "cash_secured_put",
        "contracts": contracts,
        "sell_strike": strike,
        "expiration": expiration,
        "intended_limit": limit_price,   # what the variant asked for
        "limit_price": fill,             # what it actually filled at — drives all P&L
        "fill_price": fill,
        "entry_bid": bid,
        "entry_ask": ask,
        "slippage_per_share": slippage,
        "open_fee": open_fee,
        "credit": credit_total,          # net of commission
        "max_loss": max_loss,
        "status": "open",
        "closed": None,
        "close_price": None,
        "close_reason": None,
        "pnl": None,
        "result": None,
        "rule_set": rule_set,
        "notes": notes,
        "snapshots": [],
    }
    paper["positions"].append(position)
    save_paper(paper)

    print(f"PAPER OPEN #{position['id']}: SELL {contracts} {symbol} {expiration} "
          f"${strike}P filled ${fill:.2f} (wanted ${limit_price:.2f}, bid ${bid:.2f}, "
          f"slip ${slippage:.2f}, fee ${open_fee:.2f})")
    print(f"  Net credit: ${credit_total} | Collateral: ${max_loss:,} | Rule set: {rule_set}")
    return position


def close_paper_put(position_id, close_price_per_share, reason=""):
    """Close a paper position at a specified price (buy-to-close)."""
    paper = load_paper()
    pos = next((p for p in paper["positions"] if p["id"] == position_id), None)
    if pos is None:
        print(f"No paper position #{position_id}")
        return None
    if pos["status"] != "open":
        print(f"Position #{position_id} already {pos['status']}")
        return None

    credit_per_share = pos["limit_price"]  # actual fill, set conservatively at open
    close_fee = round(COMMISSION_PER_CONTRACT * pos["contracts"], 2)
    # Buy-to-close at the given price (caller passes the ask — conservative), net of commission.
    pnl = round((credit_per_share - close_price_per_share) * 100 * pos["contracts"] - close_fee)

    pos["status"] = "closed"
    pos["closed"] = datetime.now().isoformat()
    pos["close_price"] = close_price_per_share
    pos["close_fee"] = close_fee
    pos["close_reason"] = reason
    pos["pnl"] = pnl
    pos["result"] = "win" if pnl > 0 else ("loss" if pnl < 0 else "break_even")

    save_paper(paper)
    print(f"PAPER CLOSE #{position_id}: BTC @ ${close_price_per_share:.2f} (fee ${close_fee:.2f}) | "
          f"P&L: ${pnl:+,} | Reason: {reason}")
    return pos


def snapshot_paper(client=None):
    """Daily mark-to-market: snapshot every open paper position."""
    if client is None:
        client = get_client()

    paper = load_paper()
    today = date.today()
    now = datetime.now()
    open_positions = [p for p in paper["positions"] if p["status"] == "open"]

    if not open_positions:
        print("No open paper positions to snapshot.")
        return

    print(f"=== PAPER SNAPSHOT {now.strftime('%Y-%m-%d %H:%M')} ===")
    for pos in open_positions:
        snap = _option_snapshot(client, pos["symbol"], pos["sell_strike"], pos["expiration"])
        if snap is None:
            print(f"  #{pos['id']} {pos['symbol']} ${pos['sell_strike']}P — could not fetch quote")
            continue

        credit_per_share = pos["limit_price"]
        # Hypothetical close at current ask (conservative — round-trip cost)
        hypothetical_pnl = round(
            (credit_per_share - snap["option_ask"]) * 100 * pos["contracts"]
        )
        pct_of_max = (credit_per_share - snap["option_mid"]) / credit_per_share * 100 \
            if credit_per_share > 0 else 0

        entry = {
            "date": str(today),
            "time": now.strftime("%H:%M"),
            "stock_price": snap["stock_price"],
            "option_bid": snap["option_bid"],
            "option_ask": snap["option_ask"],
            "option_mid": snap["option_mid"],
            "dte": snap["dte"],
            "hypothetical_pnl": hypothetical_pnl,
            "pct_of_max": round(pct_of_max, 1),
        }
        existing_dates = [s["date"] for s in pos["snapshots"]]
        if str(today) not in existing_dates:
            pos["snapshots"].append(entry)

        print(f"  #{pos['id']} {pos['symbol']} ${pos['sell_strike']}P exp {pos['expiration']} | "
              f"Stock ${snap['stock_price']:.2f} | Put ${snap['option_mid']:.2f} | "
              f"If closed: ${hypothetical_pnl:+,} ({pct_of_max:.0f}% of max) | DTE {snap['dte']}")

    save_paper(paper)


def resolve_expired(client=None):
    """Auto-close paper positions past their expiration date.

    Uses the most recent snapshot's stock price to determine the outcome:
    - Stock above strike → expired worthless → keep full credit
    - Stock at/below strike → assigned → P&L = (stock - strike) * 100 + credit
      (simulates being put the shares at strike, then marked at current price)
    """
    if client is None:
        client = get_client()

    paper = load_paper()
    today = date.today()
    resolved = 0

    for pos in paper["positions"]:
        if pos["status"] != "open":
            continue
        exp = datetime.strptime(pos["expiration"], "%Y-%m-%d").date()
        if exp >= today:
            continue

        # Use the actual closing price ON the expiration date, not today's price
        # (positions can be resolved days late). Fall back to live quote only if
        # price history is unavailable.
        stock_at_exp = _expiry_close(client, pos["symbol"], exp)
        if stock_at_exp is None:
            q = client.get_quotes([pos["symbol"]])
            q.raise_for_status()
            stock_at_exp = q.json()[pos["symbol"]]["quote"]["lastPrice"]

        credit_per_share = pos["limit_price"]
        if stock_at_exp > pos["sell_strike"]:
            # Expired worthless — full credit
            pnl = round(credit_per_share * 100 * pos["contracts"])
            reason = f"expired worthless (stock ${stock_at_exp:.2f} > strike ${pos['sell_strike']})"
            close_price = 0.0
        else:
            # Assigned — mark at current stock price
            intrinsic = pos["sell_strike"] - stock_at_exp
            pnl = round((credit_per_share - intrinsic) * 100 * pos["contracts"])
            reason = f"assigned (stock ${stock_at_exp:.2f} <= strike ${pos['sell_strike']})"
            close_price = intrinsic

        pos["status"] = "closed"
        pos["closed"] = datetime.now().isoformat()
        pos["close_price"] = close_price
        pos["close_reason"] = reason
        pos["pnl"] = pnl
        pos["result"] = "win" if pnl > 0 else ("loss" if pnl < 0 else "break_even")
        resolved += 1
        print(f"  RESOLVED #{pos['id']} {pos['symbol']} ${pos['sell_strike']}P — {reason} | P&L ${pnl:+,}")

    save_paper(paper)
    if resolved == 0:
        print("No expired paper positions to resolve.")


def show_paper(client=None):
    """Show paper portfolio: open positions with live marks + summary."""
    paper = load_paper()
    open_positions = [p for p in paper["positions"] if p["status"] == "open"]
    closed = [p for p in paper["positions"] if p["status"] == "closed"]

    print(f"\n=== PAPER OPTIONS PORTFOLIO ===")
    print(f"Open: {len(open_positions)} | Closed: {len(closed)}")

    if open_positions:
        if client is None:
            client = get_client()
        print(f"\n{'#':>3} {'Symbol':<7} {'Strike':>7} {'Exp':<12} {'Credit':>8} {'Mid':>7} {'Unreal':>9} {'%Max':>6} {'DTE':>5}")
        print("-" * 80)
        total_unreal = 0
        for pos in open_positions:
            snap = _option_snapshot(client, pos["symbol"], pos["sell_strike"], pos["expiration"])
            if snap:
                credit_per_share = pos["limit_price"]
                unreal = round((credit_per_share - snap["option_ask"]) * 100 * pos["contracts"])
                pct = (credit_per_share - snap["option_mid"]) / credit_per_share * 100
                total_unreal += unreal
                print(f"{pos['id']:>3} {pos['symbol']:<7} ${pos['sell_strike']:>6.0f} "
                      f"{pos['expiration']:<12} ${pos['credit']:>7,} ${snap['option_mid']:>6.2f} "
                      f"${unreal:>+8,} {pct:>5.0f}% {snap['dte']:>5}")
            else:
                print(f"{pos['id']:>3} {pos['symbol']:<7} ${pos['sell_strike']:>6.0f} "
                      f"{pos['expiration']:<12} ${pos['credit']:>7,} {'?':>7} {'?':>9} {'?':>6} {'?':>5}")
        print("-" * 80)
        print(f"Total unrealized: ${total_unreal:+,}")

    paper_stats(paper)


def paper_stats(paper=None):
    """Performance summary for paper trades."""
    if paper is None:
        paper = load_paper()
    closed = [p for p in paper["positions"] if p["status"] == "closed"]
    if not closed:
        print("\nNo closed paper trades yet.")
        return

    wins = [p for p in closed if p["result"] == "win"]
    losses = [p for p in closed if p["result"] == "loss"]
    total_pnl = sum(p["pnl"] for p in closed if p["pnl"] is not None)
    total_credit = sum(p["credit"] for p in closed)
    total_collateral = sum(p["max_loss"] for p in closed)

    print(f"\n=== PAPER PERFORMANCE ===")
    print(f"Closed trades: {len(closed)} | Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win rate: {len(wins)/len(closed)*100:.0f}%")
    print(f"Realized P&L: ${total_pnl:+,}")
    print(f"Total credit collected: ${total_credit:,}")
    print(f"Return on collateral: {total_pnl/total_collateral*100:+.2f}%" if total_collateral else "")

    # Breakdown by rule_set for strategy comparison
    rule_sets = {}
    for p in closed:
        rs = p.get("rule_set", "default")
        rule_sets.setdefault(rs, []).append(p)
    if len(rule_sets) > 1:
        print(f"\nBy rule set:")
        for rs, positions in rule_sets.items():
            w = sum(1 for p in positions if p["result"] == "win")
            pnl = sum(p["pnl"] for p in positions if p["pnl"] is not None)
            print(f"  {rs}: {len(positions)} trades, {w} wins, P&L ${pnl:+,}")


def list_positions():
    paper = load_paper()
    if not paper["positions"]:
        print("No paper positions.")
        return
    for p in paper["positions"]:
        status = p["status"].upper()
        pnl = f"${p['pnl']:+,}" if p["pnl"] is not None else "—"
        print(f"  [{status:>6}] #{p['id']} {p['symbol']} ${p['sell_strike']}P "
              f"exp {p['expiration']} | credit ${p['credit']} | P&L {pnl} | rules: {p.get('rule_set', 'default')}")


def main():
    parser = argparse.ArgumentParser(description="Paper options journal")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="Open a paper CSP")
    p_open.add_argument("symbol")
    p_open.add_argument("strike", type=float)
    p_open.add_argument("expiration", help="YYYY-MM-DD")
    p_open.add_argument("credit", type=float, help="Premium per share (e.g. 3.80)")
    p_open.add_argument("--contracts", type=int, default=1)
    p_open.add_argument("--rules", default="default", help="Rule set name for comparison")
    p_open.add_argument("--notes", default="")

    p_close = sub.add_parser("close", help="Close a paper position")
    p_close.add_argument("id", type=int)
    p_close.add_argument("price", type=float, help="BTC price per share")
    p_close.add_argument("reason", nargs="?", default="")

    sub.add_parser("snapshot", help="Daily mark-to-market snapshot of open positions")
    sub.add_parser("resolve", help="Auto-close positions past expiration")
    sub.add_parser("show", help="Portfolio view with live marks")
    sub.add_parser("list", help="List all positions")
    sub.add_parser("stats", help="Performance summary")

    args = parser.parse_args()

    if args.cmd == "open":
        open_paper_put(args.symbol.upper(), args.strike, args.expiration,
                       args.credit, args.contracts, args.rules, args.notes)
    elif args.cmd == "close":
        close_paper_put(args.id, args.price, args.reason)
    elif args.cmd == "snapshot":
        snapshot_paper()
    elif args.cmd == "resolve":
        resolve_expired()
    elif args.cmd == "show":
        show_paper()
    elif args.cmd == "list":
        list_positions()
    elif args.cmd == "stats":
        paper_stats()


if __name__ == "__main__":
    main()
