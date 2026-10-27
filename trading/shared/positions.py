"""Shared Schwab position-CSV loading (plumbing — generic, not strategy-specific).

ONE implementation of position-CSV parsing, used by portfolio_watch, covered_calls,
and anything else — so no sleeve cross-imports another sleeve's code (DRY; FUND.md §3).
Strategy-specific analysis (flags, sizing) stays in the sleeve, not here.
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POSITIONS_DIR = REPO_ROOT / "positions"
STALE_DAYS = 10


@dataclass
class Holding:
    account: str
    account_suffix: str
    symbol: str
    description: str
    quantity: float | None
    price: float | None
    market_value: float
    day_change_pct: float | None
    day_change_dollars: float | None
    cost_basis: float | None
    gain_pct: float | None
    gain_dollars: float | None
    account_pct: float | None
    asset_type: str
    is_cash: bool = False
    live_price: float | None = None
    live_change_pct: float | None = None


@dataclass
class AccountSnapshot:
    account: str
    account_suffix: str
    file: str
    as_of: str | None
    file_date: str | None
    age_days: int | None
    stale: bool
    holdings: list[Holding] = field(default_factory=list)
    total_market_value: float = 0.0
    cash_value: float = 0.0


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace("$", "").replace(",", "").replace("%", "")
    if text in {"", "--", "N/A", "Incomplete", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_metadata(line: str) -> tuple[str, str, str | None]:
    match = re.search(r"account (?P<account>.+?) \.\.\.(?P<suffix>\d+) as of (?P<asof>.+)\"?$", line.strip('"'))
    if not match:
        return "unknown", "", None
    return match.group("account"), match.group("suffix"), match.group("asof")


def file_stamp(path: Path) -> datetime | None:
    match = re.search(r"Positions-(\d{4})-(\d{2})-(\d{2})-(\d{6})\.csv$", path.name)
    if not match:
        return None
    y, m, d, hms = match.groups()
    return datetime.strptime(f"{y}-{m}-{d}-{hms}", "%Y-%m-%d-%H%M%S")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def latest_position_files(positions_dir: Path = POSITIONS_DIR) -> dict[str, Path]:
    latest: dict[str, tuple[datetime, Path]] = {}
    for path in positions_dir.glob("*.csv"):
        with path.open(newline="", encoding="utf-8-sig") as f:
            first = f.readline().strip()
        if "account_id" in next(csv.reader([first]), []):
            snapshot = parse_normalized_file(path)
            stamp = datetime.fromisoformat(snapshot.file_date)
            key = snapshot.account_suffix
        else:
            stamp = file_stamp(path)
            if stamp is None:
                continue
            account, suffix, _ = parse_metadata(first)
            key = suffix or account
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, path)
    return {key: path for key, (_, path) in latest.items()}


def parse_position_file(path: Path, today: date | None = None) -> AccountSnapshot:
    today = today or date.today()
    with path.open(newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f), [])
    if "account_id" in header:
        return parse_normalized_file(path, today)
    stamp = file_stamp(path)
    file_date = stamp.date() if stamp else None
    age_days = (today - file_date).days if file_date else None

    with path.open(newline="") as f:
        lines = f.readlines()
    if not lines:
        raise ValueError(f"empty position file: {path}")

    account, suffix, as_of = parse_metadata(lines[0].strip())
    header_index = next((i for i, line in enumerate(lines) if line.startswith('"Symbol"')), None)
    if header_index is None:
        raise ValueError(f"missing Schwab positions header: {path}")

    reader = csv.DictReader(lines[header_index:])
    snapshot = AccountSnapshot(
        account=account,
        account_suffix=suffix,
        file=display_path(path),
        as_of=as_of,
        file_date=str(file_date) if file_date else None,
        age_days=age_days,
        stale=age_days is not None and age_days > STALE_DAYS,
    )

    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        if not symbol or symbol == "Positions Total":
            if symbol == "Positions Total":
                snapshot.total_market_value = parse_number(row.get("Mkt Val (Market Value)")) or 0.0
            continue

        asset_type = (row.get("Asset Type") or "").strip()
        market_value = parse_number(row.get("Mkt Val (Market Value)")) or 0.0
        is_cash = asset_type == "Cash and Money Market" or symbol == "Cash & Cash Investments"
        holding = Holding(
            account=account,
            account_suffix=suffix,
            symbol=symbol,
            description=(row.get("Description") or "").strip(),
            quantity=parse_number(row.get("Qty (Quantity)")),
            price=parse_number(row.get("Price")),
            market_value=market_value,
            day_change_pct=parse_number(row.get("Day Chng % (Day Change %)")),
            day_change_dollars=parse_number(row.get("Day Chng $ (Day Change $)")),
            cost_basis=parse_number(row.get("Cost Basis")),
            gain_pct=parse_number(row.get("Gain % (Gain/Loss %)")),
            gain_dollars=parse_number(row.get("Gain $ (Gain/Loss $)")),
            account_pct=parse_number(row.get("% of Acct (% of Account)")),
            asset_type=asset_type,
            is_cash=is_cash,
        )
        if is_cash:
            snapshot.cash_value += market_value
        snapshot.holdings.append(holding)

    if not snapshot.total_market_value:
        snapshot.total_market_value = sum(h.market_value for h in snapshot.holdings)
    return snapshot


def parse_normalized_file(path: Path, today: date | None = None) -> AccountSnapshot:
    """Read one broker-independent account snapshot; account_id is a local alias.

    Required: account_id, account_name, as_of (ISO date), symbol, quantity,
    price, market_value. Optional: cost_basis, asset_type, description,
    day_change_pct, day_change_dollars. Use asset_type=cash for cash rows.
    """
    today = today or date.today()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"account_id", "account_name", "as_of", "symbol", "quantity", "price", "market_value"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing normalized CSV columns: {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Empty normalized portfolio: {path}")
    first = rows[0]
    account_id = first["account_id"].strip()
    account_name = first["account_name"].strip()
    as_of = first["as_of"].strip()
    if not account_id or not account_name:
        raise ValueError(f"Missing account ID or name: {path}")
    file_date = date.fromisoformat(as_of)
    if file_date > today:
        raise ValueError(f"Portfolio as_of is in the future: {path}")
    age = (today - file_date).days
    snapshot = AccountSnapshot(account_name, account_id, display_path(path), as_of,
                               str(file_date), age, age > STALE_DAYS)
    for row in rows:
        if (row["account_id"].strip(), row["account_name"].strip(), row["as_of"].strip()) != (account_id, account_name, as_of):
            raise ValueError(f"Use one account and snapshot date per CSV: {path}")
        symbol = row["symbol"].strip()
        mv = parse_number(row["market_value"])
        if not symbol or mv is None or not math.isfinite(mv):
            raise ValueError(f"Each holding requires symbol and market_value: {path}")
        basis = parse_number(row.get("cost_basis"))
        asset = row.get("asset_type", "equity").strip().lower()
        cash = asset == "cash"
        asset_label = {"cash": "Cash and Money Market", "equity": "Equity",
                       "etf": "ETFs & Closed End Funds", "option": "Option"}.get(asset)
        if asset_label is None:
            raise ValueError(f"Unknown asset_type {asset!r}: {path}")
        gain = mv - basis if basis is not None else None
        h = Holding(account_name, account_id, symbol, row.get("description", ""),
                    parse_number(row["quantity"]), parse_number(row["price"]), mv,
                    parse_number(row.get("day_change_pct")), parse_number(row.get("day_change_dollars")),
                    basis, gain / abs(basis) * 100 if basis and gain is not None else None,
                    gain, None, asset_label, cash)
        snapshot.holdings.append(h)
        snapshot.total_market_value += mv
        if cash:
            snapshot.cash_value += mv
    for h in snapshot.holdings:
        h.account_pct = h.market_value / snapshot.total_market_value * 100 if snapshot.total_market_value else 0.0
    return snapshot
