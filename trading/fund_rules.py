"""
fund_rules.py — THE canonical fund-level numbers. Single source of truth.

Reasoning + citations for every value live in FUND.md (repo root). This file holds
only the numbers, so code never hardcodes a threshold. Each sleeve keeps its OWN
strategy-specific numbers in its own rules.py (e.g. strategies/csp_401k/rules.py);
this file is for FUND-WIDE risk/sizing/exposure policy only. Do not duplicate sleeve
numbers here, and do not put fund numbers in a sleeve file.

These are chosen, evidence-informed POLICY values (FUND.md §4), not optimized
constants. Change a number here and the whole book's risk policy changes at once.
"""

# ======================================================================
# ENFORCED — read by risk.py / fund_engine.py on every candidate.
# ======================================================================

# --- Concentration / correlation (FUND.md §4) ---
# Single-name is a FLAG, not a hard block: the csp_401k mandate explicitly allows one
# high-conviction position to use most of the deployable cash ("sometimes one contract
# is the most this account can do") — see strategies/csp_401k/RULES.md. The hard
# single-name rules are: 1 short put per underlying + cash fit + the defense buffer
# below. We only WARN when a new name would exceed this share of active capital.
SINGLE_NAME_FLAG_PCT = 35.0     # warn (don't reject) above this % of ACTIVE capital
MAX_BUCKET_PCT = 50.0           # HARD cap: one correlation bucket can't exceed this % of
                                # active capital — this is the real diversification teeth
DEFENSE_CASH_BUFFER_PCT = 20.0  # keep this % of free cash undeployed to defend open
                                # positions; a new trade can't consume past it
CATALYST_BENCHMARK = "QQQ"      # market proxy for separating beta from idiosyncratic moves
CATALYST_IDIO_PCT = -4.0        # adverse catalyst only if a name falls this much MORE than
                                # the market today (idiosyncratic) — a broad-beta selloff,
                                # when premium is richest, is NOT a catalyst
VRP_THIN_EDGE = 3.0             # VRP at/below this = flag "thin edge, size small or skip"

# --- Vol-regime gate (FUND.md §2C/§4) — enforced by risk.py on short-premium trades ---
# All short-vol sleeves are ONE correlated bet; this is the regime switch. VIX/VIX3M
# < 1 = contango (the normal state, ~80% of days — when IV most reliably overstates
# realized vol and short premium has its edge); >= 1 = backwardation (near-term fear
# repricing — the environment where short-vol losses cluster). In backwardation we
# stand down on NEW short premium; existing positions are managed, not auto-closed.
# Quote symbols verified against Schwab 2026-06-10 ($VIX / $VIX3M as INDEX quotes).
VIX_SYMBOL = "$VIX"
VIX3M_SYMBOL = "$VIX3M"
VIX_BACKWARDATION_RATIO = 1.0   # VIX/VIX3M at/above this = backwardation -> no new short premium
# Correlated names count as ONE bet (e.g. semis, crypto-beta). The bucket cap groups
# these before sizing.
CORRELATION_BUCKETS = {
    "semis": ["NVDA", "AMD", "MU", "TSM", "ASML", "MRVL", "ARM", "SMCI", "ON", "LRCX"],
    "crypto_beta": ["MSTR", "COIN", "IBIT", "MARA", "RIOT"],
    "megacap_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NFLX"],
}

# --- Per-trade risk (FUND.md §4) — enforced by risk.py on defined-risk trades ---
KELLY_FRACTION = 0.25           # fractional-Kelly basis for the per-trade cap below
PER_TRADE_RISK_PCT = 3.0        # a NON-spread defined-risk trade's max loss can't exceed this
                                # % of book. 3% on a small account = "no single trade craters
                                # it" (cash + concentration are the real binding constraints).
DEFINED_RISK_PER_TRADE_PCT = 6.0  # per-trade max-loss cap for put_spread only. Matches the
                                # backtested weekly ladder rung (~$10k width entries on the
                                # 2026-08-24 SPY spread backtest, strategies/index_vrp/
                                # backtest.py). Judgment dial on top of modeled evidence —
                                # MEDIUM confidence.
MAX_CONCURRENT_POSITIONS = 2    # max simultaneous open CASH-SECURED-PUT positions. A count
                                # cap is really a committed-cash proxy sized for CSPs
                                # ($30-60k collateral each ≈ the whole cash sleeve at 2).
                                # Defined-risk spreads are NOT counted here — they commit
                                # ~$3-5k each and are capped in dollars instead (below).
                                # (2026-08-24: was fund-wide; scoped to CSPs when the spread
                                # deployment cap landed.)

# --- Defined-risk (put_spread) deployment (FUND.md §4) — enforced by risk.py ---
# Replaces the count cap for spreads: the binding limit is TOTAL OPEN SPREAD WIDTH in
# dollars — the max simultaneous loss if every open spread maxes out in one crash month.
# $80k = the backtest's full-size config (~$37.8k/yr modeled, worst month -$42k, worst
# year -$39k, every 2008-2024 start year ends profitable — strategies/index_vrp/
# backtest.py + experiments.py, skew-swept). This is a reference research allocation,
# not an inferred account-specific risk tolerance. MEDIUM confidence (modeled
# prices); the structure (cap dollars, not count) is the point.
SPREAD_DEPLOYMENT_CAP_DOLLARS = 80_000
SPREAD_LADDER_RUNGS = 8         # weekly entries add at most cap/rungs (~$10k) of width at
                                # a time, so expiries stagger instead of stacking into one
                                # week. 8 rungs (not the backtest's 4) keeps the per-entry
                                # rung at ~$10k so each entry still fits the 6% defined-
                                # risk per-trade cap; steady-state deployment, which is
                                # what the backtest actually measured, is unchanged.

# --- Drawdown brake (FUND.md §4) — enforced by fund_engine via state/book_history.jsonl ---
DEGROSS_LEVELS = [              # cut gross exposure in thirds as book drawdown deepens
    (10.0, 1 / 3), (15.0, 2 / 3), (20.0, 1.0),
]

# --- Event calendar (FUND.md §2D) — awareness line in the brief, NOT a gate ---
# Pre-FOMC announcement drift: equities accrue positive excess return in the ~24h
# before scheduled FOMC announcements (Lucca & Moench 2015, NY Fed SR512; still
# positive through Dec 2024 and concentrated in press-conference meetings — all 8
# scheduled 2026 meetings have one). Announcement days (day 2 of each meeting),
# from the federalreserve.gov FOMC calendar:
FOMC_DATES_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
                   "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
FOMC_AWARENESS_DAYS = 3         # show the brief line when an announcement is this close
                                # (display window only — no rule hangs off it)
# Index-VRP blackout: index put spreads are undiversified bets on the broad market, and a
# scheduled FOMC announcement is the single biggest macro move they're exposed to. Inside
# this window the index-VRP sleeve opens NO new short premium. Scope: index sleeve ONLY.
# Single-name CSPs keep FOMC as awareness-only (deep cushion + idiosyncratic risk absorbs
# it — FUND.md §2D); the index sleeve has neither, so it gets a real gate. This is the gate
# that stops a thin-cushion index spread from surfacing the day before the Fed.
FOMC_BLACKOUT_DAYS = 1          # index-VRP only: no new spreads within this many days of FOMC

# --- Idle-cash yield (csp_401k RULES.md §3 has the sources) ---
# Account-wide fact: uninvested cash in any Schwab account sits in the standard Bank
# Sweep at 0.01% APY — effectively zero. Cash earns ~3.5% ONLY when deliberately
# parked in SWVXX. Never assume a "~4% money market" floor for idle cash.
IDLE_CASH_APY = 0.0001          # Schwab Bank Sweep APY, 2026-06
SWVXX_APY = 0.035               # SWVXX 7-day yield, 2026-06

# --- Grading (FUND.md §6) — enforced by grade.py / fund_engine ---
MIN_TRADES_FOR_EDGE = 100       # closed trades before a sleeve's measured edge is trusted
SLEEVE_KILL_EXPECTANCY = 0.0    # sleeve flagged KILL if rolling expectancy <= this

# --- Risk dial (FUND.md §4) — the book's posture knob, enforced by judge.py ---
# ONE setting that says how much cushion + edge the book demands before a short-premium
# trade may surface. The sleeve scanners don't change; the dial sets fund-wide FLOORS the
# judge applies on top of them, so the same 30-delta index spread surfaces when aggressive
# and is killed when defensive. The current setting + the account owner's outlook live in
# state/risk_posture.json (data, editable without a code change); this is the level->numbers
# map and the fallback. min_cushion_pct = short strike must sit at least this far OTM;
# min_vrp = required variance-risk premium (IV - realized vol) in vol points.
# min_cushion_pct governs naked/undefined short premium. min_cushion_pct_defined is the
# separate floor for DEFINED-RISK spreads: a ~30-delta index spread has 3-4% cushion BY
# CONSTRUCTION (the BXMD sweet spot — FUND.md §4), so holding it to the naked-put floor
# was a structural ban, not a filter (two weeks of 35 judge-kills, 2026-08-10..24, while
# the shadow record ran 66/66). The wing caps the tail the cushion floor exists to guard,
# so the defined floor is lower on purpose; defensive still effectively shuts the sleeve.
RISK_DIALS = {
    "aggressive": {"min_cushion_pct": 3.0, "min_cushion_pct_defined": 2.5, "min_vrp": 0.0},
    "neutral":    {"min_cushion_pct": 5.0, "min_cushion_pct_defined": 3.0, "min_vrp": 2.0},
    "defensive":  {"min_cushion_pct": 7.0, "min_cushion_pct_defined": 5.0, "min_vrp": 3.0},
}
DEFAULT_DIAL = "defensive"      # fallback when state/risk_posture.json is missing/unreadable
# A trade whose cushion clears the floor but only by this margin is FLAGGED (surfaced with a
# thin-cushion warning), not killed — so a borderline trade reaches the account owner labeled, not hidden.
DIAL_FLAG_MARGIN_PCT = 1.5

# --- Sleeve status ladder (FUND.md §6) — enforced by fund_engine via slack_format ---
# Professional practice is prove-BEFORE-promote: backtest -> paper/forward-test -> live.
# >90% of backtested strategies fail live (López de Prado; Peterson), so a sleeve is NOT
# actionable until its forward record earns it. "paper" sleeves still scan + shadow-track
# and render in the PAPER section, but never as a NEW (actionable) trade. Promote by
# editing this map only after grade.scorecard() reports the sleeve "trusted"
# (>= MIN_TRADES_FOR_EDGE forward closes AND positive expectancy). Defaults reflect real
# evidence: short-vol core is backtested/cited; the directional sleeves use proxy signals
# with no in-system out-of-sample validation yet.
SLEEVE_STATUS = {
    "cash_secured_put": "live",   # tastytrade triad, ~15yr backtest incl. 2020/2022
    "put_spread":       "live",   # index VRP — Cboe PUT Sharpe 0.65
    "covered_call":     "live",   # BXM
    "pead":             "paper",  # entry signal is an admitted proxy (EPS% != SUE deciles)
    "trend":            "paper",  # unvalidated in-system
    "factor":           "paper",  # unvalidated in-system
}


def sleeve_is_live(strategy):
    return SLEEVE_STATUS.get(strategy, "paper") == "live"  # default-deny: unknown == paper


# Net-long/gross caps, sleeve vol-targeting, and rebalance bands are documented in
# FUND.md §4 as FUTURE controls — they need delta tracking / vol estimation / the ETF
# rebalancer, which aren't built yet. Deliberately not kept here as dead config.
