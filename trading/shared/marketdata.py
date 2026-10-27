"""Shared market-data helpers (plumbing — generic, not strategy-specific).

Lives in shared/ so multiple sleeves use ONE implementation (DRY) without importing
each other's code. Anything strategy-specific stays in the sleeve, not here.
"""
import math
import statistics


def vix_term_ratio(client, vix_symbol="$VIX", vix3m_symbol="$VIX3M"):
    """VIX/VIX3M — the vol term-structure regime in one number.

    < 1 = contango (normal, favorable for selling premium); >= 1 = backwardation
    (near-term fear — stand down on new short premium). Returns None on any
    failure: None must mean "regime unknown, no gate", never a false stand-down.
    """
    try:
        r = client.get_quotes([vix_symbol, vix3m_symbol])
        r.raise_for_status()
        q = r.json()
        vix = q[vix_symbol]["quote"]["lastPrice"]
        vix3m = q[vix3m_symbol]["quote"]["lastPrice"]
        if not vix or not vix3m or vix <= 0 or vix3m <= 0:
            return None
        return round(vix / vix3m, 3)
    except Exception:
        return None


def realized_vol_30d(client, symbol):
    """Annualized 30-trading-day realized vol from daily closes, as a percentage.

    The comparison baseline for an option's implied vol: if IV >> RV the option is
    overpriced vs what the underlying has actually been doing, so selling premium has
    positive edge (the variance risk premium). IV ~ RV or IV < RV = no edge.
    Returns None if there isn't enough history.
    """
    try:
        r = client.get_price_history_every_day(symbol=symbol)
        r.raise_for_status()
        candles = r.json().get("candles", [])
        if len(candles) < 31:
            return None
        closes = [c["close"] for c in candles[-31:]]
        log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        daily_stdev = statistics.stdev(log_returns)
        return round(daily_stdev * math.sqrt(252) * 100, 1)
    except Exception:
        return None
