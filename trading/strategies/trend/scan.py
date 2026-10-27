"""
trend/scan.py — the trend/ballast sleeve (FUND.md §2A).

Faber's 10-month rule on the equity core: risk-on while price is above its long
trend, risk-off (rotate the de-grossed equity into T-bills/managed-futures/gold)
when it breaks below. The cheapest crash defense there is and the one genuinely
uncorrelated stream in the book. One signal, checked monthly. Recommend-only.
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


def weekly_closes(client, symbol):
    r = client.get_price_history_every_week(symbol=symbol)
    r.raise_for_status()
    return [c["close"] for c in r.json().get("candles", [])]


def run():
    client = get_client()
    closes = weekly_closes(client, rules.BENCHMARK)
    if len(closes) < rules.SMA_WEEKS:
        raise RuntimeError(f"{rules.BENCHMARK}: only {len(closes)} weeks, need {rules.SMA_WEEKS}")
    sma = sum(closes[-rules.SMA_WEEKS:]) / rules.SMA_WEEKS
    price = closes[-1]
    pct = (price - sma) / sma * 100
    regime = "risk_on" if price > sma else "risk_off"

    signal = {"timestamp": datetime.now().isoformat(), "benchmark": rules.BENCHMARK,
              "price": round(price, 2), "sma": round(sma, 2), "pct_above": round(pct, 1),
              "regime": regime, "ballast": rules.BALLAST}
    (STATE / "signal.json").write_text(json.dumps(signal, indent=2))

    print(f"=== TREND {datetime.now():%Y-%m-%d} ===")
    print(f"{rules.BENCHMARK} ${price:.2f} vs {rules.SMA_WEEKS}wk SMA ${sma:.2f} "
          f"({pct:+.1f}%) -> {regime.upper()}")
    if regime == "risk_off":
        print(f"  De-gross equity into ballast: {', '.join(rules.BALLAST)}")
    return signal


if __name__ == "__main__":
    run()
