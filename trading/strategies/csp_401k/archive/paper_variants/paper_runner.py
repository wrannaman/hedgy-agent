"""
Daily paper-trading runner — the driver that turns variants into running
paper positions.

For each variant auto-discovered in variants/:
  1. entry_signals(snapshot) -> proposed entries (dedupe vs already-open positions)
  2. compose_order(signal, snapshot, client) -> exact contract
  3. Opens a paper position tagged with variant name via paper_options.open_paper_put()

For each existing open paper position:
  1. Fetches current option + stock data
  2. Passes to variant.manage_position(position, snapshot) for decision
  3. If action="close" -> closes at current ask; "alert"/"hold:info" -> prints

Usage:
    python3 experiments/paper_runner.py
    python3 experiments/paper_runner.py --dry-run
"""
import argparse
import importlib
import json
import os
import pkgutil
import sys
from pathlib import Path

_STRATEGY_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_STRATEGY_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from shared.auth import get_client
from paper_options import (
    open_paper_put, close_paper_put, load_paper, _option_snapshot,
)
import variants

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(ROOT, "state", "market_snapshots")


def discover_variants():
    """Load every module in variants/ that doesn't start with '_'."""
    loaded = []
    for _, mod_name, _ in pkgutil.iter_modules(variants.__path__):
        if mod_name.startswith("_"):
            continue
        loaded.append(importlib.import_module(f"variants.{mod_name}"))
    return loaded


def load_latest_snapshot():
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    files = sorted(f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json"))
    if not files:
        return None
    with open(os.path.join(SNAPSHOT_DIR, files[-1])) as f:
        return json.load(f)


def open_positions(variant_name=None):
    paper = load_paper()
    positions = [p for p in paper["positions"] if p["status"] == "open"]
    if variant_name is not None:
        positions = [p for p in positions if p.get("rule_set") == variant_name]
    return positions


def run_entries(variant, snapshot, client, dry_run):
    signals = variant.entry_signals(snapshot)
    if not signals:
        print(f"  no new signals")
        return 0

    existing = {p["symbol"] for p in open_positions(variant.name)}
    opened = 0
    for signal in signals:
        if signal.symbol in existing:
            print(f"  SKIP {signal.symbol} — already open")
            continue
        if dry_run:
            print(f"  [DRY] would open {signal.symbol}: {signal.reason}")
            opened += 1
            continue
        order = variant.compose_order(signal, snapshot, client)
        if order is None:
            print(f"  SKIP {signal.symbol} — no suitable contract")
            continue
        filled = open_paper_put(
            symbol=order.symbol,
            strike=order.sell_strike,
            expiration=order.expiration,
            limit_price=order.limit_price,
            contracts=order.contracts,
            rule_set=variant.name,
            notes=f"auto: {signal.reason}",
            client=client,
        )
        if filled is None:
            # Broker refused the fill (illiquid / untradeable) — no position, like real life.
            continue
        opened += 1
    return opened


def run_management(snapshot, client, dry_run):
    variants_by_name = {v.name: v for v in discover_variants()}
    positions = open_positions()

    if not positions:
        print("  (no open paper positions)")
        return 0

    actions = 0
    for pos in positions:
        variant = variants_by_name.get(pos.get("rule_set"))
        if variant is None:
            print(f"  #{pos['id']} {pos['symbol']}: unknown variant '{pos.get('rule_set')}' — skip")
            continue

        live = _option_snapshot(client, pos["symbol"], pos["sell_strike"], pos["expiration"])
        if live is None:
            print(f"  #{pos['id']} {pos['symbol']}: no quote — skip")
            continue

        pos_for_mgmt = dict(pos)
        pos_for_mgmt.update({
            "current_mid": live["option_mid"],
            "current_ask": live["option_ask"],
            "current_stock": live["stock_price"],
            "current_dte": live["dte"],
        })

        action = variant.manage_position(pos_for_mgmt, snapshot)
        tag = f"#{pos['id']} {pos['symbol']} ${pos['sell_strike']}P ({variant.name})"

        if action.action == "close":
            if dry_run:
                print(f"  [DRY] {tag}: CLOSE — {action.reason}")
            else:
                close_paper_put(pos["id"], live["option_ask"], action.reason)
            actions += 1
        elif action.action == "alert":
            print(f"  ALERT {tag}: {action.reason}")
        elif action.action == "hold" and action.urgency == "info":
            print(f"  INFO  {tag}: {action.reason}")
    return actions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot = load_latest_snapshot()
    if snapshot is None:
        print("No market snapshots. Run experiments/snapshot.py first.")
        return 1

    vix = snapshot.get("vix")
    vix_str = f"{vix:.2f}" if vix else "None"
    spy_c = snapshot.get("spy_change") or 0
    qqq_c = snapshot.get("qqq_change") or 0
    print(f"=== PAPER RUNNER {snapshot['date']} ===")
    print(f"SPY {spy_c:+.2f}% | QQQ {qqq_c:+.2f}% | VIX {vix_str}")

    client = get_client()
    all_variants = discover_variants()
    print(f"Variants: {', '.join(v.name for v in all_variants)}\n")

    print("--- Entries ---")
    total_opened = 0
    for variant in all_variants:
        print(f"[{variant.name}]")
        total_opened += run_entries(variant, snapshot, client, args.dry_run)

    print("\n--- Management ---")
    total_actions = run_management(snapshot, client, args.dry_run)

    print(f"\nSummary: {total_opened} new entries, {total_actions} management actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
