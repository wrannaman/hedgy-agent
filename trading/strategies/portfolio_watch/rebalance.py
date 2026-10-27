#!/usr/bin/env python3
"""Tax-aware cash-raise planner + trailing-stop watcher (recommendation-only).

Answers one question: "raise $X of cash with the least tax, and tell me which
concentrated winners have fallen far enough to trim." It NEVER places an order —
every output is a recommendation that requires the account owner's explicit confirmation
(repo CLAUDE.md). It reuses the portfolio_watch CSV loader + Schwab quote path so
there is one implementation of each (DRY).

Three things it produces:
  1. Free / negative-tax moves   — sheltered trims ($0 tax) and loss harvests
                                    (a loser banked against other gains = a refund).
  2. Tax-aware cash ladder        — to raise a taxable, SPENDABLE target, the
                                    cheapest-tax sequence of trims, running tax total.
  3. Trailing-stop triggers       — concentrated winners now down >= the trailing
                                    threshold from a rolling high tracked across runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.positions import (  # noqa: E402
    AccountSnapshot, Holding, latest_position_files, parse_position_file, POSITIONS_DIR,
)
from strategies.portfolio_watch import rules  # noqa: E402
from strategies.portfolio_watch.sweep import (  # noqa: E402  reuse quote + exposure plumbing
    build_bucket_exposures, build_exposures, dollars, enrich_holdings, holding_value, quote_symbols,
)

STATE_DIR = HERE / "state"
TRAILING_JSON = STATE_DIR / "trailing_highs.json"
OUT_JSON = STATE_DIR / "rebalance.json"
OUT_TEXT = STATE_DIR / "rebalance_summary.txt"


# --------------------------------------------------------------------------- #
# Per-lot economics (pure, testable — no Schwab/network).
# --------------------------------------------------------------------------- #
def ref_price(h: Holding) -> float | None:
    """Best available price: live quote if enriched, else the CSV snapshot price."""
    return h.live_price if h.live_price is not None else h.price


def eff_market_value(h: Holding) -> float:
    """Market value at the best available price (live re-prices the CSV snapshot)."""
    return holding_value(h)  # one implementation, shared with sweep (DRY)


def eff_gain(h: Holding) -> float | None:
    """Embedded gain in dollars, or None when cost basis is unknown ('Incomplete')."""
    if h.cost_basis is not None:
        return eff_market_value(h) - h.cost_basis
    return h.gain_dollars  # falls back to the CSV's figure; None if that's blank too


def treatment_for(suffix: str) -> str:
    return rules.ACCOUNT_TAX_TREATMENT.get(suffix, rules.TAXABLE)  # unknown -> assume taxable (safe)


def tax_effect(gain: float, treatment: str, rate: float) -> float:
    """Signed tax from fully realizing `gain`. Sheltered = 0. Taxable winner = +owe;
    taxable loser = -saved (it offsets other gains he has in size)."""
    if treatment != rules.TAXABLE:
        return 0.0
    return gain * rate


# --------------------------------------------------------------------------- #
# Candidate construction.
# --------------------------------------------------------------------------- #
def _portfolio_pct(symbol: str, exposures: dict[str, dict[str, Any]]) -> float:
    return float(exposures.get(symbol, {}).get("portfolio_pct", 0.0) or 0.0)


def _bucket_of(suffix: str) -> str:
    return rules.ACCOUNT_BUCKET.get(suffix, "taxable")


def _bucket_pct(symbol: str, bucket: str, totals: dict[str, float],
                by_symbol: dict[tuple[str, str], float]) -> float:
    total = totals.get(bucket) or 0.0
    return (by_symbol.get((bucket, symbol), 0.0) / total * 100) if total else 0.0


def build_candidates(
    accounts: list[AccountSnapshot],
    exposures: dict[str, dict[str, Any]],
    bucket_totals: dict[str, float],
    bucket_by_symbol: dict[tuple[str, str], float],
    rate: float,
    short_term_rate: float,
    hold: set[str],
    short_term: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One row per taxable, non-cash lot with computable economics.

    Returns (candidates, unknown). `unknown` is lots we refuse to plan (basis missing)
    so they're surfaced for manual review rather than silently dropped.
    """
    candidates: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for account in accounts:
        treatment = treatment_for(account.account_suffix)
        for h in account.holdings:
            if h.is_cash or h.symbol in hold:
                continue
            mv = eff_market_value(h)
            if mv < rules.MIN_TRIM_DOLLARS:
                continue
            gain = eff_gain(h)
            if gain is None:
                if treatment == rules.TAXABLE:
                    unknown.append({
                        "symbol": h.symbol, "account": account.account,
                        "suffix": account.account_suffix, "market_value": round(mv, 2),
                        "reason": "cost basis unknown (Incomplete) — tax can't be computed",
                    })
                continue
            r = short_term_rate if h.symbol in short_term else rate
            full_tax = tax_effect(gain, treatment, r)
            bucket = _bucket_of(account.account_suffix)
            candidates.append({
                "symbol": h.symbol,
                "account": account.account,
                "suffix": account.account_suffix,
                "bucket": bucket,
                "treatment": treatment,
                "spendable": treatment in rules.SPENDABLE_TREATMENTS,
                "market_value": round(mv, 2),
                "cost_basis": h.cost_basis,
                "gain": round(gain, 2),
                "gain_fraction": round(gain / mv, 4) if mv else 0.0,
                "rate": r,
                "tax_to_exit_full": round(full_tax, 2),       # signed: losers negative
                "tax_per_dollar": round(full_tax / mv, 4) if mv else 0.0,
                # concentration is bucket- and book-level, NOT per-account
                "bucket_pct": round(_bucket_pct(h.symbol, bucket, bucket_totals, bucket_by_symbol), 2),
                "portfolio_pct": _portfolio_pct(h.symbol, exposures),
                "is_loss": gain < 0,
            })
    return candidates, unknown


# --------------------------------------------------------------------------- #
# The three outputs.
# --------------------------------------------------------------------------- #
def harvest_moves(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Taxable losers — selling them banks a loss that shelters gains elsewhere.
    A loss inside a 401k/Roth is NOT harvestable (no tax event), so taxable-only."""
    losers = [c for c in candidates if c["is_loss"] and c["treatment"] == rules.TAXABLE]
    return sorted(losers, key=lambda c: c["gain"])  # biggest loss first


def free_moves(
    accounts: list[AccountSnapshot], exposures: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sheltered (Roth / 401k) holdings that can be trimmed to raise in-account dry
    powder at $0 current tax. Surfaced concentrated-first."""
    moves: list[dict[str, Any]] = []
    for account in accounts:
        if treatment_for(account.account_suffix) == rules.TAXABLE:
            continue
        for h in account.holdings:
            if h.is_cash:
                continue
            mv = eff_market_value(h)
            if mv < rules.MIN_TRIM_DOLLARS:
                continue
            moves.append({
                "symbol": h.symbol, "account": account.account,
                "suffix": account.account_suffix, "treatment": treatment_for(account.account_suffix),
                "market_value": round(mv, 2), "account_pct": h.account_pct,
                "portfolio_pct": _portfolio_pct(h.symbol, exposures),
                "note": "tax-free to trim; proceeds are in-account dry powder, not spendable",
            })
    return sorted(moves, key=lambda m: m["market_value"], reverse=True)


def top_concentrations(
    bucket_totals: dict[str, float],
    bucket_by_symbol: dict[tuple[str, str], float],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Largest single names by DOLLAR size, each tagged with its share of its BUCKET
    (taxable book / 401k / Roth). Ranked by dollars so a tiny bucket's 100% can't
    outrank a real position — the bucket_pct is context, not the sort key. Independent
    of cost basis, so names with unknown basis (e.g. JNJ) still show up."""
    rows = []
    for (bucket, symbol), mv in bucket_by_symbol.items():
        total = bucket_totals.get(bucket) or 0.0
        rows.append({
            "symbol": symbol, "bucket": bucket,
            "bucket_label": rules.BUCKET_LABEL.get(bucket, bucket),
            "bucket_pct": round(mv / total * 100, 2) if total else 0.0,
            "market_value": round(mv, 2),
        })
    return sorted(rows, key=lambda r: r["market_value"], reverse=True)[:limit]


def plan_ladder(
    candidates: list[dict[str, Any]], target: float,
) -> dict[str, Any]:
    """Greedy least-tax sequence to raise `target` of SPENDABLE (taxable) cash.

    Sorted by tax-per-dollar ascending: loss harvests (negative) first, then
    high-basis / low-gain names, then the big winners last. Partial sells realize a
    proportional slice of the gain.
    """
    pool = sorted(
        (c for c in candidates if c["spendable"]),
        key=lambda c: (c["tax_per_dollar"], -c["market_value"]),
    )
    rungs: list[dict[str, Any]] = []
    raised = tax = 0.0
    for c in pool:
        if raised >= target:
            break
        take = min(c["market_value"], target - raised)
        fraction = take / c["market_value"] if c["market_value"] else 0.0
        rung_tax = c["tax_to_exit_full"] * fraction
        raised += take
        tax += rung_tax
        rungs.append({
            "symbol": c["symbol"], "account": c["account"], "suffix": c["suffix"],
            "sell_dollars": round(take, 2),
            "fraction_of_position": round(fraction, 3),
            "tax": round(rung_tax, 2),
            "tax_per_dollar": c["tax_per_dollar"],
            "portfolio_pct": c["portfolio_pct"],
            "kind": "harvest_loss" if c["is_loss"] else "trim_winner",
        })
    return {
        "target": round(target, 2),
        "raised": round(raised, 2),
        "shortfall": round(max(0.0, target - raised), 2),
        "total_tax": round(tax, 2),
        "blended_rate": round(tax / raised, 4) if raised else 0.0,
        "rungs": rungs,
    }


# --------------------------------------------------------------------------- #
# Trailing-stop watcher (the "tax-aware stop loss").
# --------------------------------------------------------------------------- #
def load_trailing(path: Path = TRAILING_JSON) -> dict[str, float]:
    if path.exists():
        try:
            return {k: float(v) for k, v in json.loads(path.read_text()).items()}
        except (ValueError, json.JSONDecodeError):
            return {}
    return {}


def update_trailing(
    accounts: list[AccountSnapshot], prev: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Ratchet each symbol's rolling high with the best price seen this run, and
    measure the current drawdown from it."""
    result: dict[str, dict[str, float]] = {}
    for account in accounts:
        for h in account.holdings:
            price = ref_price(h)
            if h.is_cash or price is None:
                continue
            high = max(prev.get(h.symbol, 0.0), price, result.get(h.symbol, {}).get("high", 0.0))
            drawdown = (price / high - 1.0) * 100 if high else 0.0
            result[h.symbol] = {"high": round(high, 4), "price": round(price, 4),
                                "drawdown_pct": round(drawdown, 2)}
    return result


def stop_triggers(
    accounts: list[AccountSnapshot],
    exposures: dict[str, dict[str, Any]],
    bucket_totals: dict[str, float],
    bucket_by_symbol: dict[tuple[str, str], float],
    trailing: dict[str, dict[str, float]],
    rate: float,
    hold: set[str],
) -> list[dict[str, Any]]:
    """Concentrated winners now down >= the trailing threshold from their rolling high.
    Concentration is bucket- and book-level (NOT per-account): a name qualifies if it's
    a big share of its bucket (e.g. the combined taxable book) or of the whole book.
    A trim suggestion with its tax cost — a flag, never an auto-order."""
    # where is each symbol most concentrated? (bucket, pct) across the buckets it's in
    peak_bucket: dict[str, tuple[str, float]] = {}
    for (bucket, symbol), mv in bucket_by_symbol.items():
        total = bucket_totals.get(bucket) or 0.0
        pct = mv / total * 100 if total else 0.0
        if pct > peak_bucket.get(symbol, ("", 0.0))[1]:
            peak_bucket[symbol] = (bucket, pct)

    triggers: list[dict[str, Any]] = []
    for symbol, exp in exposures.items():
        if symbol in hold:
            continue
        port_pct = float(exp.get("portfolio_pct", 0.0) or 0.0)
        bucket, bucket_pct = peak_bucket.get(symbol, ("", 0.0))
        concentrated = (bucket_pct >= rules.CONCENTRATION_BUCKET_PCT
                        or port_pct >= rules.CONCENTRATION_PORTFOLIO_PCT)
        track = trailing.get(symbol)
        if not concentrated or not track or track["drawdown_pct"] > -rules.TRAILING_STOP_PCT:
            continue
        # tax to trim back the position, from taxable lots only
        taxable_mv = taxable_gain = 0.0
        for account in accounts:
            if treatment_for(account.account_suffix) != rules.TAXABLE:
                continue
            for h in account.holdings:
                if h.symbol != symbol or h.is_cash:
                    continue
                g = eff_gain(h)
                if g is not None:
                    taxable_mv += eff_market_value(h)
                    taxable_gain += g
        label = rules.BUCKET_LABEL.get(bucket, bucket)
        triggers.append({
            "symbol": symbol,
            "bucket": bucket,
            "bucket_pct": round(bucket_pct, 2),
            "portfolio_pct": round(port_pct, 2),
            "drawdown_from_high_pct": track["drawdown_pct"],
            "high": track["high"], "price": track["price"],
            "taxable_market_value": round(taxable_mv, 2),
            "taxable_gain": round(taxable_gain, 2),
            "tax_to_exit_taxable": round(max(0.0, taxable_gain) * rate, 2),
            "message": (f"{symbol} is {bucket_pct:.1f}% of the {label} "
                        f"({port_pct:.1f}% of the whole book) and down "
                        f"{abs(track['drawdown_pct']):.1f}% from its high — past the "
                        f"{rules.TRAILING_STOP_PCT:.0f}% trailing stop; consider trimming."),
        })
    return sorted(triggers, key=lambda t: t["drawdown_from_high_pct"])


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #
def build_text(payload: dict[str, Any]) -> str:
    lines = ["Tax-aware rebalance — recommendation only, no orders placed.", ""]
    # Staleness leads, because every dollar below is computed from the exports.
    # 2026-09-22: `stale_accounts` had been in the payload but read by nothing, so
    # a 106-day-old June book rendered a $50k cash ladder — named lots, named tax —
    # with no hint the share counts and cost bases were four months old.
    stale = payload.get("stale_accounts") or []
    if stale:
        as_of = payload.get("stale_as_of")
        noun = "export is" if len(stale) == 1 else "exports are"
        lines.insert(1, f"  STALE — {len(stale)} position {noun} "
                        f"{payload.get('stale_age_days', 0)} days old"
                        f"{f' (as of {as_of})' if as_of else ''}. Share counts, cash and "
                        f"cost bases are from then; re-export before acting on anything below.")
    conc = payload.get("concentration", [])
    if conc:
        lines.append("BIGGEST POSITIONS (% of their configured portfolio bucket):")
        for c in conc:
            lines.append(f"  • {c['symbol']:6s} {c['bucket_pct']:>5.1f}% of {c['bucket_label']:13s} "
                         f"({dollars(c['market_value'])})")
        lines.append("")
    harvests = payload["harvests"]
    if harvests:
        total = sum(h["gain"] for h in harvests)
        offset = sum(h["tax_to_exit_full"] for h in harvests)
        lines.append(f"LOSS HARVESTS (sell to bank losses, shelter other gains): "
                     f"{dollars(total)} of losses ≈ {dollars(-offset)} tax saved")
        for h in harvests:
            lines.append(f"  • {h['symbol']} ({h['account']}): {dollars(h['gain'])} "
                         f"loss on {dollars(h['market_value'])}")
        lines.append("")
    triggers = payload["trailing_stops"]
    if triggers:
        lines.append("TRAILING-STOP TRIGGERS:")
        for t in triggers:
            lines.append(f"  • {t['message']} Full taxable exit tax ≈ {dollars(t['tax_to_exit_taxable'])}.")
        lines.append("")
    ladder = payload["cash_ladder"]
    lines.append(f"CASH LADDER — raise {dollars(ladder['target'])} spendable, "
                 f"least tax first: got {dollars(ladder['raised'])} for "
                 f"{dollars(ladder['total_tax'])} tax ({ladder['blended_rate'] * 100:.1f}% blended)")
    for r in ladder["rungs"]:
        lines.append(f"  {r['kind']:13s} {r['symbol']:6s} {r['account']:20s} "
                     f"sell {dollars(r['sell_dollars'])}  tax {dollars(r['tax'])}")
    if ladder["shortfall"] > 0:
        lines.append(f"  (short {dollars(ladder['shortfall'])} — not enough non-held taxable to hit target)")
    free = payload["free_moves"]
    if free:
        lines.append("")
        lines.append("FREE (sheltered, $0 tax — in-account dry powder):")
        for m in free[:6]:
            lines.append(f"  • {m['symbol']} ({m['account']}): {dollars(m['market_value'])}")
    if payload["needs_review"]:
        lines.append("")
        lines.append("NEEDS REVIEW (excluded from plan):")
        for u in payload["needs_review"]:
            lines.append(f"  • {u['symbol']} ({u['account']}): {u['reason']}")
    return "\n".join(lines)


def run(
    target: float | None = None,
    hold: set[str] | None = None,
    short_term: set[str] | None = None,
    ca_rate: float = rules.CA_RATE,
    fed_rate: float = rules.FED_LTCG_RATE,
    no_quotes: bool = False,
    positions_dir: Path = POSITIONS_DIR,
    state_dir: Path = STATE_DIR,
) -> dict[str, Any]:
    hold = {s.upper() for s in (hold or set())}
    short_term = {s.upper() for s in (short_term or set())}
    target = rules.DEFAULT_CASH_TARGET if target is None else target
    rate = rules.all_in_lt_rate(ca_rate=ca_rate, fed_rate=fed_rate)
    short_rate = short_term and rules.all_in_lt_rate(ca_rate=ca_rate, fed_rate=rules.SHORT_TERM_FED_RATE) or rate

    latest = latest_position_files(positions_dir)
    accounts = [parse_position_file(path) for path in sorted(latest.values(), key=lambda p: p.name)]
    quotes = quote_symbols(accounts, no_quotes)
    enrich_holdings(accounts, quotes)
    exposures = build_exposures(accounts)
    bucket_totals, bucket_by_symbol = build_bucket_exposures(accounts)

    candidates, unknown = build_candidates(
        accounts, exposures, bucket_totals, bucket_by_symbol, rate, short_rate, hold, short_term)
    trailing = update_trailing(accounts, load_trailing(state_dir / "trailing_highs.json"))

    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "quotes": "skipped" if no_quotes else "attempted",
        "all_in_lt_rate": round(rate, 4),
        "held_out": sorted(hold),
        "stale_accounts": [a.account for a in accounts if a.stale],
        # Age/date of the oldest stale export, so build_text can caveat the plan
        # instead of printing sell amounts as though the holdings were current.
        "stale_age_days": max((a.age_days or 0 for a in accounts if a.stale), default=0),
        "stale_as_of": min((a.file_date for a in accounts if a.stale and a.file_date),
                           default=None),
        "concentration": top_concentrations(bucket_totals, bucket_by_symbol),
        "harvests": harvest_moves(candidates),
        "trailing_stops": stop_triggers(
            accounts, exposures, bucket_totals, bucket_by_symbol, trailing, rate, hold),
        "cash_ladder": plan_ladder(candidates, target),
        "free_moves": free_moves(accounts, exposures),
        "needs_review": unknown,
    }
    payload["summary"] = build_text(payload)

    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trailing_highs.json").write_text(
        json.dumps({s: v["high"] for s, v in trailing.items()}, indent=2))
    (state_dir / "rebalance.json").write_text(json.dumps(payload, indent=2, default=str))
    (state_dir / "rebalance_summary.txt").write_text(payload["summary"] + "\n")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Tax-aware cash-raise planner + trailing-stop watcher.")
    p.add_argument("--target", type=float, default=None, help="Spendable taxable cash to raise.")
    p.add_argument("--hold", default="", help="Comma-separated symbols to exclude (e.g. NVDA).")
    p.add_argument("--short-term", default="", help="Comma-separated symbols whose lots are short-term.")
    p.add_argument("--ca-rate", type=float, default=rules.CA_RATE, help="CA marginal rate on gains.")
    p.add_argument("--fed-rate", type=float, default=rules.FED_LTCG_RATE, help="Federal LTCG rate.")
    p.add_argument("--no-quotes", action="store_true", help="Use CSV prices; skip live Schwab quotes.")
    p.add_argument("--positions-dir", type=Path, default=POSITIONS_DIR, help="Directory of normalized or Schwab CSV snapshots.")
    p.add_argument("--state-dir", type=Path, default=STATE_DIR, help="Directory for private generated reports.")
    args = p.parse_args()

    payload = run(
        target=args.target,
        hold={s.strip() for s in args.hold.split(",") if s.strip()},
        short_term={s.strip() for s in args.short_term.split(",") if s.strip()},
        ca_rate=args.ca_rate, fed_rate=args.fed_rate, no_quotes=args.no_quotes,
        positions_dir=args.positions_dir, state_dir=args.state_dir,
    )
    print(payload["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
