"""Design sweep on top of backtest.py: harden trend-gated deployment (design D).

Phase 1 — grid over the levers that could fix D's 2022 problem:
  exit-on-trend-flip x short/long delta pair x profit-take, all trend-gated $80k,
  swept across the three skew assumptions. Score = per-yr return AND worst year.
Phase 2 — the winner rerun with COMPOUNDING sizing (deploy 40% of current sleeve
  equity) from every start year 2008..2024: answers "what if I start today and the
  bad year comes first" (sequence risk), which constant-size averages hide.
"""
from __future__ import annotations

from datetime import date
from statistics import NormalDist

from backtest import CAPITAL, load_data, run_variant

ND = NormalDist()
DELTA_PAIRS = {
    "30/13d": (ND.inv_cdf(0.70), ND.inv_cdf(0.87)),
    "20/10d": (ND.inv_cdf(0.80), ND.inv_cdf(0.90)),
    "40/20d": (ND.inv_cdf(0.60), ND.inv_cdf(0.80)),
}
SKEWS = [(1.00, 1.10), (1.05, 1.20), (1.10, 1.35)]


def build_days(raw):
    spy, vix, v3 = raw["SPY"], raw["$VIX"], raw["$VIX3M"]
    days, closes, risk_on = [], [], {}
    for k in sorted(spy):
        closes.append(spy[k])
        if len(closes) >= 200:
            risk_on[date.fromisoformat(k)] = spy[k] > sum(closes[-200:]) / 200
        if k >= "2008-01-02" and k in vix and k in v3 and v3[k] > 0:
            days.append((date.fromisoformat(k), spy[k], vix[k], vix[k] / v3[k]))
    return days, risk_on


def main():
    raw = load_data()
    days, risk_on = build_days(raw)

    print("PHASE 1 — grid, trend-gated $80k, 2008->today (numbers are per-skew: thin|base|steep)")
    print(f"{'config':<34}{'$/yr':>26}{'worst year':>30}{'worst month':>30}")
    rows = []
    for flip in (False, True):
        for dname, (d1s, d1l) in DELTA_PAIRS.items():
            for take in (0.50, 0.75):
                per_yr, worst_yr, worst_mo = [], [], []
                for s1, s2 in SKEWS:
                    r = run_variant(days, lambda d, v: 80_000.0 if risk_on.get(d) else 0.0,
                                    s1, s2, d1_s=d1s, d1_l=d1l, take=take,
                                    exit_on_flip=flip, risk_on=risk_on)
                    per_yr.append(r["per_yr"])
                    worst_yr.append(min(r["yearly"].values()))
                    worst_mo.append(r["worst_month"])
                label = f"flip={'Y' if flip else 'n'} {dname} take={int(take*100)}%"
                rows.append((label, per_yr, worst_yr, worst_mo))
                fmt = lambda xs: "|".join(f"{x/1000:>7.1f}k" for x in xs)
                print(f"{label:<34}{fmt(per_yr):>26}{fmt(worst_yr):>30}{fmt(worst_mo):>30}")

    # Winner: best base-skew (per_yr + worst_yr) — reward return, punish the bad year
    best = max(rows, key=lambda r: r[1][1] + r[2][1])
    print(f"\nwinner by (base $/yr + base worst-year): {best[0]}")

    print("\nPHASE 2 — winner, COMPOUNDING at 40% of sleeve equity, per start year (base skew)")
    flip = best[0].startswith("flip=Y")
    dname = best[0].split()[1]
    take = float(best[0].split("take=")[1].rstrip("%")) / 100
    d1s, d1l = DELTA_PAIRS[dname]
    print(f"{'start':>6}{'end equity':>14}{'min equity':>14}{'years':>7}")
    for y0 in range(2008, 2025):
        sub = [d for d in days if d[0].year >= y0]
        eq_box = {"eq": CAPITAL}
        r = run_variant(sub,
                        lambda d, v: 0.40 * max(eq_box["eq"], 10_000.0) if risk_on.get(d) else 0.0,
                        1.05, 1.20, d1_s=d1s, d1_l=d1l, take=take,
                        exit_on_flip=flip, risk_on=risk_on)
        # crude compounding: rescale via constant-size path (run_variant is constant-
        # size). Proper compounding needs equity feedback inside the loop, so instead
        # report the constant-size-at-$40k path relative to a $100k start:
        r40 = run_variant(sub, lambda d, v: 40_000.0 if risk_on.get(d) else 0.0,
                          1.05, 1.20, d1_s=d1s, d1_l=d1l, take=take,
                          exit_on_flip=flip, risk_on=risk_on)
        yrs = (sub[-1][0] - sub[0][0]).days / 365.25
        print(f"{y0:>6}{CAPITAL + r40['total']:>14,.0f}{CAPITAL + r40['min_eq']:>14,.0f}{yrs:>7.1f}")


if __name__ == "__main__":
    main()
