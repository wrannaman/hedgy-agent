#!/usr/bin/env python3
"""Recommendation-only cross-account portfolio sweep.

Reads Schwab position CSV exports, normalizes holdings, optionally enriches live
quotes, and writes structured context for the morning trading agent. This module
never places orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))
from shared.positions import (  # noqa: E402  position-CSV loading (single source)
    Holding, AccountSnapshot, parse_number, parse_metadata, file_stamp,
    display_path, latest_position_files, parse_position_file, POSITIONS_DIR, STALE_DAYS,
)

STATE_DIR = HERE / "state"
LATEST_JSON = STATE_DIR / "latest.json"
LATEST_SUMMARY = STATE_DIR / "latest_summary.txt"

IDLE_CASH_DOLLARS = 10_000
IDLE_CASH_PCT = 5.0
BIG_MOVE_PCT = 3.0
LARGE_LOSS_PCT = -35.0
LARGE_LOSS_DOLLARS = -5_000
LARGE_LOSS_MIN_MARKET_VALUE = 3_000
LARGE_WIN_PCT = 150.0
LARGE_WIN_ACCOUNT_PCT = 5.0
CONCENTRATION_PCT = 15.0
OVERLAP_DOLLARS = 10_000
SUMMARY_EXCLUDED_KINDS = {"bucket_concentration", "large_winner"}
FLAG_KIND_RANK = {
    "large_loser": 0,
    "big_move": 1,
    "portfolio_concentration": 2,
    "idle_cash": 3,
    "stale_csv": 4,
    "large_winner": 5,
    "cross_account_overlap": 6,
    "bucket_concentration": 7,
}


def dollars(value: float | None) -> str:
    if value is None:
        return "unknown dollars"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def holding_value(h: Holding) -> float:
    """Best-price market value: live quote re-prices the CSV snapshot when present."""
    if h.live_price is not None and h.quantity is not None:
        return h.live_price * h.quantity
    return h.market_value


def build_bucket_exposures(accounts: list[AccountSnapshot]) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """Group holdings by locally configured portfolio buckets across accounts."""
    from strategies.portfolio_watch import rules  # local import avoids load-order coupling
    totals: dict[str, float] = {}
    by_symbol: dict[tuple[str, str], float] = {}
    for account in accounts:
        bucket = rules.ACCOUNT_BUCKET.get(account.account_suffix, "taxable")
        for h in account.holdings:
            mv = holding_value(h)
            totals[bucket] = totals.get(bucket, 0.0) + mv  # cash counts toward the pool
            if not h.is_cash:
                by_symbol[(bucket, h.symbol)] = by_symbol.get((bucket, h.symbol), 0.0) + mv
    return totals, by_symbol


def quote_symbols(accounts: list[AccountSnapshot], no_quotes: bool) -> dict[str, dict[str, float]]:
    if no_quotes:
        return {}
    symbols = sorted({h.symbol for a in accounts for h in a.holdings if not h.is_cash})
    if not symbols:
        return {}

    sys.path.insert(0, str(REPO_ROOT))
    from shared.auth import get_client

    client = get_client()
    quotes: dict[str, dict[str, float]] = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        resp = client.get_quotes(chunk)
        resp.raise_for_status()
        for symbol, payload in resp.json().items():
            quote = payload.get("quote", {})
            price = quote.get("lastPrice")
            change = quote.get("netPercentChange")
            if price is not None:
                quotes[symbol] = {
                    "price": float(price),
                    "change_pct": float(change or 0.0),
                }
    return quotes


def enrich_holdings(accounts: list[AccountSnapshot], quotes: dict[str, dict[str, float]]) -> None:
    for account in accounts:
        for holding in account.holdings:
            quote = quotes.get(holding.symbol)
            if quote:
                holding.live_price = quote.get("price")
                holding.live_change_pct = quote.get("change_pct")


def build_exposures(accounts: list[AccountSnapshot]) -> dict[str, dict[str, Any]]:
    total = sum(holding_value(h) for account in accounts for h in account.holdings) or 1.0
    exposures: dict[str, dict[str, Any]] = {}
    for account in accounts:
        for holding in account.holdings:
            if holding.is_cash:
                continue
            mv = holding_value(holding)
            item = exposures.setdefault(holding.symbol, {
                "symbol": holding.symbol,
                "description": holding.description,
                "market_value": 0.0,
                "portfolio_pct": 0.0,
                "accounts": [],
            })
            item["market_value"] += mv
            item["accounts"].append({
                "account": account.account,
                "suffix": account.account_suffix,
                "market_value": round(mv, 2),
                "account_pct": holding.account_pct,
            })
    for item in exposures.values():
        item["market_value"] = round(item["market_value"], 2)
        item["portfolio_pct"] = round(item["market_value"] / total * 100, 2)
    return dict(sorted(exposures.items(), key=lambda kv: kv[1]["market_value"], reverse=True))


def add_flag(flags: list[dict[str, Any]], severity: str, kind: str, message: str, **data: Any) -> None:
    flags.append({"severity": severity, "kind": kind, "message": message, **data})


def build_flags(accounts: list[AccountSnapshot], exposures: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    for account in accounts:
        if account.stale:
            add_flag(
                flags, "warning", "stale_csv",
                f"{account.account} CSV is {account.age_days} days old; caveat recommendations",
                account=account.account, suffix=account.account_suffix, age_days=account.age_days,
                file_date=account.file_date,
            )
        cash_pct = account.cash_value / account.total_market_value * 100 if account.total_market_value else 0.0
        if account.cash_value >= IDLE_CASH_DOLLARS or cash_pct >= IDLE_CASH_PCT:
            add_flag(
                flags, "info", "idle_cash",
                f"{account.account} has ${account.cash_value:,.0f} cash or money market ({cash_pct:.1f}% of account)",
                account=account.account, suffix=account.account_suffix,
                market_value=round(account.cash_value, 2), account_pct=round(cash_pct, 2),
            )

        for holding in account.holdings:
            if holding.is_cash:
                continue
            move = holding.live_change_pct if holding.live_change_pct is not None else holding.day_change_pct
            if holding.asset_type != "Option" and move is not None and abs(move) >= BIG_MOVE_PCT:
                add_flag(
                    flags, "attention", "big_move",
                    f"{holding.symbol} moved {move:+.1f}% today in {account.account}",
                    account=account.account, suffix=account.account_suffix,
                    symbol=holding.symbol, move_pct=round(move, 2), priority=abs(move),
                )
            if (
                holding.gain_pct is not None
                and holding.gain_pct <= LARGE_LOSS_PCT
                and holding.market_value >= LARGE_LOSS_MIN_MARKET_VALUE
            ) or (
                holding.gain_dollars is not None and holding.gain_dollars <= LARGE_LOSS_DOLLARS
            ):
                pct = f"{abs(holding.gain_pct):.1f}%" if holding.gain_pct is not None else "unknown %"
                add_flag(
                    flags, "attention", "large_loser",
                    f"{holding.symbol} is down {pct} ({dollars(holding.gain_dollars)}) in {account.account}",
                    account=account.account, suffix=account.account_suffix, symbol=holding.symbol,
                    gain_pct=holding.gain_pct, gain_dollars=holding.gain_dollars,
                    priority=abs(holding.gain_dollars or holding.market_value),
                )
            if (
                holding.gain_pct is not None
                and holding.gain_pct >= LARGE_WIN_PCT
                and (holding.account_pct or 0.0) >= LARGE_WIN_ACCOUNT_PCT
            ):
                add_flag(
                    flags, "info", "large_winner",
                    f"{holding.symbol} is up {holding.gain_pct:.0f}% and is {holding.account_pct:.1f}% of {account.account}",
                    account=account.account, suffix=account.account_suffix, symbol=holding.symbol,
                    gain_pct=holding.gain_pct, account_pct=holding.account_pct,
                )
    # Concentration is measured per BUCKET (taxable book / 401k / Roth), never per
    # single account — the two taxable accounts are one bucket. One flag per (bucket,
    # symbol) above the threshold, framed in dollars + bucket %, not "% of account X".
    from strategies.portfolio_watch import rules
    for symbol, exposure in exposures.items():
        portfolio_pct = float(exposure.get("portfolio_pct") or 0.0)
        if portfolio_pct >= rules.CONCENTRATION_PORTFOLIO_PCT:
            accounts_count = len(exposure["accounts"])
            where = f"across {accounts_count} accounts" if accounts_count != 1 else "in 1 account"
            add_flag(
                flags, "attention", "portfolio_concentration",
                f"{symbol} is {portfolio_pct:.1f}% of the whole book (${exposure['market_value']:,.0f} {where})",
                symbol=symbol, portfolio_pct=round(portfolio_pct, 2),
                market_value=round(exposure["market_value"], 2),
                accounts=exposure["accounts"], priority=portfolio_pct,
            )

    bucket_totals, bucket_by_symbol = build_bucket_exposures(accounts)
    for (bucket, symbol), mv in bucket_by_symbol.items():
        total = bucket_totals.get(bucket) or 0.0
        bucket_pct = mv / total * 100 if total else 0.0
        if bucket_pct >= CONCENTRATION_PCT:
            label = rules.BUCKET_LABEL.get(bucket, bucket)
            add_flag(
                flags, "info", "bucket_concentration",
                f"{symbol} is {bucket_pct:.1f}% of the {label} (${mv:,.0f})",
                bucket=bucket, symbol=symbol, bucket_pct=round(bucket_pct, 2),
                market_value=round(mv, 2), priority=bucket_pct,
            )

    for symbol, exposure in exposures.items():
        if len(exposure["accounts"]) > 1 and exposure["market_value"] >= OVERLAP_DOLLARS:
            add_flag(
                flags, "info", "cross_account_overlap",
                f"{symbol} is held across {len(exposure['accounts'])} accounts (${exposure['market_value']:,.0f} total)",
                symbol=symbol, market_value=exposure["market_value"],
                portfolio_pct=exposure["portfolio_pct"], accounts=exposure["accounts"],
            )

    severity_rank = {"attention": 0, "warning": 1, "info": 2}
    return sorted(flags, key=lambda f: (
        severity_rank.get(f["severity"], 9),
        FLAG_KIND_RANK.get(f["kind"], 99),
        -(f.get("priority") or 0),
        f["message"],
    ))


def stale_caveat(flags: list[dict[str, Any]]) -> str:
    """One collapsed staleness warning, or "" when every export is current.

    Deliberately NOT a competing summary item. 2026-09-22: all four CSVs had been
    106 days stale since June 8 and the warning never once reached Slack — six
    `attention` flags outranked it in the `attention[:2] or warnings[:2]` pick
    below, so every morning reported June holdings under live prices as if they
    were today's. Staleness qualifies every other number on the line, so it leads
    the line whenever it is present and is never eligible to be dropped.
    """
    stale = [f for f in flags if f["kind"] == "stale_csv"]
    if not stale:
        return ""
    age = max(f.get("age_days") or 0 for f in stale)
    dates = {f.get("file_date") for f in stale if f.get("file_date")}
    as_of = f" from {sorted(dates)[-1]}" if len(dates) == 1 else ""
    noun = "CSV" if len(stale) == 1 else "CSVs"
    return (f"STALE DATA — {len(stale)} position {noun} {age}d old; "
            f"holdings and cash are{as_of}; refresh exports before acting.")


def summary_line(flags: list[dict[str, Any]]) -> str:
    summary_flags = [f for f in flags if f["kind"] not in SUMMARY_EXCLUDED_KINDS]
    attention = [f for f in summary_flags if f["severity"] == "attention"]
    warnings = [f for f in flags
                if f["severity"] == "warning" and f["kind"] != "stale_csv"]
    infos = [f for f in summary_flags if f["severity"] == "info"]
    chosen = attention[:2] or warnings[:2] or infos[:2]
    caveat = stale_caveat(flags)
    if not chosen:
        # "latest CSVs" reads as "current" — never say it about a stale export.
        body = ("no material cross-account flags." if caveat
                else "no material cross-account flags from latest CSVs.")
    else:
        body = "; ".join(f["message"] for f in chosen)
    return f"Portfolio watch: {caveat + ' ' if caveat else ''}{body}"


def write_payload(payload: dict[str, Any], state_dir: Path = STATE_DIR) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    json_path = state_dir / "latest.json"
    text_path = state_dir / "latest_summary.txt"
    payload["output_files"] = {
        "json": display_path(json_path),
        "text": display_path(text_path),
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    text_path.write_text(payload["summary"] + "\n")
    return payload


def run(
    no_quotes: bool = False,
    positions_dir: Path = POSITIONS_DIR,
    state_dir: Path = STATE_DIR,
) -> dict[str, Any]:
    latest = latest_position_files(positions_dir)
    if not latest:
        return write_payload({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "positions_csv",
            "quotes": "skipped" if no_quotes else "attempted",
            "accounts": [],
            "exposures_by_symbol": {},
            "flags": [{
                "severity": "warning",
                "kind": "missing_csv",
                "message": "No position CSV exports were found; cross-account context is unavailable",
            }],
            "summary": "Portfolio watch: no position CSV exports found; cross-account context unavailable.",
        }, state_dir=state_dir)

    accounts = [parse_position_file(path) for path in sorted(latest.values(), key=lambda p: p.name)]
    quotes = quote_symbols(accounts, no_quotes)
    enrich_holdings(accounts, quotes)
    exposures = build_exposures(accounts)
    flags = build_flags(accounts, exposures)
    summary = summary_line(flags)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "positions_csv",
        "quotes": "skipped" if no_quotes else "attempted",
        "accounts": [asdict(account) for account in accounts],
        "exposures_by_symbol": exposures,
        "flags": flags,
        "summary": summary,
    }

    return write_payload(payload, state_dir=state_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-quotes", action="store_true", help="Parse CSVs without Schwab quote enrichment.")
    parser.add_argument("--positions-dir", type=Path, default=POSITIONS_DIR, help="Directory of normalized or Schwab CSV snapshots.")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR, help="Directory for private generated reports.")
    args = parser.parse_args()

    payload = run(no_quotes=args.no_quotes, positions_dir=args.positions_dir, state_dir=args.state_dir)
    print(payload["summary"])
    print(f"Wrote {payload['output_files']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
