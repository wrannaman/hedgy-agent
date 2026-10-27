"""The replay loop — runs the ACTUAL production decision functions over historical
underlying closes and emits the realized P&L of every closed trade.

Two production seams, never reimplemented:
  - entry: screener_select.best_put_from_chain on a synthetic-but-Schwab-shaped chain.
  - management: decision.management_verdict (the same core monitor.py calls live).

The engine only does bookkeeping: mark open positions through the pricer, ask the
real verdict whether to close, realize P&L, free capital, re-enter. Swap the pricer
(BS-modeled today, recorded-chain tomorrow) and rerun the identical loop.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rules
from decision import management_verdict
from screener_select import best_put_from_chain

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth_chain import build_chain


def _default_entry(pricer, vol_model):
    """The real entry gate over a synthetic chain. Returns (symbol, asof, spot) -> hit|None."""
    def entry(symbol, asof, spot):
        vol = vol_model.vol(symbol=symbol, asof=asof)
        if vol is None:
            return None
        chain = build_chain(symbol, asof, spot, vol, pricer)
        return best_put_from_chain(chain, symbol)
    return entry


def run_backtest(symbol, prices, pricer, *, vol_model=None, entry=None,
                 start=None, end=None, bankroll=100_000.0, contracts=None, rs=rules):
    """Replay symbol over `prices` ([(date, close)]). Returns list[ClosedTrade dict].

    One position per name at a time (mirrors live sizing). entry defaults to the real
    gate over a synthetic chain (needs vol_model); tests inject a deterministic entry
    plus a fake pricer so outcomes are exact. rs lets the sweep vary management
    thresholds without editing rules.py.
    """
    if contracts is None:
        contracts = rs.CONTRACTS_PER_UNDERLYING
    if entry is None:
        if vol_model is None:
            raise ValueError("run_backtest needs either an explicit entry or a vol_model")
        entry = _default_entry(pricer, vol_model)

    series = sorted(prices, key=lambda r: r[0])
    if start is not None:
        series = [(d, c) for d, c in series if d >= start]
    if end is not None:
        series = [(d, c) for d, c in series if d <= end]

    cash = bankroll
    position = None
    closed = []

    def _close(pos, asof, mark, reason):
        nonlocal cash, position
        pnl = (pos["credit"] - mark) * 100 * pos["contracts"]
        cash += pos["collateral"] + pnl
        closed.append({
            "symbol": symbol,
            "opened": pos["opened"],
            "closed": asof,
            "strike": pos["strike"],
            "credit": pos["credit"],
            "contracts": pos["contracts"],
            "exit_mark": round(mark, 2),
            "pnl": round(pnl, 2),
            "exit_reason": reason,
            "dte_at_exit": (pos["expiry"] - asof).days,
            "days_in_trade": (asof - pos["opened"]).days,
        })
        position = None

    for asof, spot in series:
        # ---- mark + manage the open position via the REAL verdict ----
        if position is not None:
            dte = (position["expiry"] - asof).days
            if dte <= 0:
                # Expiry: realize intrinsic (worthless if OTM, assigned-equivalent if ITM).
                _close(position, asof, max(position["strike"] - spot, 0.0), "expiry")
            else:
                mark = pricer.put(spot=spot, strike=position["strike"], dte=dte,
                                  asof=asof, symbol=symbol)
                v = management_verdict(
                    credit=position["credit"], current_mid=mark, price=spot,
                    sell_strike=position["strike"], dte=dte,
                    days_in_trade=(asof - position["opened"]).days,
                    contracts=position["contracts"], rs=rs,
                )
                if v["do"] in ("CLOSE", "CUT"):
                    _close(position, asof, mark, v["do"])

        # ---- entry: only when flat and the collateral fits free cash ----
        if position is None:
            hit = entry(symbol, asof, spot)
            if hit:
                collateral = hit["strike"] * 100 * contracts
                if collateral <= cash:
                    cash -= collateral
                    position = {
                        "opened": asof,
                        "expiry": _add_days(asof, hit["dte"]),
                        "strike": hit["strike"],
                        "credit": hit["mid"],
                        "contracts": contracts,
                        "collateral": collateral,
                    }

    return closed


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=n)
