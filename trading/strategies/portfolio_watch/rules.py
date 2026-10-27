"""
rules.py — the numbers for the tax-aware rebalancer (portfolio_watch sleeve).

Strategy-specific policy, kept here so code never hardcodes a threshold (DRY; the
fund-wide risk numbers live in fund_rules.py — this file is ONLY the rebalance/tax
knobs). Reasoning below each value; change a number here and the planner changes.

Tax note: these are CHOSEN, documented assumptions for a high-income California filer,
not tax advice and not pulled from a return. Every rate is overridable from the CLI
(--ca-rate, --fed-rate) so a different year/bracket doesn't require an edit here.
"""

# --- Account tax treatment (source: repo CLAUDE.md "Account map") -------------
# Selling INSIDE a sheltered account triggers no current tax; selling in a taxable
# account does. "spendable" = proceeds you can actually use now; sheltered proceeds
# are in-account dry powder only (rebalance/buy-the-dip without a withdrawal).
TAXABLE = "taxable"
TAX_DEFERRED = "tax_deferred"  # traditional 401k — no tax on sale, taxed at withdrawal
TAX_FREE = "tax_free"          # Roth — never taxed

from shared.config import load_accounts

_ACCOUNTS = load_accounts()
ACCOUNT_TAX_TREATMENT = {key: value["tax_treatment"] for key, value in _ACCOUNTS.items()}
SPENDABLE_TREATMENTS = {TAXABLE}  # proceeds usable outside the account

# --- All-in marginal rate on a realized LONG-TERM gain ------------------------
# Federal LTCG 20% (top bracket) + NIIT 3.8% + California, which taxes capital gains
# as ORDINARY income (no LT preference) — high-bracket CA marginal ~11.3%. Sum ~35.1%.
# We assume every lot is long-term: all holdings here show multi-year, multi-hundred-%
# gains. Short-term lots would be taxed far higher (fed ordinary up to 37%); if any
# exist, pass them via --short-term and we apply SHORT_TERM_FED_RATE instead.
FED_LTCG_RATE = 0.20
NIIT_RATE = 0.038
CA_RATE = 0.113
SHORT_TERM_FED_RATE = 0.37  # used only for symbols explicitly flagged short-term

# --- Cash-raise planner -------------------------------------------------------
DEFAULT_CASH_TARGET = 50_000   # default taxable spendable cash to raise when no --target
MIN_TRIM_DOLLARS = 2_000       # don't propose trims smaller than this (avoid dust/fees)

# --- User-defined portfolio buckets ------------------------------------------
# Multiple accounts may share one bucket (for example, two taxable brokerages).
ACCOUNT_BUCKET = {key: value["bucket"] for key, value in _ACCOUNTS.items()}
BUCKET_LABEL = {bucket: bucket for bucket in ACCOUNT_BUCKET.values()}
BUCKET_LABEL.setdefault("taxable", "taxable book")

# --- Trailing-stop trigger (the "tax-aware stop loss") ------------------------
# A concentrated winner that has fallen this far from its rolling high (tracked in
# state/trailing_highs.json across runs) escalates from "eligible" to "trim now".
# It's a FLAG, never an auto-order — this repo never trades without confirmation.
TRAILING_STOP_PCT = 15.0
# A name is "concentrated" (and thus stop-eligible) above either threshold. Both are
# measured against a BUCKET or the whole book — never a single account.
CONCENTRATION_BUCKET_PCT = 12.0     # % of its bucket (e.g. the combined taxable book)
CONCENTRATION_PORTFOLIO_PCT = 8.0   # % of the WHOLE book across all accounts


def all_in_lt_rate(ca_rate: float = CA_RATE, fed_rate: float = FED_LTCG_RATE) -> float:
    """Combined marginal rate applied to a realized long-term gain."""
    return fed_rate + NIIT_RATE + ca_rate
