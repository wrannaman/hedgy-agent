"""Underlying daily-close loader for the backtest — free data, cached to disk.

Pull daily OHLC once via Schwab get_price_history_every_day, cache the closes to
state/backtest/prices/SYMBOL.json. After the first pull every rerun is offline and
deterministic — the whole point of caching is that a sweep over rule grids never
re-hits the network and always replays the identical price path.

This is the ONLY module in backtest/ that touches Schwab. Everything downstream
(pricer, volmodel, synth_chain, engine) is pure and replays cached closes.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parents[1] / "state" / "backtest" / "prices"


def _cache_path(symbol: str) -> Path:
    return _CACHE_DIR / f"{symbol}.json"


def _load_cache(symbol: str) -> dict[str, float]:
    p = _cache_path(symbol)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_cache(symbol: str, closes: dict[str, float]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(symbol).write_text(json.dumps(closes, sort_keys=True))


def _fetch_closes(client, symbol: str) -> dict[str, float]:
    """Full available daily-close history from Schwab as {YYYY-MM-DD: close}."""
    r = client.get_price_history_every_day(symbol=symbol)
    r.raise_for_status()
    out: dict[str, float] = {}
    for c in r.json().get("candles", []):
        d = datetime.fromtimestamp(c["datetime"] / 1000).date()
        out[d.isoformat()] = c["close"]
    return out


def load_prices(symbol, start=None, end=None, client=None):
    """Return [(date, close), ...] ascending for symbol within [start, end].

    Reads the on-disk cache first; only calls Schwab (via client) when the cache is
    empty, then merges and persists. start/end are date objects or None (unbounded).
    A cached symbol replays with no network and no client required.
    """
    closes = _load_cache(symbol)
    if not closes:
        if client is None:
            raise RuntimeError(
                f"No cached closes for {symbol} and no client to fetch them. "
                f"Run once with a live client to populate state/backtest/prices/."
            )
        closes = _fetch_closes(client, symbol)
        _save_cache(symbol, closes)

    series = sorted((date.fromisoformat(k), v) for k, v in closes.items())
    if start is not None:
        series = [(d, c) for d, c in series if d >= start]
    if end is not None:
        series = [(d, c) for d, c in series if d <= end]
    return series
