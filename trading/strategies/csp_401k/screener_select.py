"""Pure put-selection logic for the screener — no client, no network, no schwab.

Split out from screener.py so it is unit-testable and so the Schwab greek-sentinel
filter has one clear home. screener.py does the I/O (fetch chain, fetch realized
vol) and delegates the actual "which put is best" decision here.

Why this module exists at all: on 2026-06-08 the screener surfaced a DVN $34 put as
"best of 159" paying a $342 (10%) premium. The real market for that put was ~$0.04
(bid 0.01 / ask 0.25). Schwab had returned its **-999 "greek not computed" sentinel**
for the contract's IV and delta, and the bid/ask in that same record were stale
indicative junk, not a tradeable NBBO. Because `best_put` picks the *highest*
premium-as-%-of-collateral, an unfiltered bad record with a phantom fat bid wins
automatically — argmax over noisy data surfaces the outlier. The fix: a record
without real greeks is not a real quote; drop it before it can be chosen.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import (
    MIN_CUSHION_PCT, MIN_PREMIUM_PCT, DTE_MIN, DTE_MAX,
    MAX_SPREAD_PCT, MAX_DELTA,
)

# Schwab serves this value for any greek/IV it didn't compute (illiquid or not-yet-
# quoted contract). The bid/ask in such a record are stale/indicative, never a real
# market — never price a trade off one.
SCHWAB_SENTINEL = -999.0

# Below this many distinct days of IV history, a rank is more noise than signal — report
# nothing rather than a number that looks authoritative. INFORMATIONAL display floor, not a
# trading rule (nothing gates on iv_rank until ~60 days accrue; see RULES.md §1a).
IV_RANK_MIN_DAYS = 10


def compute_iv_ranks(rows):
    """Per-symbol expanding-window IV rank from iv_history rows: {sym: (rank_0_100, n_days)}.

    rank = where today's IV sits in this name's own observed range so far — the
    tastytrade-standard signal, over whatever window has accrued (n_days says how much
    to trust it; it converges to a true 60d rank as the log fills). Dedupes to ONE
    reading per (symbol, date), last wins: the screener runs morning + intraday, and
    duplicate same-day rows would otherwise fatten the range and skew every rank.
    Symbols with < IV_RANK_MIN_DAYS days are omitted. Pure — caller does the file I/O.
    """
    by_day = {}
    for r in rows:
        sym, d, iv = r.get("symbol"), r.get("date"), r.get("underlying_iv")
        if sym and d and iv is not None:
            by_day.setdefault(sym, {})[d] = iv
    ranks = {}
    for sym, days in by_day.items():
        if len(days) < IV_RANK_MIN_DAYS:
            continue
        series = [iv for _, iv in sorted(days.items())]
        cur, lo, hi = series[-1], min(series), max(series)
        rank = 50.0 if hi == lo else (cur - lo) / (hi - lo) * 100
        ranks[sym] = (round(rank), len(series))
    return ranks


def _greek_ok(x):
    """True for a real computed greek/IV; False for None or the -999 sentinel."""
    return x is not None and x > SCHWAB_SENTINEL + 1


def _flatten_puts(d):
    """Every put in the chain as (strike, expiration, contract) tuples."""
    puts = []
    for expkey, strikes in d.get("putExpDateMap", {}).items():
        exp = expkey.split(":")[0]
        for sp_str, contracts in strikes.items():
            puts.append((float(sp_str), exp, contracts[0]))
    return puts


def underlying_iv_and_spot(d):
    """(underlying IV, spot) from an already-fetched chain dict, or (None, None).

    Underlying IV = the nearest-to-spot strike that actually has a computed IV —
    skipping sentinels so one -999 record can't poison it. Lives here (not in
    best_put_from_chain) so the screener can log IV history for EVERY screened
    name, not just the ones that clear the gates — sparse per-name history is
    what kept IV-rank uncomputable.
    """
    if d.get("status") == "FAILED":
        return None, None
    spot = d.get("underlyingPrice")
    if not spot or spot <= 0:
        return None, None
    puts = _flatten_puts(d)
    iv = next(
        (p[2].get("volatility")
         for p in sorted(puts, key=lambda p: abs(p[0] - spot))
         if _greek_ok(p[2].get("volatility"))),
        None,
    )
    return iv, spot


# The four judgment gates, in the order _score_put applies them. A put that fails
# exactly ONE of these is a NEAR MISS (see near_miss_from_chain): it is a single gate
# away from being a candidate, and that gate is the reason we never saw the name.
# The structural checks above them (real greeks, two-sided quote, DTE window) are not
# gates in this sense — a put failing one of those isn't a trade we passed on, it's a
# contract that doesn't exist for us.
GATES = ("cushion", "delta", "spread", "premium")


def _score_put(sp, exp, ct, spot, underlying_iv, symbol, *, require_delta_gate=True):
    """(record, failed_gates) for one put, or None if it is not a real tradeable quote.

    ONE home for the gate arithmetic (repo DRY rule): both best_put_from_chain and
    near_miss_from_chain call this, so a candidate and a near-miss can never be scored
    by two subtly different copies of the same rules. `failed_gates` == [] means the put
    clears everything; a one-element list names the single gate that killed it.

    Strike DEPTH is gated on delta (MAX_DELTA, RULES.md §2), not on a linear expected-move
    cushion — see the rules.py note on why the old form drifted to half the intended depth
    as IV rose. `implied_move_pct` is still reported: it is what the market prices as a
    1-SD move and the morning layer reads it, but it no longer selects the strike.
    """
    vol, delta = ct.get("volatility"), ct.get("delta")
    # A record without computed greeks is a stale/indicative quote whose bid/ask
    # are not a real market. Because `best` is the MAX premium %, an unfiltered
    # bad record — a fat phantom bid on a deep-OTM put — wins automatically.
    # Drop it. (DVN 2026-06-08: -999 greeks + a $3.20 bid on a put worth ~$0.04.)
    # This filter is now load-bearing twice over: delta IS the depth gate, so a
    # sentinel delta would not merely mis-rank a put, it would wave it through.
    if not _greek_ok(vol) or not _greek_ok(delta):
        return None
    bid, ask = ct.get("bid") or 0, ct.get("ask") or 0
    dte = ct.get("daysToExpiration") or 0
    if bid <= 0 or ask <= 0 or not (DTE_MIN <= dte <= DTE_MAX):
        return None

    abs_delta = abs(delta)
    cushion = (spot - sp) / spot * 100
    implied_move = underlying_iv * math.sqrt(dte / 365)   # informational, no longer a gate
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100 if mid else 999
    premium_pct = mid / sp * 100

    failed = []
    if cushion < MIN_CUSHION_PCT:
        failed.append("cushion")
    if require_delta_gate and abs_delta > MAX_DELTA:
        failed.append("delta")
    if spread_pct > MAX_SPREAD_PCT:
        failed.append("spread")
    if premium_pct < MIN_PREMIUM_PCT:
        failed.append("premium")

    return {
        "symbol": symbol,
        "spot": round(spot, 2),
        "strike": sp,
        "expiration": exp,
        "dte": dte,
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "mid": round(mid, 2),
        "cushion_pct": round(cushion, 1),
        "required_cushion_pct": MIN_CUSHION_PCT,   # the flat floor is now the only cushion rule
        "implied_move_pct": round(implied_move, 1),
        "max_delta": MAX_DELTA,
        "spread_pct": round(spread_pct, 1),
        "premium_pct": round(premium_pct, 2),
        "premium_dollars": round(mid * 100),
        "collateral": round(sp * 100),
        "iv": round(vol, 1),
        "underlying_iv": round(underlying_iv, 1),
        # Put SKEW, in vol points: how much richer this strike's own IV is than the
        # at-the-money IV that VRP is measured against (RULES.md §1). DIAGNOSTIC ONLY —
        # it gates nothing. It exists because VRP is an at-the-money reading while the
        # contract we actually sell is far from the money, so a name can be rejected on
        # ATM vol (MU 2026-07-13: ATM IV 92 vs RV 116, VRP -23) while the put in question
        # prices 34 points above ATM. Logging it is how we find out whether that gap ever
        # marks a real edge; see the note in best_put's VRP block for why we do NOT simply
        # point VRP at this number.
        "skew_pts": round(vol - underlying_iv, 1),
        "delta": round(abs(delta), 3),
    }, failed


def best_put_from_chain(d, symbol, *, require_delta_gate=True):
    """The best gate-clearing put from an already-fetched chain dict, or None.

    'Best' = highest premium-as-%-of-collateral among puts that clear every gate.

    Strike depth is gated on DELTA (<= MAX_DELTA, the ~16-delta / 1-SD-OTM anchor of
    RULES.md §2), plus a flat MIN_CUSHION_PCT floor below spot. Delta is the market's own
    probability that the put finishes in the money, so a name with earnings in the window
    prices that event into delta and is pushed to a deeper strike automatically — the same
    property the old expected-move cushion was reaching for, without the linear-vs-lognormal
    error that made it drift to half the intended depth on high-IV names (see rules.py).

    require_delta_gate=False drops the delta ceiling, leaving the flat cushion floor. This
    is ONLY for the `discuss` tier (RULES.md §1b) — a beaten-down willing-owner name where
    the account owner may want a shallower strike than the published band. A put found this way is
    riskier than the strict gate allows: surfaced for discussion, never actionable.
    """
    underlying_iv, spot = underlying_iv_and_spot(d)
    if underlying_iv is None:
        return None  # no spot, no puts, or whole chain unpriced — nothing safe to price off

    best = None
    for sp, exp, ct in _flatten_puts(d):
        scored = _score_put(sp, exp, ct, spot, underlying_iv, symbol,
                            require_delta_gate=require_delta_gate)
        if scored is None:
            continue
        rec, failed = scored
        if failed:
            continue
        if best is None or rec["premium_pct"] > best["premium_pct"]:
            best = rec
    return best


def near_miss_from_chain(d, symbol):
    """The best put that failed EXACTLY ONE gate, or None. Plus why the name died.

    Returns (record | None, {gate: count}) — the record carries `failed_gate`, the single
    gate that killed it.

    Why this exists: when nothing in a chain clears, the name has until now vanished with
    no trace anywhere — not in last_screen.json, not in skipped_log.jsonl (which only ever
    logged candidates that ALREADY cleared, so the 30-day "did we miss edge?" back-check
    was structurally blind to every name the gates deleted). On 2026-07-13 that was 154 of
    169 names, QCOM among them: its 160 put paid 3.84% with a 12.9% cushion and failed on
    ONE gate — the expected-move cushion demanded 23.6% because ATM IV was 72. We never saw
    it, and we had no way to know we hadn't.

    A near-miss must ALSO clear the flat MIN_CUSHION_PCT floor — so in practice it is a put
    that failed on `delta`, `spread`, or `premium`. Without that requirement the argmax picks
    the at-the-money put every time: a 184 strike on a 183.77 spot fails exactly one gate and
    carries the fattest premium in the chain, so it wins on premium_pct and the telemetry
    reports the most dangerous strike available as "one gate away". It isn't one gate away —
    it's a different trade. Same argmax-over-junk shape as the DVN sentinel bug in this
    module's header: rank by premium and whatever is closest to the money (or fake) wins
    unless you exclude it first. The 10% floor is the non-negotiable minimum the discuss
    tier also keeps (RULES.md §1b).

    A near-miss is NOT a recommendation and is NOT a candidate — it never enters `hits`,
    is never ranked, and can never be actionable. It is the audit trail for what the gates
    threw away, so a gate that is quietly deleting the whole high-IV end of the universe
    shows up as data instead of silence.
    """
    underlying_iv, spot = underlying_iv_and_spot(d)
    if underlying_iv is None:
        return None, {}

    best, counts = None, {}
    for sp, exp, ct in _flatten_puts(d):
        scored = _score_put(sp, exp, ct, spot, underlying_iv, symbol)
        if scored is None:
            continue
        rec, failed = scored
        for g in failed:
            counts[g] = counts.get(g, 0) + 1
        if len(failed) != 1 or rec["cushion_pct"] < MIN_CUSHION_PCT:
            continue
        rec["failed_gate"] = failed[0]
        if best is None or rec["premium_pct"] > best["premium_pct"]:
            best = rec
    return best, counts
