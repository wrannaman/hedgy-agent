"""Threshold sweep — run the engine across the universe and a grid of rule overrides,
every cell repeated across the vrp_mult assumption.

Overrides are INJECTED, never written to rules.py: management thresholds ride in a
RuleSet passed to the engine (→ management_verdict), and the one entry-gate knob in the
grid (MIN_CUSHION_PCT) is applied by temporarily setting screener_select's module
global for the duration of a run and restoring it. rules.py stays the single source of
truth; promotion is still a human editing it and citing a robust §12 finding.
"""
from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rules
import screener_select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from volmodel import RealizedVolModel
from pricer import BSReconstructedPricer
from engine import run_backtest
from report import summarize, render


@dataclass
class RuleSet:
    """Swept thresholds, defaulting to the canonical rules.py values. Same attribute
    names management_verdict reads, so it drops in as the rs argument unchanged."""
    PROFIT_TARGET_PCT: float = rules.PROFIT_TARGET_PCT
    MANAGE_DTE: Optional[int] = rules.MANAGE_DTE
    MANAGE_DTE_CUTS_LOSERS: bool = rules.MANAGE_DTE_CUTS_LOSERS
    STOP_MULTIPLE: Optional[float] = rules.STOP_MULTIPLE
    STRIKE_PROXIMITY_PCT: float = rules.STRIKE_PROXIMITY_PCT
    MIN_CUSHION_PCT: float = rules.MIN_CUSHION_PCT
    CONTRACTS_PER_UNDERLYING: int = rules.CONTRACTS_PER_UNDERLYING


# The promotion grid (plan Phase 4). None means "rule off": MANAGE_DTE=None ->
# hold-to-expiry; STOP_MULTIPLE=None -> no mechanical stop.
DEFAULT_GRID = {
    "MANAGE_DTE": [14, 21, 28, None],
    "MANAGE_DTE_CUTS_LOSERS": [True, False],
    "PROFIT_TARGET_PCT": [35, 50, 65],
    "STOP_MULTIPLE": [2.0, 2.5, None],
    "MIN_CUSHION_PCT": [10, 15, 20],
}

_RULESET_FIELDS = {f.name for f in fields(RuleSet)}


def _ruleset_from(combo):
    return RuleSet(**{k: v for k, v in combo.items() if k in _RULESET_FIELDS})


def run_grid(symbols, prices_by_symbol, *, grid=None, vrp_mults=(1.0, 1.2, 1.5),
             window=30, bankroll=100_000.0, pricer_factory=None, entry_factory=None):
    """Full-factorial sweep. Returns list of {"params": combo, "by_vrp": {vrp: summary}}.

    Every (combo × vrp) cell is present (summary is {"n": 0} when no trade fired), so the
    matrix is complete and the report can rank without holes. pricer_factory/entry_factory
    are injection seams for deterministic tests (fake pricer, scripted entry).
    """
    grid = grid or DEFAULT_GRID
    dims = list(grid.keys())
    combos = [dict(zip(dims, vals)) for vals in itertools.product(*(grid[d] for d in dims))]

    rows = []
    for combo in combos:
        rs = _ruleset_from(combo)
        by_vrp = {}
        for vm in vrp_mults:
            vol_model = RealizedVolModel(prices_by_symbol, window=window, vrp_mult=vm)
            pricer = pricer_factory(vol_model) if pricer_factory else BSReconstructedPricer(vol_model)

            saved_cushion = screener_select.MIN_CUSHION_PCT
            screener_select.MIN_CUSHION_PCT = rs.MIN_CUSHION_PCT
            try:
                all_closed = []
                for sym in symbols:
                    prices = prices_by_symbol.get(sym) or []
                    if not prices:
                        continue
                    entry = entry_factory(sym, pricer, vol_model, rs) if entry_factory else None
                    all_closed.extend(run_backtest(
                        sym, prices, pricer, vol_model=vol_model, entry=entry,
                        bankroll=bankroll, rs=rs,
                    ))
            finally:
                screener_select.MIN_CUSHION_PCT = saved_cushion
            by_vrp[vm] = summarize(all_closed, bankroll)
        rows.append({"params": combo, "by_vrp": by_vrp})
    return rows


def main(argv=None):
    import argparse
    from datetime import date
    from prices import load_prices
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from universe import UNIVERSE

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default=None, help="comma list; default = full universe")
    ap.add_argument("--limit", type=int, default=None, help="cap universe size (cost control)")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--vrp-mult", default="1.0,1.2,1.5")
    ap.add_argument("--metric", default="total_return_pct")
    args = ap.parse_args(argv)

    symbols = args.symbols.split(",") if args.symbols else list(UNIVERSE)
    if args.limit:
        symbols = symbols[:args.limit]
    vrp_mults = tuple(float(x) for x in args.vrp_mult.split(","))
    start = date.fromisoformat(args.start)

    prices_by_symbol = {}
    for sym in symbols:
        try:
            prices_by_symbol[sym] = load_prices(sym, start, None)
        except RuntimeError:
            from shared.auth import get_client
            prices_by_symbol[sym] = load_prices(sym, start, None, client=get_client())

    rows = run_grid(symbols, prices_by_symbol, vrp_mults=vrp_mults)
    print(render(rows, list(DEFAULT_GRID.keys()), vrp_mults, metric=args.metric))
    return 0


if __name__ == "__main__":
    sys.exit(main())
