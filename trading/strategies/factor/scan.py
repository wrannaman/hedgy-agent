"""
factor/scan.py — the long-only factor-tilt sleeve (FUND.md §2A).

Ranks the evidence-backed factor ETFs (quality, low-vol, momentum, value) by 12-1
month momentum and surfaces the leaders to tilt toward vs the SPY benchmark. Slow
signal, low turnover. Recommend-only.
"""
import sys, json
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from shared.auth import get_client
import rules

STATE = Path(__file__).resolve().parent / "state"
STATE.mkdir(exist_ok=True)


def momentum_12_1(client, symbol):
    r = client.get_price_history_every_week(symbol=symbol)
    r.raise_for_status()
    closes = [c["close"] for c in r.json().get("candles", [])]
    if len(closes) < rules.LOOKBACK_WEEKS + 1:
        return None
    return round((closes[-rules.SKIP_WEEKS] / closes[-rules.LOOKBACK_WEEKS] - 1) * 100, 1)


def run():
    client = get_client()
    ranked = sorted(
        [{"symbol": s, "mom_12_1": m}
         for s in rules.ETFS if (m := momentum_12_1(client, s)) is not None],
        key=lambda x: x["mom_12_1"], reverse=True)

    bench = next((r["mom_12_1"] for r in ranked if r["symbol"] == "SPY"), None)
    leaders = [r for r in ranked if r["symbol"] != "SPY"][:rules.TOP_N]

    out = {"timestamp": datetime.now().isoformat(), "ranked": ranked,
           "benchmark_mom": bench, "leaders": [l["symbol"] for l in leaders]}
    (STATE / "signal.json").write_text(json.dumps(out, indent=2))

    print(f"=== FACTOR {datetime.now():%Y-%m-%d} === (12-1 momentum)")
    for r in ranked:
        tag = " <- tilt" if r in leaders else (" (benchmark)" if r["symbol"] == "SPY" else "")
        print(f"  {r['symbol']:5} {r['mom_12_1']:+6.1f}%{tag}")
    return out


if __name__ == "__main__":
    run()
