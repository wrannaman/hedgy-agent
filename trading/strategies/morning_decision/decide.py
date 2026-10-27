#!/usr/bin/env python3
"""Build the deterministic morning decision.

This module turns existing strategy outputs into one recommended next action.
It does not place orders and does not replace the mandatory bad-news check.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CSP_STATE = REPO_ROOT / "strategies" / "csp_401k" / "state"
PORTFOLIO_STATE = REPO_ROOT / "strategies" / "portfolio_watch" / "state"
CATALYST_STATE = REPO_ROOT / "strategies" / "catalyst_check" / "state"
STATE_DIR = HERE / "state"

LAST_SCREEN = CSP_STATE / "last_screen.json"
TRADE_LOG = CSP_STATE / "trade_log.json"
PORTFOLIO_LATEST = PORTFOLIO_STATE / "latest.json"
CATALYST_LATEST = CATALYST_STATE / "latest.json"
COVERED_CALLS = CSP_STATE / "covered_calls.json"
VOL_REGIME = REPO_ROOT / "state" / "vol_regime.json"  # written by fund_engine, same run
DECISION_JSON = STATE_DIR / "morning_decision.json"
DECISION_TEXT = STATE_DIR / "morning_decision.txt"

MAX_SCREEN_AGE_HOURS = 12
MAX_VOL_REGIME_AGE_HOURS = 12
MAX_CATALYST_AGE_HOURS = 6
MIN_CANDIDATE_DOLLARS_PER_DAY = 3.0
# REMOVED 2026-07-07: PORTFOLIO_OVERLAP_PENALTY (was 0.65). Cross-account holdings are
# FYI-ONLY (RULES.md §7): they surface as a note for the account owner — the portfolio-level risk
# manager — but never score, gate, or veto a 401k candidate. The engine sees a partial
# slice of net worth, so any "total portfolio risk" scoring is theater on incomplete
# data, and it was distorting the ranking away from the richest edge (the account owner's call).
# Within-book correlation (duplicate underlying, correlated groups) still gates.
NO_CSV_PENALTY = 0.85
CATALYST_CAUTION_PENALTY = 0.60


@dataclass
class CandidateDecision:
    symbol: str
    strike: float
    expiration: str
    dte: int
    premium_dollars: float
    collateral: float
    cushion_pct: float
    implied_move_pct: float
    vrp: float | None
    fits_cash: bool
    prob_safe: float
    dollars_per_day: float
    score: float
    penalties: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def symbol_state_path(symbol: str, state_dir: Path = CATALYST_STATE) -> Path:
    safe = "".join(char if char.isalnum() or char in "_.-" else "_" for char in symbol.upper())
    return state_dir / f"{safe}.json"


def load_catalyst_state(
    screen: dict[str, Any],
    latest_path: Path = CATALYST_LATEST,
    state_dir: Path = CATALYST_STATE,
) -> dict[str, Any]:
    latest = load_json(latest_path, {})
    by_symbol: dict[str, Any] = {}
    if latest.get("symbol"):
        by_symbol[str(latest["symbol"])] = latest
    for candidate in screen.get("candidates", []):
        symbol = candidate.get("symbol")
        if symbol:
            payload = load_json(symbol_state_path(str(symbol), state_dir), {})
            if payload.get("symbol"):
                by_symbol[str(payload["symbol"])] = payload
    return {
        "latest": latest,
        "by_symbol": by_symbol,
    }


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def naive_timestamp(value: str | None) -> datetime | None:
    ts = parse_timestamp(value)
    if ts is None:
        return None
    return ts.replace(tzinfo=None)


def screen_age_hours(screen: dict[str, Any], now: datetime) -> float | None:
    ts = naive_timestamp(screen.get("timestamp"))
    if ts is None:
        return None
    return (now - ts).total_seconds() / 3600


def catalyst_applies(
    catalyst: dict[str, Any] | None,
    symbol: str,
    screen: dict[str, Any],
    now: datetime,
) -> bool:
    if not catalyst or catalyst.get("symbol") != symbol:
        return False
    if not screen.get("timestamp") or catalyst.get("screen_timestamp") != screen.get("timestamp"):
        return False
    generated_at = naive_timestamp(catalyst.get("generated_at"))
    if generated_at is None:
        return False
    screen_ts = naive_timestamp(screen.get("timestamp"))
    if screen_ts and generated_at < screen_ts:
        return False
    return (now - generated_at) <= timedelta(hours=MAX_CATALYST_AGE_HOURS)


def catalyst_for_symbol(catalyst_state: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not catalyst_state:
        return None
    by_symbol = catalyst_state.get("by_symbol") or {}
    if by_symbol.get(symbol):
        return by_symbol[symbol]
    if catalyst_state.get("symbol") == symbol:
        return catalyst_state
    return None


def probability_safe(candidate: dict[str, Any]) -> float:
    """Probability the put expires worthless.

    Delta IS that number — it is the market's own probability the put finishes in the
    money, so 1 - delta is the answer directly ("delta<->probability is definitional",
    RULES.md §2). Prefer it whenever the chain gave us one.

    The cushion/implied-move ratio below is the legacy fallback, kept only for records
    without a delta (older state files, hand-built candidates). It became actively
    misleading on 2026-07-13 when the screener's depth gate moved from a linear
    expected-move cushion to a delta band (rules.MAX_DELTA): a legitimate 16-delta put —
    ~84% safe — sits INSIDE the implied move, so this ratio scores it 0.65 and the morning
    layer would rank down exactly the trades the screener is now built to find.
    """
    delta = candidate.get("delta")
    if delta is not None:
        return round(1.0 - abs(delta), 2)

    implied = candidate.get("implied_move_pct") or 0
    cushion = candidate.get("cushion_pct") or 0
    if implied <= 0:
        return 0.80
    ratio = cushion / implied
    if ratio >= 1.5:
        return 0.90
    if ratio >= 1.0:
        return 0.80
    return 0.65


def open_trades(trade_log: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        trade for trade in trade_log.get("trades", [])
        if trade.get("status") == "open"
    ]


def exposure_for(portfolio: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    return (portfolio.get("exposures_by_symbol") or {}).get(symbol)


def portfolio_context_available(portfolio: dict[str, Any]) -> bool:
    if not portfolio:
        return False
    flags = portfolio.get("flags") or []
    return not any(flag.get("kind") == "missing_csv" for flag in flags)


def score_candidate(
    candidate: dict[str, Any],
    trade_log: dict[str, Any],
    portfolio: dict[str, Any],
    catalyst: dict[str, Any] | None = None,
) -> CandidateDecision:
    prob = probability_safe(candidate)
    dte = int(candidate.get("dte") or 1)
    premium = float(candidate.get("premium_dollars") or 0)
    dollars_per_day = premium * prob / max(dte, 1)
    score = dollars_per_day
    penalties: list[str] = []
    blockers: list[str] = []
    notes: list[str] = []
    symbol = candidate.get("symbol", "")

    if not candidate.get("fits_cash", False):
        blockers.append("collateral does not fit free cash; swap math required")

    if any(trade.get("symbol") == symbol for trade in open_trades(trade_log)):
        blockers.append("already have an open 401k put on this underlying")

    exposure = exposure_for(portfolio, symbol)
    if exposure:
        # FYI-only (RULES.md §7): a note for the recap, never a score/gate effect.
        notes.append(
            f"FYI: already own ${exposure.get('market_value', 0):,.0f} of {symbol} across portfolio"
        )

    vrp = candidate.get("vrp")
    if vrp is not None and vrp <= 0:
        # Negative/zero VRP = implied vol at or below realized vol = no edge: you'd be
        # selling fairly-priced or cheap vol. Hard reject, matching the index_vrp
        # sleeve's MIN_VRP gate and the logged MU skip ("paid more but had no edge, IV
        # under realized"). A previous 0.70 score penalty let no-edge names still win
        # on a quiet day. VRP None (realized vol unavailable) is missing data, not
        # negative edge — left to scoring, not blocked.
        blockers.append(f"no variance-risk-premium edge (VRP {vrp:+g}; IV <= realized vol)")

    standing = candidate.get("standing_block")
    if standing:
        # csp_401k RULES.md §5a/§5b — an uncleared company-specific disqualifier, or a dated
        # share-supply event inside the contract. The screener writes this field; we re-block
        # here rather than importing its module (no cross-strategy imports) and rather than
        # trusting `actionable`, which this ranker deliberately does not read. Without this,
        # a screener-blocked candidate could still rank first on raw dollars per day.
        # Preserve the explicit block independently of the ranker's scoring inputs.
        blockers.append(f"standing risk: {standing}")
        notes.append(standing)

    if not portfolio_context_available(portfolio):
        score *= NO_CSV_PENALTY
        penalties.append("portfolio CSV context unavailable")

    if catalyst and catalyst.get("symbol") == symbol:
        verdict = catalyst.get("verdict")
        if verdict == "block":
            blockers.append("catalyst check blocked this candidate")
            notes.append(catalyst.get("summary", "catalyst check blocked"))
        elif verdict == "caution":
            score *= CATALYST_CAUTION_PENALTY
            penalties.append("catalyst caution")
            notes.append(catalyst.get("summary", "catalyst check requires review"))
        elif verdict == "clean":
            notes.append("catalyst check clean")

    return CandidateDecision(
        symbol=symbol,
        strike=float(candidate.get("strike") or 0),
        expiration=str(candidate.get("expiration") or ""),
        dte=dte,
        premium_dollars=premium,
        collateral=float(candidate.get("collateral") or 0),
        cushion_pct=float(candidate.get("cushion_pct") or 0),
        implied_move_pct=float(candidate.get("implied_move_pct") or 0),
        vrp=vrp,
        fits_cash=bool(candidate.get("fits_cash")),
        prob_safe=prob,
        dollars_per_day=round(dollars_per_day, 2),
        score=round(score, 2),
        penalties=penalties,
        blockers=blockers,
        notes=notes,
    )


def top_portfolio_flags(portfolio: dict[str, Any], limit: int = 2) -> list[dict[str, Any]]:
    flags = portfolio.get("flags") or []
    attention = [flag for flag in flags if flag.get("severity") == "attention"]
    warnings = [flag for flag in flags if flag.get("severity") == "warning"]
    infos = [flag for flag in flags if flag.get("severity") == "info"]
    return (attention or warnings or infos)[:limit]


def top_covered_call(covered_calls: dict[str, Any]) -> dict[str, Any] | None:
    if covered_calls.get("errors") or covered_calls.get("mode") != "live_chain":
        return None
    candidates = covered_calls.get("candidates") or []
    actionable = [candidate for candidate in candidates if candidate.get("actionable", True)]
    return (actionable or candidates or [None])[0]


def vol_regime_blocks(vol_regime: dict[str, Any] | None, now: datetime) -> bool:
    """True if a fresh vol-regime snapshot says backwardation — the fund-level
    short-premium stand-down (fund_rules.VIX_BACKWARDATION_RATIO). decide.py
    builds from last_screen.json directly, bypassing risk.evaluate, so without
    this check the Slack rec could contradict the morning brief. Missing or
    stale snapshot = regime unknown = no gate (fail open, same as risk.py)."""
    if not vol_regime or vol_regime.get("regime") != "backwardation":
        return False
    generated_at = naive_timestamp(vol_regime.get("generated_at"))
    if generated_at is None:
        return False
    return (now - generated_at) <= timedelta(hours=MAX_VOL_REGIME_AGE_HOURS)


def build_decision(
    screen: dict[str, Any],
    trade_log: dict[str, Any],
    portfolio: dict[str, Any],
    catalyst: dict[str, Any] | None = None,
    covered_calls: dict[str, Any] | None = None,
    now: datetime | None = None,
    vol_regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    open_positions = open_trades(trade_log)
    raw_candidates = screen.get("candidates", [])
    candidates = [
        score_candidate(
            candidate,
            trade_log,
            portfolio,
            candidate_catalyst
            if catalyst_applies(candidate_catalyst, candidate.get("symbol", ""), screen, now)
            else None,
        )
        for candidate in raw_candidates
        for candidate_catalyst in [catalyst_for_symbol(catalyst, candidate.get("symbol", ""))]
    ]
    if vol_regime_blocks(vol_regime, now):
        ratio = vol_regime.get("vix_term_ratio")
        for candidate in candidates:
            candidate.blockers.append(
                f"vol regime: VIX/VIX3M {ratio:.2f} = backwardation — no new short premium"
            )
    age = screen_age_hours(screen, now)
    screen_fresh = age is not None and age <= MAX_SCREEN_AGE_HOURS
    viable = [
        candidate for candidate in candidates
        if not candidate.blockers and candidate.score >= MIN_CANDIDATE_DOLLARS_PER_DAY
    ] if screen_fresh else []
    viable.sort(key=lambda c: c.score, reverse=True)
    flags = top_portfolio_flags(portfolio)
    covered_call = top_covered_call(covered_calls or {})

    caveats: list[str] = []
    if age is None:
        caveats.append("screener timestamp missing")
    elif age > MAX_SCREEN_AGE_HOURS:
        caveats.append(f"screener is {age:.1f} hours old")
    if not portfolio_context_available(portfolio):
        caveats.append("portfolio CSV context unavailable")
    if not raw_candidates:
        pass
    elif not any(
        catalyst_applies(
            catalyst_for_symbol(catalyst, candidate.get("symbol", "")),
            candidate.get("symbol", ""),
            screen,
            now,
        )
        for candidate in raw_candidates
    ):
        caveats.append("catalyst check pending")
    if (covered_calls or {}).get("errors"):
        caveats.append("covered call scan had errors")
    elif (covered_calls or {}).get("mode") and (covered_calls or {}).get("mode") != "live_chain":
        caveats.append("covered call live chain scan pending")
    if vol_regime_blocks(vol_regime, now):
        caveats.append("vol regime backwardation — new short premium stood down")

    if viable:
        pick = viable[0]
        action = "CHECK_CANDIDATE"
        text = (
            f"Morning decision: check {pick.symbol} ${pick.strike:.0f} put first "
            f"(${pick.dollars_per_day:.2f}/day expected, {pick.cushion_pct:.0f}% cushion); "
            "trade only if catalyst check is clean"
        )
        if pick.notes:
            text += f"; context: {pick.notes[0]}"
    elif covered_call:
        action = "CHECK_COVERED_CALL"
        holding_note = ""
        if open_positions:
            symbols = ", ".join(sorted({trade.get("symbol", "?") for trade in open_positions}))
            holding_note = f"; keep holding open put(s) on {symbols}"
        text = (
            f"Morning decision: no clean 401k put; check covered call on {covered_call['symbol']} "
            f"${covered_call['strike']:.0f} call ({covered_call['contracts']} contract, "
            f"${covered_call['premium_dollars']:.0f}, {covered_call['otm_pct']:.0f}% above spot)"
            f"{holding_note}"
        )
    elif open_positions:
        action = "HOLD"
        symbols = ", ".join(sorted({trade.get("symbol", "?") for trade in open_positions}))
        blocked = next((c for c in candidates if c.blockers), None)
        reason = f"; best blocked candidate: {blocked.symbol} ({', '.join(blocked.blockers)})" if blocked else ""
        text = f"Morning decision: hold open 401k put(s) on {symbols}; no clean candidate beat the gates{reason}"
    elif flags:
        action = "PORTFOLIO_REVIEW"
        text = f"Morning decision: no clean 401k put; review portfolio flag: {flags[0]['message']}"
    else:
        action = "NO_ACTION"
        text = "Morning decision: no clean 401k put and no material portfolio flag"

    decision = {
        "generated_at": now.isoformat(timespec="seconds"),
        "screen_timestamp": screen.get("timestamp"),
        "action": action,
        "summary": text,
        "caveats": caveats,
        "open_positions": open_positions,
        "candidate_count": len(candidates),
        "viable_candidate_count": len(viable),
        "best_candidate": asdict(viable[0]) if viable else None,
        "candidates": [asdict(candidate) for candidate in candidates],
        "portfolio_flags": flags,
        "catalyst_check": catalyst or {},
        "covered_call_candidate": covered_call,
    }
    return decision


def write_decision(decision: dict[str, Any], state_dir: Path = STATE_DIR) -> dict[str, Any]:
    state_dir.mkdir(exist_ok=True)
    json_path = state_dir / "morning_decision.json"
    text_path = state_dir / "morning_decision.txt"
    decision["output_files"] = {
        "json": display_path(json_path),
        "text": display_path(text_path),
    }
    json_path.write_text(json.dumps(decision, indent=2, default=str))
    text_path.write_text(decision["summary"] + "\n")
    return decision


def run(
    screen_path: Path = LAST_SCREEN,
    trade_log_path: Path = TRADE_LOG,
    portfolio_path: Path = PORTFOLIO_LATEST,
    catalyst_path: Path = CATALYST_LATEST,
    covered_calls_path: Path = COVERED_CALLS,
    state_dir: Path = STATE_DIR,
) -> dict[str, Any]:
    decision = build_decision(
        screen := load_json(screen_path, {}),
        load_json(trade_log_path, {"trades": []}),
        load_json(portfolio_path, {}),
        load_catalyst_state(screen, catalyst_path, catalyst_path.parent),
        load_json(covered_calls_path, {}),
        vol_regime=load_json(VOL_REGIME, {}),
    )
    return write_decision(decision, state_dir=state_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    decision = run()
    print(decision["summary"])
    print(f"Wrote {decision['output_files']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
