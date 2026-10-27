"""
Does the *driver* of a red day matter for csp_401k entries?

Damodaran (Musings on Markets, 2026-09-10) showed the S&P 500 averaged about
-0.5% on 2026 days when the 10-year yield rose >3bp and about +0.5% when it fell
>3bp. The worry for us: a rate-driven selloff is a discount-rate repricing (slow,
persistent, hits long-duration names), not the fear overreaction that RULES.md §1
red-day selling assumes. If true, candidates surfaced on rate-shock days should
break their strikes more often than candidates surfaced on idiosyncratic red days.

This script buckets every settled candidate in `state/skipped_log.jsonl` by the
10-year's daily change on its log day (FRED DGS10) and compares outcomes:
expired-OTM rate, strike-touched rate, max drawdown, hypothetical P&L. It also
replicates Damodaran's SPY-by-yield-change table on our own data.

Result on 2026-09-15 (621 settled candidates, log days 2026-05-27..2026-08-11):
no driver effect. Red-day + vrp>=15 candidates were 100% expired-OTM and 0%
strike-touched in all three yield buckets (n=15/17/6). All red-day candidates:
rate-shock red 92% OTM vs idiosyncratic red 99%, touched 18% vs 12% — a small
gap driven by negative-VRP names the floor already excludes. The 25% expected-
move cushion is far deeper than a month of rate-driven drift reaches. Window
caveat: the biggest 10y up-day in 2026 was +14bp; no tantrum day is in-sample.

Data: FRED DGS10 CSV and Yahoo daily closes, cached under $TMPDIR. Both hosts
are outside the default sandbox allowlist. Yahoo closes are split-adjusted and
skipped_log spots are not (KLAC 10:1 in July 2026), so candidates whose logged
spot is >3x the later close are dropped as split artifacts.

Usage:
  python3 experiments/rate_bucket_backcheck.py
"""
import csv
import json
import os
import statistics as st
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
STATE = HERE / "state"
CACHE = Path(os.environ.get("TMPDIR", "/tmp")) / "rate_bucket_cache"
UA = {"User-Agent": "Mozilla/5.0"}
BP_THRESHOLD = 3.0  # Damodaran's cut: >3bp is a "large" daily move
ACTIONABLE_VRP = 15.0  # RULES.md §1 actionable floor


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()


def load_dgs10():
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "dgs10.csv"
    if not p.exists():
        p.write_bytes(fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2025-12-01"))
    series = {}
    for r in csv.DictReader(p.open()):
        if r["DGS10"] not in (".", ""):
            series[r["observation_date"]] = float(r["DGS10"])
    days = sorted(series)
    change_bp = {days[i]: (series[days[i]] - series[days[i - 1]]) * 100 for i in range(1, len(days))}
    return series, days, change_bp


def load_closes(symbols):
    (CACHE / "px").mkdir(parents=True, exist_ok=True)
    out = {}
    for s in symbols:
        p = CACHE / "px" / f"{s}.json"
        if not p.exists():
            d = json.loads(fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1y&interval=1d"))
            r = d["chart"]["result"][0]
            closes = r["indicators"]["quote"][0]["close"]
            ser = {
                datetime.fromtimestamp(t, timezone.utc).date().isoformat(): c
                for t, c in zip(r["timestamp"], closes)
                if c is not None
            }
            p.write_text(json.dumps(ser))
            time.sleep(0.25)
        out[s] = json.loads(p.read_text())
    return out


def day_return(px, sym, d):
    s = px[sym]
    ks = sorted(k for k in s if k <= d)
    if len(ks) < 2 or ks[-1] != d:
        return None
    return (s[ks[-1]] / s[ks[-2]] - 1) * 100


def close_on_or_after(px, sym, d):
    s = px[sym]
    ks = sorted(k for k in s if k >= d)
    return s[ks[0]] if ks else None


def min_close(px, sym, a, b):
    v = [c for k, c in px[sym].items() if a <= k <= b]
    return min(v) if v else None


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else float("nan")


def show(label, sub):
    if not sub:
        print(f"  {label:36} n=0")
        return
    n = len(sub)
    otm = sum(o["otm"] for o in sub)
    touched = sum(o["touched"] for o in sub)
    print(
        f"  {label:36} n={n:3} expOTM={100*otm/n:3.0f}% touched={100*touched/n:3.0f}% "
        f"medVRP={med(o['vrp'] for o in sub):+5.1f} medCush={med(o['cush'] for o in sub):4.1f} "
        f"medMaxDD={med(o['maxdd'] for o in sub):+5.1f}% sumPnL=${sum(o['pnl'] for o in sub):+,.0f}"
    )


def buckets(sub, key="bp"):
    show(f"10y up >{BP_THRESHOLD:.0f}bp", [o for o in sub if o[key] > BP_THRESHOLD])
    show(f"10y flat ±{BP_THRESHOLD:.0f}bp", [o for o in sub if -BP_THRESHOLD <= o[key] <= BP_THRESHOLD])
    show(f"10y down >{BP_THRESHOLD:.0f}bp", [o for o in sub if o[key] < -BP_THRESHOLD])


def main():
    series, days, chg = load_dgs10()
    rows = [json.loads(l) for l in (STATE / "skipped_log.jsonl").open() if l.strip()]
    trades = json.loads((STATE / "trade_log.json").read_text())["trades"]
    symbols = sorted({r["symbol"] for r in rows} | {t["symbol"] for t in trades} | {"SPY"})
    px = load_closes(symbols)

    print("SPY daily return by 10y change (2026 YTD):")
    b = {"up": [], "flat": [], "down": []}
    for d, c in chg.items():
        r = day_return(px, "SPY", d)
        if d < "2026-01-01" or r is None:
            continue
        b["up" if c > BP_THRESHOLD else "down" if c < -BP_THRESHOLD else "flat"].append(r)
    for k, v in b.items():
        print(f"  {k:5} n={len(v):3} mean={st.mean(v):+.2f}%")
    print(f"  10y 2026-01-02 {series.get('2026-01-02')} -> {days[-1]} {series[days[-1]]}")

    first = {}
    for r in rows:
        k = (r["symbol"], r["strike"], r["expiration"][:10])
        first.setdefault(k, r)
    traded = {(t["symbol"], float(t["sell_strike"]), t["expiration"][:10]) for t in trades}
    today = date.today().isoformat()
    out, splits = [], []
    for (sym, strike, exp), r in first.items():
        d = r["logged_at"][:10]
        if exp >= today or d not in chg:
            continue
        cl = close_on_or_after(px, sym, exp)
        if cl is None:
            continue
        if r["spot_at_log"] / cl > 3:
            splits.append((sym, d))
            continue
        mn = min_close(px, sym, d, exp)
        prev = [x for x in days if x < d][-1]
        pnl = r["premium_dollars"] if cl >= strike else r["premium_dollars"] - (strike - cl) * 100
        out.append(
            dict(
                sym=sym, d=d, exp=exp, bp=chg[d], bp_prev=chg.get(prev, 0.0),
                stock_ret=day_return(px, sym, d), spy_ret=day_return(px, "SPY", d),
                vrp=r["vrp"], cush=r["cushion_pct"], otm=cl >= strike, touched=mn < strike,
                pnl=pnl, traded=(sym, float(strike), exp) in traded,
                maxdd=(mn / r["spot_at_log"] - 1) * 100,
            )
        )
    print(f"\nSettled unique candidates: {len(out)} (traded {sum(o['traded'] for o in out)}); "
          f"log days {min(o['d'] for o in out)}..{max(o['d'] for o in out)}; dropped as split artifacts: {splits}")

    red = [o for o in out if o["stock_ret"] is not None and o["stock_ret"] < 0]
    act = [o for o in out if o["vrp"] is not None and o["vrp"] >= ACTIONABLE_VRP]
    red_act = [o for o in act if o["stock_ret"] is not None and o["stock_ret"] < 0]
    print("\nALL settled, by 10y change on log day:"); buckets(out)
    print("ALL settled, by 10y change on prior day:"); buckets(out, "bp_prev")
    print(f"\nRed-day candidates (n={len(red)}):"); buckets(red)
    print(f"\nvrp>={ACTIONABLE_VRP:.0f} candidates (n={len(act)}):"); buckets(act)
    print(f"\nRed-day AND vrp>={ACTIONABLE_VRP:.0f} (n={len(red_act)}):"); buckets(red_act)
    print("\nRed days split by driver:")
    spy_down = lambda o: o["spy_ret"] is not None and o["spy_ret"] < 0
    show("rate-shock red (10y up, SPY down)", [o for o in red if o["bp"] > BP_THRESHOLD and spy_down(o)])
    show("market red, not rate", [o for o in red if o["bp"] <= BP_THRESHOLD and spy_down(o)])
    show("idiosyncratic red (SPY up)", [o for o in red if o["spy_ret"] is not None and o["spy_ret"] >= 0])

    print("\nLive trades: 10y change on open day")
    for t in trades:
        d = t["opened"][:10]
        print(f"  #{t['id']:2} {d} {t['symbol']:5} 10y {chg.get(d, float('nan')):+5.1f}bp "
              f"stock {day_return(px, t['symbol'], d) or 0:+5.1f}% SPY {day_return(px, 'SPY', d) or 0:+5.1f}% pnl {t.get('pnl')}")


if __name__ == "__main__":
    sys.exit(main())
