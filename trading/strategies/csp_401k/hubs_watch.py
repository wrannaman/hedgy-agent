#!/usr/bin/env python3
"""Optional price-zone watcher (legacy filename), configured entirely locally.

No config means no network request and no notification. See price-watch.example.json.
"""
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))
from shared.notifications import post_message


def main():
    config_path = Path(os.environ.get('HEDGY_PRICE_WATCH_CONFIG', REPO_ROOT / 'price-watch.local.json'))
    if not config_path.exists():
        return 0
    config = json.loads(config_path.read_text())
    symbol = config['symbol']
    zones = config['zones']
    if not isinstance(symbol, str) or not symbol or not isinstance(zones, list):
        raise ValueError('Price watcher requires a symbol and zones list')
    from shared.auth import get_client
    response = get_client().get_quote(symbol)
    response.raise_for_status()
    price = response.json()[symbol]['quote']['lastPrice']
    state = HERE / 'state/price_watch.json'
    try:
        saved = json.loads(state.read_text())
    except (FileNotFoundError, ValueError):
        saved = {}
    fired = set(saved.get('fired', [])) if saved.get('symbol') == symbol else set()
    if price >= float(config['recovery_price']):
        fired.clear()
    else:
        for zone in zones:
            if price <= float(zone['price']) and zone['name'] not in fired:
                if post_message(f"Price watch: {symbol} entered {zone['name']} at ${price:.2f}. Review only; no order placed."):
                    fired.add(zone['name'])
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({'symbol': symbol, 'fired': sorted(fired)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
