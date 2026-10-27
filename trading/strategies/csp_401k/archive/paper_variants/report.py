"""
Variant comparison report.

Groups paper trades by variant (rule_set field) and computes the metrics that
matter for promotion decisions.

Usage:
    python3 experiments/report.py
    python3 experiments/report.py --live    # include live trades as baseline_live
"""
import argparse
import json
import os
import sys
from datetime import datetime
from statistics import mean

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_PATH = os.path.join(ROOT, "state", "paper_options.json")
LIVE_PATH = os.path.join(ROOT, "state", "trade_log.json")


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def metrics_for(trades):
    """Expectancy, win rate, ROC, max drawdown, trade cadence for closed trades."""
    closed = [t for t in trades if t.get("status") == "closed" and t.get("pnl") is not None]
    if not closed:
        return {"n": 0}

    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    collateral = sum(t.get("max_loss", 0) for t in closed)
    total_pnl = sum(pnls)

    # Running drawdown
    running, peak, max_dd = 0, 0, 0
    for p in pnls:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    dates = [datetime.fromisoformat(t["opened"]).date() for t in closed if t.get("opened")]
    trades_per_month = None
    if len(dates) >= 2:
        span_days = max((max(dates) - min(dates)).days, 1)
        if span_days >= 7:
            trades_per_month = len(closed) / span_days * 30

    return {
        "n": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "expectancy": total_pnl / len(closed),
        "avg_win": mean(wins) if wins else 0,
        "avg_loss": mean(losses) if losses else 0,
        "total_pnl": total_pnl,
        "roc_pct": (total_pnl / collateral * 100) if collateral else 0,
        "max_drawdown": max_dd,
        "trades_per_month": trades_per_month,
    }


def group_by_variant(trades):
    groups = {}
    for t in trades:
        variant = t.get("rule_set") or t.get("variant") or "unknown"
        groups.setdefault(variant, []).append(t)
    return groups


def print_report(groups, title):
    print(f"\n=== {title} ===")
    if not groups:
        print("(no trades)")
        return

    header = (
        f"{'Variant':<20} {'N':>4} {'Win%':>6} {'Exp($)':>9} "
        f"{'Total':>9} {'ROC%':>7} {'MaxDD$':>9} {'/mo':>6}"
    )
    print(header)
    print("-" * len(header))
    for variant, trades in sorted(groups.items()):
        m = metrics_for(trades)
        if m["n"] == 0:
            print(f"{variant:<20} {0:>4} {'—':>6} {'—':>9} {'—':>9} {'—':>7} {'—':>9} {'—':>6}")
            continue
        tpm = f"{m['trades_per_month']:.1f}" if m["trades_per_month"] else "—"
        print(
            f"{variant:<20} {m['n']:>4} {m['win_rate']:>5.0f}% "
            f"${m['expectancy']:>7.0f} ${m['total_pnl']:>+7.0f} "
            f"{m['roc_pct']:>+6.2f}% ${m['max_drawdown']:>7.0f} {tpm:>6}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Include live trades as baseline_live row")
    args = parser.parse_args()

    paper = _load(PAPER_PATH) or {"positions": []}
    print_report(group_by_variant(paper.get("positions", [])), "PAPER VARIANTS")

    if args.live:
        live = _load(LIVE_PATH) or {"trades": []}
        live_trades = live.get("trades", [])
        for t in live_trades:
            t["rule_set"] = "baseline_live"
        print_report(group_by_variant(live_trades), "LIVE (baseline)")


if __name__ == "__main__":
    main()
