#!/usr/bin/env python3
"""Covered-call candidate scanner for owned 401k shares.

Recommendation-only. It never places orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
STATE_DIR = HERE / "state"
OUTPUT_JSON = STATE_DIR / "covered_calls.json"
OUTPUT_TEXT = STATE_DIR / "covered_calls.txt"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))   # so `rules` resolves whether run as a script or imported
from shared.positions import latest_position_files, parse_position_file
from rules import (  # canonical sleeve numbers (single source)
    DTE_MIN, DTE_MAX, CC_MIN_OTM_PCT as MIN_OTM_PCT,
    CC_MAX_SPREAD_PCT as MAX_SPREAD_PCT, CC_MIN_PREMIUM_DOLLARS as MIN_PREMIUM_DOLLARS,
    CC_MIN_ANNUALIZED_PCT,
)
try:
    from . import wheel  # wheel shares floor the call strike at cost basis (RULES.md §13)
except ImportError:
    import wheel  # script run
CORE_PARTIAL_LIMITS = {
    "IBIT": 2,
}
AVOID_BY_DEFAULT = {
    "VGT": "ETF options can be thin; require manual liquidity review",
    "VOO": "core index ETF; avoid capping unless explicitly approved",
    "VONG": "core growth ETF; avoid capping unless explicitly approved",
}


@dataclass
class EligibleHolding:
    symbol: str
    description: str
    quantity: float
    price: float | None
    market_value: float
    max_contracts: int
    default_contracts: int
    account_pct: float | None
    note: str


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_401k_holdings() -> list[EligibleHolding]:
    latest = latest_position_files(REPO_ROOT / "positions")
    from shared.accounts import configured_account_suffix
    path = latest.get(configured_account_suffix())
    if not path:
        return []
    account = parse_position_file(path)
    holdings: list[EligibleHolding] = []
    for holding in account.holdings:
        if holding.is_cash or (holding.quantity or 0) < 100:
            continue
        max_contracts = int((holding.quantity or 0) // 100)
        default_contracts = min(max_contracts, CORE_PARTIAL_LIMITS.get(holding.symbol, max_contracts))
        note = AVOID_BY_DEFAULT.get(holding.symbol, "")
        holdings.append(EligibleHolding(
            symbol=holding.symbol,
            description=holding.description,
            quantity=holding.quantity or 0,
            price=holding.price,
            market_value=holding.market_value,
            max_contracts=max_contracts,
            default_contracts=default_contracts,
            account_pct=holding.account_pct,
            note=note,
        ))
    return holdings


def best_call(client: Any, holding: EligibleHolding, min_strike: float | None = None) -> dict[str, Any] | None:
    """min_strike: hard strike floor for wheel-assigned shares — the cycle's cost
    basis (RULES.md §13: never sell a call below basis, or a bounce calls the
    shares away at a locked-in loss). None for ordinary holdings."""
    from schwab.client import Client

    if holding.default_contracts <= 0:
        return None
    today = date.today()
    resp = client.get_option_chain(
        holding.symbol,
        contract_type=Client.Options.ContractType.CALL,
        from_date=today + timedelta(days=DTE_MIN),
        to_date=today + timedelta(days=DTE_MAX),
    )
    resp.raise_for_status()
    chain = resp.json()
    spot = chain.get("underlyingPrice") or holding.price
    if not spot:
        return None

    best = None
    for expkey, strikes in chain.get("callExpDateMap", {}).items():
        exp = expkey.split(":")[0]
        for strike_str, contracts in strikes.items():
            contract = contracts[0]
            strike = float(strike_str)
            bid = contract.get("bid") or 0
            ask = contract.get("ask") or 0
            dte = contract.get("daysToExpiration") or 0
            if bid <= 0 or ask <= 0 or not (DTE_MIN <= dte <= DTE_MAX):
                continue
            otm_pct = (strike - spot) / spot * 100
            if otm_pct < MIN_OTM_PCT:
                continue
            if min_strike is not None and strike < min_strike:
                continue  # wheel basis floor — never cap assigned shares below cost
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100 if mid else 999
            if spread_pct > MAX_SPREAD_PCT:
                continue
            premium_dollars = mid * 100 * holding.default_contracts
            if premium_dollars < MIN_PREMIUM_DOLLARS:
                continue
            dollars_per_day = premium_dollars / max(dte, 1)
            # Yield on the capital this call would CAP (the shares it can call away),
            # annualized. This — not the absolute dollar premium — is what the verdict
            # gate judges: capping $6,720 of a convex hold for 11%/yr is a SKIP even
            # though $88 clears the $25 pre-filter.
            capped_capital = spot * 100 * holding.default_contracts
            annualized_pct = (premium_dollars / capped_capital) / max(dte, 1) * 365 * 100 if capped_capital else 0
            candidate = {
                "symbol": holding.symbol,
                "spot": round(spot, 2),
                "strike": strike,
                "expiration": exp,
                "dte": dte,
                "contracts": holding.default_contracts,
                "max_contracts": holding.max_contracts,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "mid": round(mid, 2),
                "otm_pct": round(otm_pct, 1),
                "premium_dollars": round(premium_dollars, 2),
                "dollars_per_day": round(dollars_per_day, 2),
                "annualized_pct": round(annualized_pct, 1),
                "spread_pct": round(spread_pct, 1),
                "note": holding.note,
            }
            if min_strike is not None:
                candidate["wheel_basis"] = round(min_strike, 2)
            if best is None or candidate["dollars_per_day"] > best["dollars_per_day"]:
                best = candidate
    return best


def verdict(candidate: dict[str, Any] | None) -> dict[str, str] | None:
    """The single committed decision for a covered-call candidate: SELL or SKIP, with
    a reason. Same contract as monitor.py's `do`: decided here in code from rules.py,
    transcribed verbatim by every renderer, never re-derived in chat. Eligibility got
    the candidate this far; this is the judgment that makes a surfaced trade actionable.

    SKIP if the holding carries an avoid-note, or if the premium annualized over the
    capped capital is below CC_MIN_ANNUALIZED_PCT — too thin to justify capping. Else
    SELL.
    """
    if candidate is None:
        return None
    ann = candidate.get("annualized_pct", 0)
    if candidate.get("note"):
        return {"do": "SKIP", "reason": candidate["note"]}
    if ann < CC_MIN_ANNUALIZED_PCT:
        return {"do": "SKIP", "reason": (
            f"{ann:.0f}%/yr on capped capital is below the {CC_MIN_ANNUALIZED_PCT:.0f}% floor — "
            f"too thin to cap {candidate['symbol']}; hold the shares uncapped."
        )}
    return {"do": "SELL", "reason": (
        f"{ann:.0f}%/yr on capped capital clears the {CC_MIN_ANNUALIZED_PCT:.0f}% floor."
    )}


def scan(no_quotes: bool = False) -> dict[str, Any]:
    holdings = load_401k_holdings()
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []

    wheel_floors = wheel.min_call_strikes()  # {} until a CSP is ever assigned
    if not no_quotes and holdings:
        from shared.auth import get_client
        client = get_client()
        for holding in holdings:
            try:
                candidate = best_call(client, holding, min_strike=wheel_floors.get(holding.symbol))
                if candidate:
                    candidates.append(candidate)
            except Exception as exc:
                errors.append(f"{holding.symbol}: {type(exc).__name__}: {exc}")

    candidates.sort(key=lambda c: c.get("dollars_per_day", 0), reverse=True)
    for candidate in candidates:
        candidate["verdict"] = verdict(candidate)
    summary = summarize(holdings, candidates, no_quotes, errors)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "eligibility_only" if no_quotes else "live_chain",
        "eligible_holdings": [asdict(holding) for holding in holdings],
        "candidates": candidates,
        "errors": errors,
        "summary": summary,
    }
    return write_payload(payload)


def summarize(
    holdings: list[EligibleHolding],
    candidates: list[dict[str, Any]],
    no_quotes: bool,
    errors: list[str],
) -> str:
    if candidates:
        best = candidates[0]
        v = best.get("verdict") or verdict(best)
        ident = (
            f"{best['contracts']}x {best['symbol']} ${best['strike']:.0f} call "
            f"({best['otm_pct']:.0f}% OTM, ${best['premium_dollars']:.0f}, "
            f"{best.get('annualized_pct', 0):.0f}%/yr)"
        )
        if best.get("wheel_basis") is not None:
            ident += f" [wheel shares, basis ${best['wheel_basis']:g} — strike floored there]"
        if v["do"] == "SELL":
            # Schwab order-ticket fields, ready to enter (see schwab-order-format).
            return (
                f"Covered call: SELL — {ident}. {v['reason']}\n"
                f"  Sell to Open · {best['contracts']} · {best['symbol']} "
                f"{best['expiration']} ${best['strike']:.2f} Call · Limit ${best['mid']:.2f} · Day"
            )
        return f"Covered call: SKIP — best is {ident}. {v['reason']}"
    if holdings and no_quotes:
        names = ", ".join(f"{h.symbol} up to {h.default_contracts}" for h in holdings[:3])
        return f"Covered calls: eligible owned shares found ({names}); run live chain scan before recommending"
    if errors:
        return f"Covered calls: live scan failed; {errors[0]}"
    return "Covered calls: no eligible 401k share lots"


def write_payload(payload: dict[str, Any]) -> dict[str, Any]:
    STATE_DIR.mkdir(exist_ok=True)
    payload["output_files"] = {
        "json": display_path(OUTPUT_JSON),
        "text": display_path(OUTPUT_TEXT),
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    OUTPUT_TEXT.write_text(payload["summary"] + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-quotes", action="store_true", help="Only identify eligible holdings from CSV.")
    args = parser.parse_args()

    payload = scan(no_quotes=args.no_quotes)
    print(payload["summary"])
    print(f"Wrote {payload['output_files']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
