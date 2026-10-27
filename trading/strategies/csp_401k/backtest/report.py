"""Distribution stats + robustness scoring for the sweep.

The single discipline this module enforces (plan / RULES.md §12): a finding is only
promotable if it is ROBUST — its ranking holds across every vrp_mult column. A result
that flips when the assumed IV/RV markup changes is "we don't know," not evidence, and
is marked NOT robust here so it can never be cited as a reason to change rules.py.
"""
from __future__ import annotations

import statistics


def summarize(closed, bankroll):
    """Distribution summary for a list of ClosedTrade dicts. n==0 -> {"n": 0}."""
    if not closed:
        return {"n": 0}
    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    by_date = sorted(closed, key=lambda t: t["closed"])
    equity, peak, max_dd = bankroll, bankroll, 0.0
    for t in by_date:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    reasons = {}
    for t in closed:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    return {
        "n": len(closed),
        "win_rate": len(wins) / len(closed) * 100,
        "mean_pnl": statistics.mean(pnls),
        "median_pnl": statistics.median(pnls),
        "total_return_pct": sum(pnls) / bankroll * 100,
        "max_drawdown": max_dd,
        "reasons": reasons,
    }


def _marginal_metric(rows, dimension, value, vrp, metric):
    """Mean of `metric` over every grid row whose `dimension` == value, in the given
    vrp column. Marginalizes across all OTHER swept dimensions, so a dimension can be
    ranked on its own even in a full-factorial grid."""
    vals = []
    for r in rows:
        if r["params"].get(dimension) != value:
            continue
        s = r["by_vrp"].get(vrp, {})
        if s.get("n"):
            vals.append(s.get(metric, 0.0))
    return statistics.mean(vals) if vals else None


def rank_dimension(rows, dimension, vrp_mults, metric="total_return_pct"):
    """Rank the values of one swept `dimension` by `metric`, per vrp column, and judge
    robustness: the dimension's winner is robust only if the SAME value wins in every
    vrp column. Returns {dimension, winners_by_vrp, robust, winner}.
    """
    values = []
    for r in rows:
        v = r["params"].get(dimension)
        if v not in values:
            values.append(v)

    winners_by_vrp = {}
    for vrp in vrp_mults:
        scored = [(v, _marginal_metric(rows, dimension, v, vrp, metric)) for v in values]
        scored = [(v, m) for v, m in scored if m is not None]
        winners_by_vrp[vrp] = max(scored, key=lambda x: x[1])[0] if scored else None

    present = [w for w in winners_by_vrp.values() if w is not None]
    robust = bool(present) and len(set(present)) == 1
    return {
        "dimension": dimension,
        "metric": metric,
        "winners_by_vrp": winners_by_vrp,
        "robust": robust,
        "winner": present[0] if robust else None,
    }


def render(rows, dimensions, vrp_mults, metric="total_return_pct"):
    """A human-readable robustness report: for each swept dimension, the per-column
    winner and whether it is robust. Robust findings are the only promotion candidates."""
    lines = ["=== SWEEP ROBUSTNESS (metric: %s) ===" % metric,
             "A finding is promotable ONLY if ROBUST across all vrp_mult columns.", ""]
    for dim in dimensions:
        rk = rank_dimension(rows, dim, vrp_mults, metric)
        cols = "  ".join(f"vrp×{vm:g}={rk['winners_by_vrp'].get(vm)}" for vm in vrp_mults)
        tag = f"ROBUST → promote-candidate {dim}={rk['winner']}" if rk["robust"] else "NOT robust — do not cite"
        lines.append(f"{dim:<20} [{tag}]")
        lines.append(f"  winners: {cols}")
    return "\n".join(lines)
