"""Modeled backtest: SPY defined-risk put spreads, 2008 -> today.

Research question: what does a hypothetical index-VRP spread sleeve at a reference
risk-capital allocation earn through a modeled full cycle, and does
vol-scaled deployment beat flat deployment or the current 2-slot cap?

What is MEASURED vs ASSUMED (honesty contract, same as csp_401k/backtest):
  - MEASURED: SPY daily closes, daily VIX level (real implied vol, not a markup
    assumption), daily VIX/VIX3M regime ratio. This is materially stronger than
    the single-name backtest, whose IV was realized-vol-times-assumed-markup.
  - ASSUMED: the skew multipliers that turn the VIX (an ~ATM 30d number) into
    the IV of a 30-delta and a 13-delta put. Swept across three settings; a
    conclusion only counts if it survives the sweep.
  - NOT modeled: intraday paths (marks are daily closes), early assignment
    (European-style marks; XSP is cash-settled so this is close), dividends on
    the SPY benchmark line (understates SPY ~1.5-2%/yr — noted in output).

Mechanics per live rules: sell 30d/13d put spread ~35 DTE, GTC close at 50% of
credit, otherwise hold to expiry; no new entries when VIX/VIX3M >= 1.0
(fund_rules.VIX_BACKWARDATION_RATIO). Costs: $5 per spread round trip.

Run:  PYTHONPATH=../.. ../../.venv/bin/python3 backtest.py
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist

HERE = Path(__file__).resolve().parent
CACHE = HERE / "state" / "bt_prices.json"

R = 0.03  # flat risk-free for BS pricing; credit levels are dominated by IV, not r
DTE_TARGET = 35
SHORT_DELTA_D1 = NormalDist().inv_cdf(0.70)  # put delta -0.30  -> N(d1)=0.70
LONG_DELTA_D1 = NormalDist().inv_cdf(0.87)   # put delta -0.13  -> N(d1)=0.87
PROFIT_TAKE = 0.50
COST_PER_SPREAD = 5.0
BACKWARDATION = 1.0
CAPITAL = 100_000.0

_N = NormalDist().cdf


def bs_put(spot, strike, t, iv):
    if t <= 0:
        return max(strike - spot, 0.0)
    sq = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (R + iv * iv / 2) * t) / sq
    d2 = d1 - sq
    return strike * math.exp(-R * t) * _N(-d2) - spot * _N(-d1)


def strike_for_d1(spot, t, iv, d1):
    """Strike where BS d1 equals the given value (delta-targeted strike)."""
    sq = iv * math.sqrt(t)
    return spot * math.exp(-(d1 * sq - (R + iv * iv / 2) * t))


def load_data():
    if CACHE.exists():
        raw = json.loads(CACHE.read_text())
    else:
        import sys
        sys.path.insert(0, str(HERE.parents[2]))
        from shared.auth import get_client
        c = get_client()
        raw = {}
        for sym in ("SPY", "$VIX", "$VIX3M"):
            r = c.get_price_history_every_day(symbol=sym)
            r.raise_for_status()
            raw[sym] = {
                datetime.fromtimestamp(k["datetime"] / 1000).date().isoformat(): k["close"]
                for k in r.json().get("candles", [])
            }
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(raw))
    return raw


class Position:
    __slots__ = ("k_short", "k_long", "expiry", "credit", "contracts", "width_dollars")

    def __init__(self, k_short, k_long, expiry, credit, contracts):
        self.k_short, self.k_long, self.expiry = k_short, k_long, expiry
        self.credit, self.contracts = credit, contracts
        self.width_dollars = (k_short - k_long) * 100 * contracts

    def value(self, spot, t, iv_s, iv_l):
        return bs_put(spot, self.k_short, t, iv_s) - bs_put(spot, self.k_long, t, iv_l)


def run_variant(days, sizing, skew_s, skew_l, *, d1_s=SHORT_DELTA_D1, d1_l=LONG_DELTA_D1,
                take=PROFIT_TAKE, exit_on_flip=False, risk_on=None):
    """sizing(vix) -> target total open width in dollars (0 = no new entries).

    Returns dict of results. days = [(date, spy, vix, ratio)]. Entries weekly
    (first trading day each ISO week); each entry tops open width up toward the
    target, laddered at no more than target/4 per entry.
    """
    open_pos: list[Position] = []
    realized = 0.0
    trades = wins = 0
    equity_by_day = []
    last_week = None

    for d, spy, vix, ratio in days:
        iv_s, iv_l = vix / 100 * skew_s, vix / 100 * skew_l

        # --- manage opens: profit take, trend-flip exit, expiry settle ---
        flip_out = exit_on_flip and risk_on is not None and not risk_on.get(d, True)
        keep = []
        for p in open_pos:
            t = max(( p.expiry - d).days, 0) / 365
            v = p.value(spy, t, iv_s, iv_l)
            if flip_out and d < p.expiry:
                pnl = (p.credit - v) * 100 * p.contracts - COST_PER_SPREAD * p.contracts
                realized += pnl
                trades += 1; wins += pnl > 0
            elif v <= p.credit * (1 - take) and d < p.expiry:
                realized += (p.credit - v) * 100 * p.contracts - COST_PER_SPREAD * p.contracts
                trades += 1; wins += 1
            elif d >= p.expiry:
                settle = max(p.k_short - spy, 0) - max(p.k_long - spy, 0)
                pnl = (p.credit - settle) * 100 * p.contracts - COST_PER_SPREAD * p.contracts
                realized += pnl
                trades += 1; wins += pnl > 0
            else:
                keep.append(p)
        open_pos = keep

        # --- weekly entry, regime-gated ---
        wk = d.isocalendar()[:2]
        if wk != last_week and ratio < BACKWARDATION:
            last_week = wk
            target = sizing(d, vix)
            open_width = sum(p.width_dollars for p in open_pos)
            room = target - open_width
            if room > 0:
                add = min(room, max(target / 4, 1))
                k_s = strike_for_d1(spy, DTE_TARGET / 365, iv_s, d1_s)
                k_l = strike_for_d1(spy, DTE_TARGET / 365, iv_l, d1_l)
                if k_s - k_l > 0.5:
                    per = (k_s - k_l) * 100
                    n = max(int(add // per), 1) if add >= per * 0.5 else 0
                    if n:
                        credit = bs_put(spy, k_s, DTE_TARGET / 365, iv_s) - bs_put(
                            spy, k_l, DTE_TARGET / 365, iv_l)
                        if credit > 0:
                            open_pos.append(Position(k_s, k_l,
                                                     d + timedelta(days=DTE_TARGET),
                                                     credit, n))

        unreal = sum(
            (p.credit - p.value(spy, max((p.expiry - d).days, 0) / 365, iv_s, iv_l))
            * 100 * p.contracts for p in open_pos)
        equity_by_day.append((d, realized + unreal))

    # --- stats ---
    eq = [e for _, e in equity_by_day]
    peak, max_dd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e)
        max_dd = max(max_dd, peak - e)
    monthly = {}
    for d, e in equity_by_day:
        monthly[(d.year, d.month)] = e
    keys = sorted(monthly)
    mrets = [monthly[keys[i]] - monthly[keys[i - 1]] for i in range(1, len(keys))]
    yearly = {}
    for (y, m) in keys:
        yearly[y] = monthly[(y, m)]
    ylist = sorted(yearly)
    yr_pnl = {ylist[0]: yearly[ylist[0]]}
    for i in range(1, len(ylist)):
        yr_pnl[ylist[i]] = yearly[ylist[i]] - yearly[ylist[i - 1]]

    years = (equity_by_day[-1][0] - equity_by_day[0][0]).days / 365.25
    return {
        "min_eq": min(eq),
        "total": eq[-1],
        "per_yr": eq[-1] / years,
        "max_dd": max_dd,
        "worst_month": min(mrets) if mrets else 0.0,
        "best_month": max(mrets) if mrets else 0.0,
        "trades": trades,
        "win_rate": wins / trades if trades else 0.0,
        "yearly": yr_pnl,
    }


def main():
    raw = load_data()
    spy, vix, v3 = raw["SPY"], raw["$VIX"], raw["$VIX3M"]
    days = []
    closes = []
    ma_by_date = {}
    for k in sorted(spy):
        closes.append(spy[k])
        if len(closes) >= 200:
            ma_by_date[k] = sum(closes[-200:]) / 200
        if k >= "2008-01-02" and k in vix and k in v3 and v3[k] > 0:
            days.append((date.fromisoformat(k), spy[k], vix[k], vix[k] / v3[k]))
    risk_on = {date.fromisoformat(k): spy[k] > ma for k, ma in ma_by_date.items()}
    print(f"Replaying {len(days)} trading days: {days[0][0]} -> {days[-1][0]}")
    spy_ret = (days[-1][1] / days[0][1] - 1) * CAPITAL
    years = (days[-1][0] - days[0][0]).days / 365.25
    print(f"Benchmark: SPY price-only on ${CAPITAL:,.0f} = ${spy_ret:,.0f} total "
          f"(~${spy_ret / years:,.0f}/yr; add ~2%/yr dividends on top)\n")

    def vol_target(v):
        # constant-risk width: full $80k at VIX<=16, shrinks with the square of vol
        return min(80_000.0, 80_000.0 * (16.0 / max(v, 1.0)) ** 2)

    variants = {
        "A_current_2slot": lambda d, v: 6_000.0,                   # ~2 x $3k spreads
        "B_flat_80k":      lambda d, v: 80_000.0,
        "C_scale_UP_hiVIX": lambda d, v: 80_000.0 if v >= 20 else 30_000.0,
        "D_trend_gated":   lambda d, v: 80_000.0 if risk_on.get(d) else 0.0,
        "E_vol_target":    lambda d, v: vol_target(v),
        "F_trend+voltgt":  lambda d, v: vol_target(v) if risk_on.get(d) else 0.0,
    }
    skews = [("thin skew  (1.00/1.10)", 1.00, 1.10),
             ("base skew  (1.05/1.20)", 1.05, 1.20),
             ("steep skew (1.10/1.35)", 1.10, 1.35)]

    for name, sizing in variants.items():
        print(f"=== {name} ===")
        for label, s1, s2 in skews:
            r = run_variant(days, sizing, s1, s2)
            print(f"  {label}: total ${r['total']:>9,.0f}  (${r['per_yr']:>7,.0f}/yr)"
                  f"  maxDD ${r['max_dd']:>8,.0f}  worst-mo ${r['worst_month']:>8,.0f}"
                  f"  minEq ${r['min_eq']:>8,.0f}  trades {r['trades']:>4}  win {r['win_rate']:.0%}")
            if label.startswith("base"):
                bad = {y: p for y, p in r["yearly"].items() if p < 0}
                print(f"    base-skew losing years: "
                      + (", ".join(f"{y}: ${p:,.0f}" for y, p in sorted(bad.items()))
                         or "none"))
        print()


if __name__ == "__main__":
    main()
