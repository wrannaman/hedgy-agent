"""
csp_401k — THE canonical rule parameters. SINGLE SOURCE OF TRUTH for every number.

There are exactly two canonical rule files in this strategy and they describe
different layers, so they cannot contradict:
  - rules.py  (this file) — the NUMBERS. Every script imports its thresholds here.
  - RULES.md              — the REASONING + citations for those numbers.

Every other file (CLAUDE.md, POSITIONS.md, CRON_PROMPT.md, README.md) must POINT to
RULES.md and restate NO rules of its own. Never hardcode a rule threshold anywhere
but here. Change a number here and the whole system changes at once.

No file may deviate from these values. (The variants/ paper-trading sandbox was the
one sanctioned exception; retired 2026-07-23 — RULES.md §12.)
"""

# --- Entry / screener gates (RULES.md §1–2) ---
DTE_MIN, DTE_MAX = 28, 45      # days-to-expiration window at entry; lean 45
MIN_CUSHION_PCT = 10.0         # strike must sit at least this far below spot (floor)
MIN_PREMIUM_PCT = 2.0          # premium must be >= this % of the cash frozen
MAX_SPREAD_PCT = 15.0          # skip puts with bid/ask spread wider than this (illiquid)

# Strike depth, in the unit the rule is actually WRITTEN in. RULES.md §2: "~16-delta is the
# canonical '1 SD OTM' anchor (~84% chance of expiring OTM); use as a sanity check on the
# screener's strike" (tastytrade, STRONG). This gate now IS that check.
#
# REPLACES EXPECTED_MOVE_MULT = 1.0 (removed 2026-07-13), which required
#     cushion >= IV * sqrt(DTE/365)
# — a LINEAR price drop standing in for a 1-standard-deviation move. A 1-SD move is
# lognormal, not linear, so the linear form over-deepens the strike, and the error GROWS
# with IV. Measured on the live chain:
#     IV  20 -> gate lands on a 0.13-delta strike   (close enough to the 0.16 target)
#     IV  60 -> 0.11 delta
#     IV 120 -> 0.07 delta                          (less than half as deep as intended)
# So the gate quietly stopped implementing its own documented rule exactly on the high-IV
# names this universe exists to harvest: those strikes are so deep they no longer pay
# MIN_PREMIUM_PCT, nothing clears, and the name vanishes with no log line. On 2026-07-13
# that silently deleted 54 of 169 names — the median one a 0.25-delta put paying 4.88%.
# Selecting on delta directly restores the intended depth (median premium at the 16-delta
# strike: 2.83%, median cushion 19%) and adds no model assumption: delta is quoted in the
# chain and we already read it (and already reject Schwab's -999 sentinel).
#
# The 2026-07-14 version of this comment claimed "a bug fix, not a loosening." That was
# wrong in effect, and 2026-07-22 is the correction. The claim assumed MAX_DELTA acts as a
# CEILING. It does not — it acts as the TARGET, because of how the strike is chosen:
# screener_select.best_put_from_chain returns "highest premium-as-%-of-collateral among puts
# that clear every gate", and premium-% rises monotonically toward the money. The argmax
# therefore lands on the shallowest strike that survives this number, every time. Whatever
# value sits here IS the delta we sell.
#
# Set the selected-delta target intentionally; maximizing premium does not add a
# separate preference for deeper strikes. The 0.12 reference follows Tom Sosnoff's
# published short-put setup: sell the 12-delta put around 45 DTE and manage at 50%
# of maximum credit. Its single-name application still requires ongoing evaluation.
#
# The 0.16 / 1-SD anchor still stands as the general tastytrade strangle guidance (RULES.md
# §2) — the point is that 0.16 is a different rule for a different thing (a diversified,
# many-position premium book), and this is a 1-2 position book where one assignment is 8-15%
# of capital. Confidence: MEDIUM-HIGH — 12-delta is now a citation for precisely this trade
# rather than a preference, but the single-name application is ours. Revisit at >=20 closes.
MAX_DELTA = 0.12

# Variance-risk-premium floor — the EDGE gate (RULES.md §1). VRP = underlying IV − 30d
# realized vol. We only have an edge when options price MORE vol than the stock has been
# realizing (IV > RV); below that we'd be selling fairly-priced or underpriced vol and
# collecting raw premium with no edge — paid too little for the non-steady-state tail.
# This is the ABSOLUTE floor: a candidate at or below it is never actionable, however fat
# the premium. The risk dial (fund_rules / risk_posture) may demand MORE positive VRP in a
# defensive regime — it can only TIGHTEN this floor, never loosen it below 0.
MIN_VRP = 0.0

# ACTIONABLE floor — the "surface this as a TRADE" bar (RULES.md §1a). MIN_VRP > 0 means the
# candidate has *some* edge and is worth LOGGING/observing; it does NOT mean the edge is big
# enough to act on. Single-name VRP is thin and often barely positive (RULES.md §0), so a
# candidate that merely clears zero is WATCH, not ACT: it gets ranked and tracked, but the
# morning brief does not put it in front of the account owner as a trade. A fresh put only surfaces as
# actionable when VRP clears THIS floor (options genuinely rich, not marginally so) OR it is
# an earnings-premium harvest with a deep cushion (the one real single-name edge, §0).
# This is the number that stops thin +5-to-+10 VRP names (e.g. INTC +9.6 on a calm day) from
# being surfaced as "sell this now" with confident copy. Judgment dial, NOT backtested —
# tune to alert appetite: raise it for fewer/richer alerts, lower it for more. The risk dial
# may demand MORE (it can only TIGHTEN, never drop below MIN_VRP). Confidence: MEDIUM.
ACTIONABLE_VRP = 15.0

# ...AND the same gap as a PROPORTION (RULES.md §1a). A flat point floor is easier for violent
# names to clear on noise: 15 points on a 90-vol name is only 1.17x rich, while on a 25-vol
# name it's 1.6x — so points-alone tilts the screen toward the most dangerous underlyings
# (exactly the INTC trap: RV 83, everything about it is big in point terms). Actionable
# requires BOTH: vrp >= ACTIONABLE_VRP and iv/rv >= this ratio. 1.2x is the commonly-cited
# "rich" line in the IV-vs-RV literature. Same MEDIUM-confidence dial as the points floor.
ACTIONABLE_VRP_RATIO = 1.2

# No-chase guard (RULES.md §1: "sell on red days, not green" — now enforced, 2026-07-01).
# Initiating after a sharp up-move sells insurance right after it deflated. "Sharp" is scaled
# to the name's own vol, not a flat %: a day move above this many daily sigmas (RV/sqrt(252))
# demotes ACT -> WATCH for the day; the name re-surfaces on the next non-chasing screen.
# Grounded in the §1 red-day mechanism (MODERATE); the 1.0 sigma line is a judgment dial.
NO_CHASE_SIGMA = 1.0

# DISCUSS tier — surface (don't recommend) a beaten-down name for a human look (RULES.md §1b).
# A high-IV name near its 52-week low gets structurally squeezed OUT of the screen: its large
# implied move forces the strike deep (past the expected-move cushion), and that deep it no
# longer pays MIN_PREMIUM_PCT — so nothing clears and the name vanishes silently. That is
# exactly the "sell into fear on a quality name" setup the account owner wants to SEE and talk through
# before deciding. So: when a name trades within this band of its 52-week low AND offers a
# put that clears the FLAT MIN_CUSHION_PCT floor + premium + liquidity (but fails the
# expected-move cushion), surface it tagged `discuss` — visible, never `actionable`, never an
# auto-ACT. It's a conversation starter, not a screened trade. Judgment dial. Confidence: LOW
# (this is a display heuristic, not an edge claim — the trade itself is shallow by design).
NEAR_52W_LOW_BAND_PCT = 12.0

# --- Trade management: the canonical tastytrade triad (RULES.md §3) ---
# Three backtested rules, nothing invented. Source: tastytrade mechanical studies
# (SPY/QQQ short premium, ~15 yrs incl. 2020 crash + 2022 bear, managed at "50% profit
# OR 21 DTE, whichever first", 2x-credit stop). These are the simple, pre-tested rules;
# we do not add velocity/near-max/redeploy logic on top.
#
# REMOVED 2026-06-18: NEAR_MAX_CAPTURE_PCT (75 — borrowed from an Option Alpha
# defined-risk-spread study optimizing Sharpe, wrong context for our CSPs),
# FAST_CAPTURE_*, PROFIT_VELOCITY_*, OPPORTUNITY_EXIT_BEAT_RATIO (all invented here).
# Multiple overlapping thresholds can create contradictory verdicts; keep one target, timer, and stop.
PROFIT_TARGET_PCT = 50         # close at >= this % of max credit — the primary exit
MANAGE_DTE = 21                # at/inside this DTE: close a winner (gamma) — see MANAGE_DTE_CUTS_LOSERS
STOP_MULTIPLE = 2.0            # put value >= this x credit -> cut the loser (mechanical)
STRIKE_PROXIMITY_PCT = 5.0     # stock within this % of strike -> risk exit (assignment near)

# Wording-only dial for the fill-odds sentence (RULES.md §3, added 2026-08-03). A close is a
# LIMIT worked over a session, not a market order at the instantaneous ask, so decision.py
# always states the limit to place AND the modelled odds it trades there before the bell.
# Above this number the copy says "worth resting"; below it, "rest it anyway if you want the
# fill, it costs nothing." It NEVER suppresses the alert and never changes a verdict —
# resting an unfilled limit costs nothing, so there is no threshold at which staying silent
# is right. State an eligible target and its estimated fill odds rather than
# suppressing the opportunity based on one instantaneous quote. Judgment dial,
# LOW confidence, display only.
FILL_ODDS_WORKABLE_PCT = 25.0

# --- 2x-stop conditioning (RULES.md §4; added 2026-07-07 from the deep-research review) ---
# The mark-based stop is the only exit that fires off a QUOTE rather than the underlying,
# and deep-OTM put mids are exactly where quotes lie: in the 5 Aug 2024 VIX spike, deep-OTM
# put bid-ask spreads hit >80% of mid vs ~25% normal, mechanically inflating marks (BIS
# Bulletin 95). So a 2x mark must PERSIST across this many consecutive monitor runs
# (~3-4h apart, 3 runs/day) before the verdict is CUT; the first sighting surfaces as an
# alerted STOP-PENDING hold. Strike-proximity and bad-news exits are unaffected — they
# read the underlying, not the quote. Direction HIGH (verified 3-0); the 2 is a judgment
# dial (same-day confirmation). The backtest sweep is exempt via getattr default 1: its
# Black-Scholes marks are model prices with no quote artifacts to guard against.
STOP_CONFIRM_RUNS = 2

# ...and the stop is regime-conditional on the VIX AT ENTRY (RULES.md §4). In the
# 41,600-trade Project Finance short-put study, loss-taking stops improved P/L and
# drawdowns ONLY for positions entered in high-VIX regimes; in low-VIX entries the
# passive (no-stop) approaches had the most edge — a fixed stop there cuts trades that
# mean-revert. Entry VIX >= this line -> stop active (CUT on confirmation); below it the
# 2x mark surfaces as an alerted advisory HOLD and the close is a logged judgment call.
# Unknown entry VIX (legacy trades, backtest) counts as HIGH -> stop active (conservative).
# Direction HIGH (verified 3-0); the 20.0 line is a judgment dial (matches pretrade.py's
# "moderate fear" tier, not a backtested constant).
STOP_HIGH_VIX_ENTRY = 20.0

# At the 21-DTE timer, CLOSE a winner — but do NOT cut a loser on the clock alone.
# Changed 2026-06-29 (was effectively True). A position still open at the timer that is
# *down* has, by construction, already cleared the 2x-credit stop and the strike-proximity
# gate above it — so it is far OTM and "down" only on IV markup, not assignment risk.
# Cutting it realizes a loss at elevated IV on a bet whose strike isn't threatened. Time is
# not a risk signal; the stop, proximity, and bad-news exits (RULES.md §4) are. So it holds
# to expiry. Resolves the §3-timer-vs-§4 conflict toward §4's published evidence (fixed
# stops were the *worst* outcome in the 41,600-trade short-put study). Literature-backed
# (§4, HIGH); modeled backtest inconclusive (RULES.md §12). See RULES.md §3.
MANAGE_DTE_CUTS_LOSERS = False

# --- Opportunity-cost surfacing (RULES.md §3, §6) ---
# A HELD position's collateral has a "better home" only if the day's screener offers a
# materially better, positive-edge trade that fits the cash the hold would free. monitor.py
# SURFACES that comparison as an advisory note when a candidate's annualized premium yield
# beats the hold's by at least this ratio; it does NOT close anything — the close stays a
# logged judgment call. This is NOT the invented OPPORTUNITY_EXIT_BEAT_RATIO removed
# 2026-06-18: that one auto-decided CLOSE/HOLD in code off a made-up number. This is a
# surfacing knob (cf. the covered-call eligibility-vs-verdict split, §11) — heuristic and
# tunable to churn appetite, NOT a backtested edge. Raise it to surface fewer redeploys.
REDEPLOY_BEAT_RATIO = 1.5

# --- Sizing / circuit breaker (RULES.md §7–8) ---
# Size on assignment exposure rather than a fixed contract count. A contract's
# cash-secured exposure depends on strike x 100, so a count-only rule produces
# materially different allocations across underlyings. Keep duplicate-position
# protection separate from the sizing policy.
#
# Every approved trade uses the whole deployable 401k cash balance, rounded down to
# whole cash-secured contracts. The strategy is intentionally selective; a rare
# approved trade must be meaningful rather than a token allocation.
POSITION_TARGET_PCT = 100.0

# Correlated-group cap: total assignment exposure of the OPEN PUTS in one correlation
# group (crypto-beta: MARA/COIN/MSTR puts; semis: NVDA/AMD/MU/...) must stay under
# this % of the book. Counts only positions this bot originates. Shares held in the
# account (IBIT, COIN stock, ...) are FYI-only, same as cross-account holdings —
# the account owner owns portfolio-level risk, the bot caps only what it puts on (§7,
# 2026-07-14; shares counted against the cap 2026-07-07→2026-07-14 only). Enforced
# by the judgment layer, which sees the open puts. Judgment dial, MEDIUM.
# A fully sized position leaves no capital for a second put. Keep the group check as
# a structural guard for partial/future states, but do not contradict the full-cash
# sizing mandate for the first position.
CORR_GROUP_CAP_PCT = 100.0

# One POSITION per underlying (the real meaning of the old CONTRACTS_PER_UNDERLYING=1):
# never a second entry / never averaging down on the same name. Contract count within
# that one position comes from position_contracts().
MAX_POSITIONS_PER_UNDERLYING = 1

# Kept for the backtest sweep's RuleSet (engine sizes 1 contract per entry — its
# bankroll model predates position sizing). Live code must use position_contracts().
CONTRACTS_PER_UNDERLYING = 1

MAX_CONSECUTIVE_LOSSES = 3


def position_contracts(strike, book_cash):
    """Contracts for a new position: all deployable cash, floor 1.

    Sizes on assignment exposure (strike x 100 per contract). Caller still owns the
    fits-cash check (contracts x strike x 100 <= free cash) and the correlated-group
    cap (CORR_GROUP_CAP_PCT — needs live holdings). book_cash = the account's
    deployable premium-selling capital (cash balance, pre-lock), not net worth.
    """
    if not strike or strike <= 0 or not book_cash or book_cash <= 0:
        return 1
    target = book_cash * POSITION_TARGET_PCT / 100
    return max(1, int(target // (strike * 100)))

# --- Covered calls (the overwrite sub-sleeve) ---
# Entry window reuses DTE_MIN/DTE_MAX above. Call options on owned ETFs/shares run
# thinner than the CSP names, so the liquidity gate is wider than the put screener's.
# These three are ELIGIBILITY gates — cheap pre-filters that say "this contract is
# tradeable," not "this trade is worth doing."
CC_MIN_OTM_PCT = 15.0
CC_MAX_SPREAD_PCT = 25.0
CC_MIN_PREMIUM_DOLLARS = 25.0           # absolute floor; a pre-filter, NOT the verdict

# The VERDICT gate (RULES.md §11). Eligibility ≠ actionable. A covered call only earns
# a SELL if its premium, annualized over the capital it caps, clears this floor;
# otherwise the verdict is SKIP and we hold the shares uncapped. This is what stops
# the scanner from surfacing "check IBIT" — a thin overwrite on a convex hold — as if
# it were a decision. Heuristic (not backtested like the CSP triad); tune to your
# overwrite appetite. Raise it to cap less; lower it to cap more.
CC_MIN_ANNUALIZED_PCT = 20.0

# --- The wheel (RULES.md §13) ---
# An assignment starts a tracked CYCLE (wheel.py: put -> shares -> calls -> cash, one
# P&L), not a standalone bag. The one hard rule is structural, so no numeric knob lives
# here: NEVER sell a call struck below the cycle's cost basis (strike − credit/share).
# Enforced in covered_calls.best_call via wheel.min_call_strikes() and again in
# wheel.record_call. Everything else about wheel calls reuses the CC_* gates above —
# the wheel adds no loosening, only the basis floor and the cycle bookkeeping.

# --- Idle-cash floor (RULES.md §3) ---
# Account-wide fact, so the numbers live in fund_rules.py (re-exported here so this
# file stays the one import for every csp_401k script). The 401k's uninvested cash
# sits in Schwab's standard Bank Sweep — effectively zero, NOT "~4% money market".
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from fund_rules import IDLE_CASH_APY, SWVXX_APY  # noqa: E402

# --- Earnings (RULES.md §0, §5) ---
# Earnings is NOT a disqualifier and NOT a reason to close early. A strike outside the
# implied move over the contract's life — enforced by MAX_DELTA above, NOT by a cushion
# gate (that one was deleted 2026-07-13; the RULES.md §5 text still cited it until
# 2026-08-03) — harvests the IV-crush event premium, the one documented single-name edge.
# No numeric knob; the rule lives in the delta gate + judgment layer.
#
# --- Standing risk: supply events + disqualifiers (RULES.md §5a, §5b) ---
# Also no numeric knob, and deliberately so — these are per-symbol FACTS, not thresholds,
# so they live as data in `standing_risk.json` and as code in `standing_risk.py`, which
# screener.py calls. Two rules, one shared reason (an agent re-deciding a durable fact
# every morning drifts):
#   §5a a dated share-supply event (IPO lockup, secondary, index deletion) inside the
#       contract blocks ACT — unlike earnings there is no IV crush to harvest, so the
#       exposure is uncompensated.
#   §5b a confirmed company-specific disqualifier holds until its pre-written
#       `clears_when` bar is met AND the account owner sets `cleared`. The agent may open one; it
#       may never close one.
