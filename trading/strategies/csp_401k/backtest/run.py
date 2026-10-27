"""CLI: replay one name over history and print the management-triad P&L distribution
WITH a vol-assumption sensitivity sweep.

    python3 backtest/run.py --symbol NVDA --start 2018-01-01 --vrp-mult 1.0,1.2,1.5

The headline is the sensitivity ACROSS vrp_mult columns: a result that only holds at
one assumed IV/RV markup is "we don't know," not evidence (plan / RULES.md §12). This
is the first measured — not borrowed — statement about whether the triad helps deep-OTM
single-name puts. It cannot measure absolute edge (that needs recorded option prices);
it measures relative rule behavior under a swept assumption.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prices import load_prices
from volmodel import RealizedVolModel
from pricer import BSReconstructedPricer
from engine import run_backtest
from report import summarize


def _parse_date(s):
    return date.fromisoformat(s) if s else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--vrp-mult", default="1.0,1.2,1.5")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--bankroll", type=float, default=100_000.0)
    args = ap.parse_args(argv)

    start, end = _parse_date(args.start), _parse_date(args.end)
    vrp_mults = [float(x) for x in args.vrp_mult.split(",")]

    # First pull may hit Schwab; cached thereafter. One fetch, reused across the sweep.
    try:
        prices = load_prices(args.symbol, start, end)
    except RuntimeError:
        from shared.auth import get_client
        prices = load_prices(args.symbol, start, end, client=get_client())

    if not prices:
        print(f"No price history for {args.symbol} in range.")
        return 1

    cols = []
    for vm in vrp_mults:
        vol_model = RealizedVolModel({args.symbol: prices}, window=args.window, vrp_mult=vm)
        pricer = BSReconstructedPricer(vol_model)
        closed = run_backtest(args.symbol, prices, pricer, vol_model=vol_model,
                              start=start, end=end, bankroll=args.bankroll)
        cols.append((vm, summarize(closed, args.bankroll)))

    span = f"{prices[0][0]} → {prices[-1][0]}"
    print(f"\n=== BACKTEST {args.symbol}  ({span}, {len(prices)} trading days) ===")
    print("Modeled BS pricer; IV = trailing-{}d realized vol × vrp_mult. RELATIVE rule\n"
          "behavior under a swept assumption — NOT absolute edge (RULES.md §12).\n"
          .format(args.window))

    label = f"{'metric':<18}"
    print(label + "".join(f"{f'vrp×{vm:g}':>14}" for vm, _ in cols))
    print("-" * (18 + 14 * len(cols)))

    def row(name, fmt, key):
        cells = []
        for _, s in cols:
            cells.append(format(s[key], fmt) if s.get("n") and key in s else "—")
        print(f"{name:<18}" + "".join(f"{c:>14}" for c in cells))

    print(f"{'trades':<18}" + "".join(f"{s.get('n', 0):>14}" for _, s in cols))
    row("win rate %", ".0f", "win_rate")
    row("mean P&L $", "+,.0f", "mean_pnl")
    row("median P&L $", "+,.0f", "median_pnl")
    row("total return %", "+.1f", "total_return_pct")
    row("max drawdown $", ",.0f", "max_drawdown")

    print("\nexit-reason histogram (count by branch that closed the trade):")
    all_reasons = sorted({r for _, s in cols for r in s.get("reasons", {})})
    for r in all_reasons:
        cells = [str(s.get("reasons", {}).get(r, 0)) for _, s in cols]
        print(f"  {r:<16}" + "".join(f"{c:>14}" for c in cells))

    return 0


if __name__ == "__main__":
    sys.exit(main())
