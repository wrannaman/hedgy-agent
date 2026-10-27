"""
risk.py — the fund's risk gate. Turns FUND.md §4 policy into a function.

Given a candidate trade and the book's live holdings, decide pass / trim / reject
and SHOW THE NUMBERS. Every threshold comes from fund_rules.py (single source of
truth); nothing is hardcoded here.

Exposure is measured as **assignment/notional exposure** (FUND.md §4, §2C):
- a long position contributes its market value
- a short cash-secured put contributes its collateral (strike x 100 x contracts) —
  the worst-case "I get assigned and own the stock" notional

Denominator is **active capital** (free cash + collateral committed to active
positions), NOT total account value — the long-term ETF/share core is the benchmark
and is exempt from concentration (FUND.md §3/§5). Holdings carry a `kind`:
"long" (shares/ETF), "short_put" (active), or "core" (exempt long-term holding).

Pure and testable: holdings + candidate in, verdict out. Never calls a broker.
"""
import fund_rules as R


def bucket_for(symbol):
    """Return the correlation bucket a symbol belongs to, or None."""
    s = symbol.upper()
    for name, members in R.CORRELATION_BUCKETS.items():
        if s in members:
            return name
    return None


def _bucket_exposure(holdings, bucket):
    # Core counts here: correlated risk is real even for the long-term core. A new short
    # put on crypto stacks on the IBIT core whether or not we call it "the benchmark".
    if bucket is None:
        return 0.0
    members = set(R.CORRELATION_BUCKETS[bucket])
    return sum(h["exposure"] for h in holdings if h["symbol"].upper() in members)


def evaluate(candidate, holdings, active_capital, free_cash, catalyst_symbols=None,
             book_value=None, vix_term_ratio=None):
    """Evaluate one candidate against the book. Returns {verdict, reasons, metrics}.

    candidate: {symbol, strategy, collateral, vrp(optional)}
    holdings:  [{symbol, exposure, kind}]  kind in long|short_put|put_spread|core
               (put_spread exposure = open width dollars, from fund_engine's
               spread-aware book parsing)
    active_capital: free cash + active short-put collateral (the concentration denominator)
    free_cash: cash available to secure a new put
    catalyst_symbols: names with a confirmed adverse catalyst today (hard reject)
    book_value: total account value (liquidation) — denominator for the per-trade-risk
                cap (PER_TRADE_RISK_PCT, fractional-Kelly-derived). Applied to defined-risk
                trades where max-loss is exact; None skips it.
    vix_term_ratio: VIX/VIX3M (shared.marketdata.vix_term_ratio). At/above
                VIX_BACKWARDATION_RATIO every short-premium candidate is rejected —
                all short-vol sleeves are one correlated bet (FUND.md §2C) and this
                is the regime switch. None = regime unknown = no gate (fail open).
    """
    catalyst_symbols = {s.upper() for s in (catalyst_symbols or [])}
    sym = candidate["symbol"].upper()
    collateral = candidate.get("collateral", 0.0) or 0.0
    # Any short-premium trade ties up capital = collateral (CSP) or max-risk (spread).
    strategy = candidate.get("strategy", "cash_secured_put")
    is_spread = strategy == "put_spread"
    is_short_premium = strategy in ("cash_secured_put", "put_spread")
    bucket = bucket_for(sym)

    has_short_put = any(h["symbol"].upper() == sym and h.get("kind") == "short_put"
                        for h in holdings)
    bucket_now = _bucket_exposure(holdings, bucket)
    name_now = sum(h["exposure"] for h in holdings if h["symbol"].upper() == sym)
    bucket_after_pct = (bucket_now + collateral) / active_capital * 100 if active_capital else 0
    name_after_pct = (name_now + collateral) / active_capital * 100 if active_capital else 0
    buffer_cash = free_cash * (1 - R.DEFENSE_CASH_BUFFER_PCT / 100)

    reasons, verdict = [], "pass"

    def reject(msg):
        nonlocal verdict
        verdict = "reject"
        reasons.append(msg)

    open_positions = sum(1 for h in holdings if h.get("kind") == "short_put")
    open_spread_width = sum(h["exposure"] for h in holdings if h.get("kind") == "put_spread")

    # --- Hard gates (any one rejects) ---
    # The count cap is a committed-cash proxy sized for CSPs ($30-60k collateral each);
    # spreads are capped in DOLLARS of total open width instead (fund_rules, 2026-08-24) —
    # the number that actually bounds the worst simultaneous crash-month loss.
    if not is_spread and open_positions >= R.MAX_CONCURRENT_POSITIONS:
        reject(f"position cap: {open_positions}/{R.MAX_CONCURRENT_POSITIONS} open — slot full")
    if is_spread:
        cand_width = candidate.get("total_width_dollars") or collateral
        if open_spread_width + cand_width > R.SPREAD_DEPLOYMENT_CAP_DOLLARS:
            reject(f"deployment cap: ${open_spread_width:,.0f} of "
                   f"${R.SPREAD_DEPLOYMENT_CAP_DOLLARS:,.0f} spread width open — "
                   f"${cand_width:,.0f} more won't fit")
    # Duplicates: 1 CSP per underlying, unchanged. Spreads on the same index at different
    # expirations are the deliberate weekly ladder, so the gate does not apply to them.
    if not is_spread and has_short_put:
        reject(f"duplicate: already short a put on {sym} (1 per underlying)")
    if is_short_premium and collateral > free_cash:
        reject(f"cash: needs ${collateral:,.0f}, only ${free_cash:,.0f} free")
    elif is_short_premium and collateral > buffer_cash and any(h.get("kind") == "short_put" for h in holdings):
        reject(f"defense buffer: ${collateral:,.0f} would leave <{R.DEFENSE_CASH_BUFFER_PCT:.0f}% "
               f"cash to defend open positions (buffer ${buffer_cash:,.0f})")
    if sym in catalyst_symbols:
        reject(f"catalyst: {sym} has a confirmed adverse move/news today")
    if (is_short_premium and vix_term_ratio is not None
            and vix_term_ratio >= R.VIX_BACKWARDATION_RATIO):
        reject(f"vol regime: VIX/VIX3M {vix_term_ratio:.2f} = backwardation — "
               f"stand down on new short premium")
    vrp = candidate.get("vrp")
    if vrp is not None and vrp <= 0:
        reject(f"no edge: VRP {vrp:+.0f} (premium not priced above realized vol)")
    if bucket and bucket_after_pct > R.MAX_BUCKET_PCT:
        reject(f"bucket: '{bucket}' would be {bucket_after_pct:.0f}% of active capital "
               f"(cap {R.MAX_BUCKET_PCT:.0f}%) — stacking correlated risk")
    # Per-trade risk cap (fractional-Kelly): only for defined-risk trades, where the
    # collateral IS the exact max loss. CSP "collateral" is secured, not at-risk, so it's
    # governed by cash + concentration instead.
    if is_spread and book_value:
        # Spreads get the higher DEFINED_RISK cap (backtested ladder rung); any other
        # defined-risk trade type would fall to PER_TRADE_RISK_PCT.
        risk_cap = book_value * R.DEFINED_RISK_PER_TRADE_PCT / 100
        if collateral > risk_cap:
            reject(f"per-trade risk: ${collateral:,.0f} max-loss > "
                   f"{R.DEFINED_RISK_PER_TRADE_PCT:g}% of book (${risk_cap:,.0f})")

    # --- Soft flags (pass, but trimmed/noted) ---
    if verdict == "pass" and name_after_pct > R.SINGLE_NAME_FLAG_PCT:
        verdict = "trim"
        reasons.append(f"concentrated: {name_after_pct:.0f}% of active capital in one name "
                       f"(>{R.SINGLE_NAME_FLAG_PCT:.0f}% flag) — conviction-size only")
    if verdict == "pass" and vrp is not None and 0 < vrp <= R.VRP_THIN_EDGE:
        verdict = "trim"
        reasons.append(f"thin edge: VRP only {vrp:+.0f} — size small or skip")
    if verdict == "pass":
        reasons.append("clears all gates")

    return {
        "symbol": sym,
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {"bucket": bucket, "name_pct": round(name_after_pct, 1),
                    "bucket_after_pct": round(bucket_after_pct, 1),
                    "collateral": collateral, "vrp": vrp},
    }


def exposure_report(holdings, active_capital):
    """Summarize active-book exposure by name and correlation bucket (% of active capital)."""
    by_name, by_bucket = {}, {}
    for h in holdings:
        s = h["symbol"].upper()
        if h.get("kind") != "core":            # single-name view: active only
            by_name[s] = by_name.get(s, 0.0) + h["exposure"]
        b = bucket_for(s)
        if b:                                   # bucket view: core counts (real correlation)
            by_bucket[b] = by_bucket.get(b, 0.0) + h["exposure"]
    pct = lambda d: {k: round(v / active_capital * 100, 1)
                     for k, v in sorted(d.items(), key=lambda x: -x[1])} if active_capital else {}
    return {"by_name_pct": pct(by_name), "by_bucket_pct": pct(by_bucket)}
