"""
index_vrp/scan.py — the index variance-risk-premium sleeve scanner.

Sells DEFINED-RISK put spreads on broad-index ETFs (the best-evidenced short-premium
edge — FUND.md §2A). For each index it picks a ~SHORT_DELTA short put and a ~LONG_DELTA
long put, prices the spread, computes the variance risk premium (IV - realized vol),
and surfaces it only if it clears the gates. Defined risk = the spread width, so it fits
a small account where a cash-secured index put never would.

Output: ranked candidates to state/last_screen.json, in the same shape fund_engine and
risk.py consume (strategy="put_spread", collateral = max risk). Recommend-only.
"""
import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from shared.marketdata import realized_vol_30d
from schwab.client import Client
import rules

STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_DIR.mkdir(exist_ok=True)
STATE_PATH = STATE_DIR / "last_screen.json"


def _nearest_by_delta(puts, target):
    """Pick the put whose |delta| is closest to target."""
    return min(puts, key=lambda p: abs(abs(p["delta"]) - target))


def scan_symbol(client, symbol):
    """Best defined-risk put spread for one index ETF, or None."""
    today = date.today()
    resp = client.get_option_chain(
        symbol,
        contract_type=Client.Options.ContractType.PUT,
        from_date=today + timedelta(days=rules.DTE_MIN),
        to_date=today + timedelta(days=rules.DTE_MAX),
    )
    resp.raise_for_status()
    d = resp.json()
    if d.get("status") == "FAILED":
        return None
    spot = d.get("underlyingPrice")
    if not spot or spot <= 0:
        return None

    # Use the single expiration nearest the middle of the window.
    target_dte = (rules.DTE_MIN + rules.DTE_MAX) / 2
    by_exp = {}
    for expkey, strikes in d.get("putExpDateMap", {}).items():
        exp = expkey.split(":")[0]
        for sp_str, contracts in strikes.items():
            c = contracts[0]
            dte = c.get("daysToExpiration") or 0
            bid, ask, delta = c.get("bid") or 0, c.get("ask") or 0, c.get("delta")
            if bid <= 0 or ask <= 0 or delta is None or not (rules.DTE_MIN <= dte <= rules.DTE_MAX):
                continue
            by_exp.setdefault((exp, dte), []).append(
                {"strike": float(sp_str), "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                 "delta": delta, "iv": c.get("volatility") or 0})
    if not by_exp:
        return None
    (exp, dte), puts = min(by_exp.items(), key=lambda kv: abs(kv[0][1] - target_dte))
    if len(puts) < 2:
        return None

    short = _nearest_by_delta(puts, rules.SHORT_DELTA)
    longs = [p for p in puts if p["strike"] < short["strike"]]
    if not longs:
        return None
    long = _nearest_by_delta(longs, rules.LONG_DELTA)

    width = short["strike"] - long["strike"]
    if width <= 0:
        return None
    net_credit = short["mid"] - long["mid"]
    if net_credit <= 0:
        return None
    max_risk = (width - net_credit) * 100
    credit_pct_width = net_credit / width * 100

    # Liquidity + edge gates
    for leg in (short, long):
        sp_pct = (leg["ask"] - leg["bid"]) / leg["mid"] * 100 if leg["mid"] else 999
        if sp_pct > rules.MAX_SPREAD_PCT:
            return None
    if credit_pct_width < rules.MIN_CREDIT_PCT_OF_WIDTH:
        return None

    underlying_iv = _nearest_by_delta(puts, 0.50)["iv"] or short["iv"]
    rv = realized_vol_30d(client, symbol)
    vrp = round(underlying_iv - rv, 1) if rv is not None else None
    if vrp is not None and vrp <= rules.MIN_VRP:
        return None

    cushion = (spot - short["strike"]) / spot * 100
    return {
        "symbol": symbol,
        "strategy": "put_spread",
        "spot": round(spot, 2),
        "short_strike": short["strike"],
        "long_strike": long["strike"],
        "strike": short["strike"],          # the short leg (for display)
        "width": round(width, 2),
        "expiration": exp,
        "dte": dte,
        "net_credit": round(net_credit, 2),
        "premium_dollars": round(net_credit * 100),
        "collateral": round(max_risk),       # defined risk = buying-power reduction
        "credit_pct_width": round(credit_pct_width, 1),
        "cushion_pct": round(cushion, 1),
        "short_delta": round(abs(short["delta"]), 3),
        "underlying_iv": round(underlying_iv, 1),
        "realized_vol_30d": rv,
        "vrp": vrp,
    }


def run():
    client = get_client()
    candidates = []
    for sym in rules.UNIVERSE:
        try:
            c = scan_symbol(client, sym)
            if c:
                candidates.append(c)
        except Exception as e:
            print(f"  {sym}: error {e}")
    # Rank by edge: credit-per-width weighted by VRP
    candidates.sort(key=lambda c: c["credit_pct_width"] * max(c.get("vrp") or 0, 0), reverse=True)

    out = {"timestamp": datetime.now().isoformat(), "universe": rules.UNIVERSE,
           "candidates": candidates}
    STATE_PATH.write_text(json.dumps(out, indent=2))

    print(f"=== INDEX-VRP SCREEN {datetime.now():%Y-%m-%d %H:%M} ===")
    print(f"{len(candidates)}/{len(rules.UNIVERSE)} indices cleared the gates "
          f"(~{rules.SHORT_DELTA:.0%}/{rules.LONG_DELTA:.0%}δ spread, credit >= "
          f"{rules.MIN_CREDIT_PCT_OF_WIDTH:.0f}% of width, VRP > {rules.MIN_VRP:.0f})\n")
    print(f"{'sym':4} {'spot':>8} {'short':>7} {'long':>7} {'exp':>11} {'dte':>3} "
          f"{'cush':>5} {'cr/w':>5} {'$cr':>5} {'risk':>6} {'IV':>4} {'RV':>4} {'VRP':>4}")
    for c in candidates:
        print(f"{c['symbol']:4} {c['spot']:>8} {c['short_strike']:>7g} {c['long_strike']:>7g} "
              f"{c['expiration']:>11} {c['dte']:>3} {c['cushion_pct']:>4.0f}% "
              f"{c['credit_pct_width']:>4.0f}% {c['premium_dollars']:>5} {c['collateral']:>6} "
              f"{c['underlying_iv']:>4.0f} {str(c['realized_vol_30d']):>4} {str(c['vrp']):>4}")
    return out


if __name__ == "__main__":
    run()
