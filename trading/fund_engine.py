"""
fund_engine.py — the morning engine (FUND.md §6).

Sweeps the sleeve scanners, applies the canonical risk gates (risk.py / fund_rules.py),
ranks survivors, and prints ONE actionable brief. Recommendation-only: it never places
an order (repo safety floor). Run after the sleeve scanners have written their state.

Live sleeves: single-name VRP puts, index-VRP spreads, covered calls, trend/regime,
factor tilt, portfolio exposure. Deferred sleeves (PEAD, SPX/XSP §1256) are named in
the brief so the gaps are visible, never silently missing (FUND.md §6).
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "strategies" / "csp_401k"))

import fund_rules as R
import risk
import grade
import judge
from shared.auth import get_client
from shared.accounts import account_by_suffix, configured_account_suffix
from shared.marketdata import vix_term_ratio
from reconcile import parse_occ_symbol

# index_vrp sleeve rules (management flags the engine enacts daily: TREND_EXIT_ON_FLIP,
# PROFIT_TARGET_PCT for the on-fill GTC line). Loaded by path because `import rules`
# would collide with the csp_401k rules already on sys.path.
import importlib.util as _ilu
_ivrp_spec = _ilu.spec_from_file_location(
    "index_vrp_rules", _ROOT / "strategies" / "index_vrp" / "rules.py")
IVRP_RULES = _ilu.module_from_spec(_ivrp_spec)
_ivrp_spec.loader.exec_module(IVRP_RULES)

CSP = _ROOT / "strategies" / "csp_401k" / "state"
PW = _ROOT / "strategies" / "portfolio_watch" / "state"
IVRP = _ROOT / "strategies" / "index_vrp" / "state"
PEAD = _ROOT / "strategies" / "pead" / "state"


def pair_put_positions(positions):
    """Schwab positions -> (holdings, locked). Pure; testable without a client.

    Put legs are bucketed by (underlying, expiration) so short+long pairs become ONE
    defined-risk spread holding (exposure = width dollars, the real committed cash),
    not a phantom full-collateral CSP with its wing dropped. For example, a
    synthetic 100/95 put spread commits $500 of width per contract, not $10,000
    of full short-put collateral. Dropping the long wing would inflate locked
    capital, understate free cash, and misclassify the holding.
    """
    holdings, locked = [], 0.0
    put_shorts, put_longs = {}, {}
    for p in positions or []:
        inst = p.get("instrument", {})
        mv = abs(p.get("marketValue", 0) or 0)
        if inst.get("assetType") == "OPTION":
            parsed = parse_occ_symbol(inst.get("symbol", ""))
            if not parsed or parsed["put_call"] != "PUT":
                continue
            key = (parsed["underlying"], parsed["expiration"])
            shortq = p.get("shortQuantity", 0) or 0
            longq = p.get("longQuantity", 0) or 0
            if shortq > 0:
                put_shorts.setdefault(key, []).append([parsed["strike"], shortq])
            if longq > 0:
                put_longs.setdefault(key, []).append([parsed["strike"], longq])
        elif inst.get("assetType") in ("EQUITY", "COLLECTIVE_INVESTMENT"):
            holdings.append({"symbol": inst.get("symbol", "?"), "exposure": mv, "kind": "core"})
    for (under, exp), shorts in put_shorts.items():
        # Nearest wing pairs first (highest long strike below the short strike).
        longs = sorted(put_longs.get((under, exp), []), key=lambda leg: -leg[0])
        for s_strike, s_qty in shorts:
            for leg in longs:
                l_strike, l_qty = leg
                if s_qty <= 0 or l_qty <= 0 or l_strike >= s_strike:
                    continue
                n = min(s_qty, l_qty)
                width = (s_strike - l_strike) * 100 * n
                locked += width
                holdings.append({"symbol": under, "exposure": width, "kind": "put_spread"})
                s_qty -= n
                leg[1] -= n
            if s_qty > 0:  # unpaired remainder = a true cash-secured short put
                collat = s_strike * 100 * s_qty
                locked += collat
                holdings.append({"symbol": under, "exposure": collat, "kind": "short_put"})
    return holdings, locked


def trend_gate_reason(trend, today=None):
    """Reject-reason for NEW index spreads from the trend signal, or None (gate open).

    Backtest-promoted 2026-08-24 (strategies/index_vrp/backtest.py): no new spreads when
    SPY is below its 40-wk SMA — the replay's losses cluster almost entirely in risk_off
    tapes (the gate skipped 2008 and 2020). A missing/stale signal FAILS CLOSED with its
    own reason — a gate that can't run must say so, never silently pass.
    """
    today = today or date.today().isoformat()
    if not trend or str(trend.get("timestamp", ""))[:10] != today:
        day = str(trend.get("timestamp", ""))[:10] if trend else "never"
        return (f"trend gate: signal stale (last {day}) — gate cannot run, fail closed; "
                f"re-run strategies/trend/scan.py")
    if trend.get("regime") != "risk_on":
        return "trend gate: SPY below 40-wk SMA (risk_off) — no new spreads"
    return None


def load_book(client):
    """Live 401k book: holdings (core vs active short puts), free cash, active capital."""
    from schwab import client as sc
    acct = account_by_suffix(client, configured_account_suffix())
    resp = client.get_account(acct["hashValue"], fields=[sc.Client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    sa = resp.json().get("securitiesAccount", {})
    bal = sa.get("currentBalances", {})
    cash = bal.get("cashBalance", 0)
    book_value = bal.get("liquidationValue", 0) or cash

    holdings, locked = pair_put_positions(sa.get("positions", []))
    free_cash = max(cash - locked, 0)
    return {"holdings": holdings, "free_cash": free_cash, "active_capital": cash,
            "book_value": book_value}


def _screen_is_today(data):
    """A sleeve screen counts only if it was written TODAY. The sleeve scanners run
    non-fatally right before fund_engine (run_daily.sh); if one silently fails, its
    last_screen.json keeps YESTERDAY's candidates. The brief-date guard catches
    fund_engine itself going stale, not a single sleeve's screen — so a stale screen
    would surface candidates whose edge has since flipped (an IWM spread that today's
    scan now rejects on negative VRP). Returns (is_today, screen_day)."""
    screen_day = (data.get("timestamp") or "")[:10]
    return screen_day == date.today().isoformat(), (screen_day or "unknown")


def load_put_candidates():
    """Returns (candidates, stale_day). stale_day is the screen's date when it's not
    today's (so the caller drops the sleeve and says why); None when fresh."""
    f = CSP / "last_screen.json"
    if not f.exists():
        return [], None
    data = json.loads(f.read_text())
    fresh, day = _screen_is_today(data)
    if not fresh:
        return [], day
    return [{"symbol": c["symbol"], "collateral": c["collateral"], "vrp": c.get("vrp"),
             "premium": c.get("premium_dollars"), "cushion": c.get("cushion_pct"),
             "strike": c.get("strike"), "expiration": c.get("expiration"),
             "standing_block": c.get("standing_block"),
             "strategy": "cash_secured_put"} for c in data.get("candidates", [])], None


def load_index_vrp_candidates():
    """Returns (candidates, stale_day) — see load_put_candidates."""
    f = IVRP / "last_screen.json"
    if not f.exists():
        return [], None
    data = json.loads(f.read_text())
    fresh, day = _screen_is_today(data)
    if not fresh:
        return [], day
    return data.get("candidates", []), None


def load_open_index_spreads():
    """Open spreads from the index_vrp sleeve's own trade log (fills only)."""
    f = IVRP / "trade_log.json"
    if not f.exists():
        return []
    return [t for t in json.loads(f.read_text()).get("trades", [])
            if t.get("status") == "open"]


def size_spread_candidate(c, open_spread_width):
    """Scale a scanner 1-contract spread to this week's ladder rung (FUND.md §4).

    Per-entry width = min(remaining deployment room, cap / SPREAD_LADDER_RUNGS), so
    entries stagger across expirations instead of stacking into one week. Sizing never
    forces a fit: at least 1 contract is proposed and risk.evaluate's deployment gate
    rejects it if the cap truly has no room.
    """
    per_width = (c.get("width") or 0) * 100
    if per_width <= 0 or c.get("strategy") != "put_spread":
        return c
    room = R.SPREAD_DEPLOYMENT_CAP_DOLLARS - open_spread_width
    rung = R.SPREAD_DEPLOYMENT_CAP_DOLLARS / R.SPREAD_LADDER_RUNGS
    n = max(int(min(room, rung) // per_width), 1)
    c["contracts"] = n
    c["total_width_dollars"] = round(per_width * n)
    c["collateral"] = round((c.get("collateral") or 0) * n)
    c["premium_dollars"] = round((c.get("net_credit") or 0) * 100 * n)
    return c


def _day_move(q, s):
    quote = q.get(s, {}).get("quote", {})
    return quote.get("netPercentChangeInDouble", quote.get("netPercentChange", 0)) or 0


def detect_catalysts(client, symbols):
    """Flag names down idiosyncratically — falling more than the market by the threshold.
    A broad-beta selloff (premium richest) is NOT a catalyst."""
    if not symbols:
        return set()
    resp = client.get_quotes(list(symbols) + [R.CATALYST_BENCHMARK])
    resp.raise_for_status()
    q = resp.json()
    if R.CATALYST_BENCHMARK not in q:
        return set()  # no benchmark -> can't separate beta from idio; don't false-flag
    market = _day_move(q, R.CATALYST_BENCHMARK)
    return {s for s in symbols if _day_move(q, s) - market <= R.CATALYST_IDIO_PCT}


def load_taxable_book():
    """Taxable-bucket book from portfolio_watch state (the CSV sweep): holdings,
    free cash, bucket value. PEAD is a taxable sleeve, so its candidates are gated
    against THIS bucket — concentration is per-bucket, never cross-bucket."""
    f = PW / "latest.json"
    if not f.exists():
        return None
    from strategies.portfolio_watch.rules import ACCOUNT_BUCKET
    data = json.loads(f.read_text())
    taxable = {s for s, b in ACCOUNT_BUCKET.items() if b == "taxable"}
    accounts = [a for a in data.get("accounts", []) if a.get("account_suffix") in taxable]
    if not accounts:
        return None
    holdings = []
    for sym, e in (data.get("exposures_by_symbol") or {}).items():
        mv = sum(a.get("market_value", 0) for a in e.get("accounts", [])
                 if a.get("suffix") in taxable)
        if mv > 0:
            holdings.append({"symbol": sym, "exposure": mv, "kind": "core"})
    value = sum(a.get("total_market_value", 0) for a in accounts)
    cash = sum(a.get("cash_value", 0) for a in accounts)
    return {"holdings": holdings, "free_cash": cash, "active_capital": value,
            "book_value": value}


def load_pead_candidates(taxable_book):
    """PEAD candidates sized off the fund-wide per-trade risk cap: a long
    position's max loss is its full dollar size, so the suggested position is
    PER_TRADE_RISK_PCT of the taxable bucket (live value, never hardcoded)."""
    f = PEAD / "last_screen.json"
    if not f.exists():
        return [], None
    data = json.loads(f.read_text())
    cands = data.get("candidates", [])
    if taxable_book:
        size = round(taxable_book["book_value"] * R.PER_TRADE_RISK_PCT / 100)
        for c in cands:
            c["collateral"] = size
    return cands, data.get("note")


def load_covered_calls():
    f = CSP / "covered_calls.json"
    if not f.exists():
        return []
    return [c for c in json.loads(f.read_text()).get("candidates", []) if c.get("actionable")]


def load_portfolio_flags():
    f = PW / "latest.json"
    if not f.exists():
        return []
    return json.loads(f.read_text()).get("flags", [])


def load_rebalance():
    """Tax-aware cash-raise + trailing-stop output (portfolio_watch/rebalance.py)."""
    f = PW / "rebalance.json"
    return json.loads(f.read_text()) if f.exists() else None


def _money(v):
    if v is None:
        return "?"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def load_signal(sleeve):
    f = _ROOT / "strategies" / sleeve / "state" / "signal.json"
    return json.loads(f.read_text()) if f.exists() else None


def score(cand):
    """Rank survivors by edge per dollar of capital: VRP-weighted premium yield."""
    vrp = cand.get("vrp") or 0
    prem = cand.get("premium") or 0
    collat = cand.get("collateral") or 1
    return (prem / collat) * max(vrp, 0)


def killed_sleeves():
    """Strategies the scorecard says to KILL (negative realized expectancy past min sample)."""
    return {r["strategy"] for r in grade.scorecard() if r["verdict"].startswith("KILL")}


def track_drawdown(book_value):
    """Append today's book value to the history and return (drawdown%, de-gross directive)."""
    hist = _ROOT / "state" / "book_history.jsonl"
    hist.parent.mkdir(exist_ok=True)
    values = []
    if hist.exists():
        for line in hist.read_text().splitlines():
            try:
                values.append(json.loads(line)["book_value"])
            except (json.JSONDecodeError, KeyError):
                pass
    values.append(book_value)
    with hist.open("a") as f:
        f.write(json.dumps({"book_value": round(book_value)}) + "\n")
    peak = max(values)
    dd = (peak - book_value) / peak * 100 if peak else 0
    for level, cut in sorted(R.DEGROSS_LEVELS, reverse=True):
        if dd >= level:
            return dd, f"book -{dd:.0f}% from peak -> DE-GROSS to {(1 - cut) * 100:.0f}% of gross (ballast)"
    return dd, None


def vol_regime(client):
    """VIX/VIX3M once per run, persisted so downstream consumers (decide.py, the
    agent) see the same number the gates used. None = regime unknown (no gate)."""
    ratio = vix_term_ratio(client, R.VIX_SYMBOL, R.VIX3M_SYMBOL)
    regime = None if ratio is None else (
        "backwardation" if ratio >= R.VIX_BACKWARDATION_RATIO else "contango")
    out = {"vix_term_ratio": ratio, "regime": regime,
           "threshold": R.VIX_BACKWARDATION_RATIO,
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    state = _ROOT / "state"
    state.mkdir(exist_ok=True)
    (state / "vol_regime.json").write_text(json.dumps(out, indent=2))
    return out


def append_journal(book, exp, dd, degross, vol, trend, factor,
                   graded, idx_graded, pead_graded, passing, idx_pass, pead_pass):
    """One JSON line per morning to state/brief_journal.jsonl (append-only).

    The recommendation-grading substrate (FUND.md §6): with ~2 closed trades the
    realized scorecard will take years to reach MIN_TRADES_FOR_EDGE, but the engine
    gates several candidates every morning. Snapshot the world state + every gated
    candidate + what was recommended, and grade.grade_recommendations() scores each
    recommendation once its own expiration passes — sleeves earn or lose trust on
    recommended outcomes long before the live book has the sample size.
    """
    entry = {
        "v": 1,
        "date": str(date.today()),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "book": {"book_value": round(book["book_value"]),
                 "active_capital": round(book["active_capital"]),
                 "free_cash": round(book["free_cash"])},
        "drawdown_pct": round(dd, 1),
        "degross": degross,
        "vol_regime": {"vix_term_ratio": vol["vix_term_ratio"], "regime": vol["regime"]},
        "fomc_in_days": fomc_in_days(),
        "trend": ({"regime": trend.get("regime"), "pct_above": trend.get("pct_above")}
                  if trend else None),
        "factor_leaders": factor.get("leaders") if factor else None,
        "exposure_by_bucket_pct": exp["by_bucket_pct"],
        "candidates": [
            {"sleeve": sleeve, "verdict": g["verdict"], "reasons": g["reasons"],
             "metrics": g["metrics"], "cand": g["cand"]}
            for sleeve, gs in (("csp_401k", graded), ("index_vrp", idx_graded),
                               ("pead", pead_graded))
            for g in gs
        ],
        "recommended": [
            {"sleeve": sleeve, "rank": i, "verdict": g["verdict"], **g["cand"]}
            for sleeve, gs in (("csp_401k", passing), ("index_vrp", idx_pass),
                               ("pead", pead_pass))
            for i, g in enumerate(gs, 1)
        ],
    }
    journal = _ROOT / "state" / "brief_journal.jsonl"
    journal.parent.mkdir(exist_ok=True)
    with journal.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def fomc_in_days(today=None):
    """Days until the next scheduled FOMC announcement, or None if far/none left.
    Awareness only (pre-FOMC drift, FUND.md §2D) — never a gate."""
    today = today or date.today()
    upcoming = [d for d in (date.fromisoformat(s) for s in R.FOMC_DATES_2026)
                if d >= today]
    if not upcoming:
        return None
    days = (min(upcoming) - today).days
    return days if days <= R.FOMC_AWARENESS_DAYS else None


def run():
    client = get_client()
    book = load_book(client)
    vol = vol_regime(client)
    posture = judge.load_posture()
    candidates, put_stale = load_put_candidates()
    catalysts = detect_catalysts(client, {c["symbol"] for c in candidates})

    killed = killed_sleeves()

    def gate(c, catalysts):
        v = risk.evaluate(c, book["holdings"], book["active_capital"], book["free_cash"],
                          catalysts, book["book_value"],
                          vix_term_ratio=vol["vix_term_ratio"])
        if c.get("strategy") in killed:
            v["verdict"] = "reject"
            v["reasons"].append("sleeve KILLED by grading (negative realized expectancy)")
        if c.get("standing_block"):
            v["verdict"] = "reject"
            v["reasons"].append(f"standing disqualifier: {c['standing_block']}")
        v["cand"] = c
        return v

    graded = [gate(c, catalysts) for c in candidates]
    passing = sorted([g for g in graded if g["verdict"] in ("pass", "trim")],
                     key=lambda g: score(g["cand"]), reverse=True)
    rejected = [g for g in graded if g["verdict"] == "reject"]

    # Index-VRP sleeve — same gates; broad ETFs aren't in a correlation bucket, so this
    # sleeve survives when single names are all correlated junk (the whole point).
    idx_cands, idx_stale = load_index_vrp_candidates()
    # Ladder sizing BEFORE gating, so risk.evaluate judges the real ticket (contracts,
    # total width), not the scanner's 1-contract preview.
    _open_spread_width = sum(h["exposure"] for h in book["holdings"]
                             if h.get("kind") == "put_spread")
    idx_cands = [size_spread_candidate(c, _open_spread_width) for c in idx_cands]
    idx_catalysts = detect_catalysts(client, {c["symbol"] for c in idx_cands}) if idx_cands else set()
    idx_graded = [gate(c, idx_catalysts) for c in idx_cands]
    # Trend gate — index sleeve only (see trend_gate_reason).
    trend = load_signal("trend")
    trend_fresh = bool(trend) and str(trend.get("timestamp", ""))[:10] == date.today().isoformat()
    _trend_reason = trend_gate_reason(trend)
    if _trend_reason:
        for g in idx_graded:
            g["verdict"] = "reject"
            g["reasons"].append(_trend_reason)
    # FOMC blackout — index sleeve only. These spreads are pure broad-market bets, so a
    # scheduled Fed decision is the macro event they're most exposed to; don't open new
    # short premium right before it. (Single-name CSPs above keep FOMC awareness-only.)
    _fomc = fomc_in_days()
    if _fomc is not None and _fomc <= R.FOMC_BLACKOUT_DAYS:
        for g in idx_graded:
            g["verdict"] = "reject"
            g["reasons"].append(
                f"FOMC in {_fomc}d — index-VRP blackout (no new broad-market short premium)")
    idx_pass = sorted([g for g in idx_graded if g["verdict"] in ("pass", "trim")],
                      key=lambda g: (g["cand"].get("credit_pct_width") or 0) * max(g["cand"].get("vrp") or 0, 0),
                      reverse=True)

    # PEAD sleeve — long-only drift in the TAXABLE bucket, so it's gated against
    # that bucket's own holdings (concentration is per-bucket, never cross-bucket)
    # and sized off the fund-wide per-trade risk cap.
    taxable_book = load_taxable_book()
    pead_cands, pead_note = load_pead_candidates(taxable_book)
    pead_catalysts = (detect_catalysts(client, {c["symbol"] for c in pead_cands})
                      if pead_cands else set())

    def pead_gate(c):
        tb = taxable_book or book
        v = risk.evaluate(c, tb["holdings"], tb["active_capital"], tb["free_cash"],
                          pead_catalysts, tb["book_value"],
                          vix_term_ratio=vol["vix_term_ratio"])
        if c.get("strategy") in killed:
            v["verdict"] = "reject"
            v["reasons"].append("sleeve KILLED by grading (negative realized expectancy)")
        v["cand"] = c
        return v

    pead_graded = [pead_gate(c) for c in pead_cands]
    pead_pass = sorted([g for g in pead_graded if g["verdict"] in ("pass", "trim")],
                       key=lambda g: g["cand"].get("surprise_pct") or 0, reverse=True)

    exp = risk.exposure_report(book["holdings"], book["active_capital"])
    cc = load_covered_calls()
    flags = load_portfolio_flags()

    dd, degross = track_drawdown(book["book_value"])
    print("=" * 64)
    print("MORNING BRIEF")
    # Machine-parseable freshness key. run_daily.sh and the agent both verify this
    # equals today before trusting any sleeve output — a stale brief (fund_engine
    # failed, or the morning aborted on an auth/market guard before regenerating it)
    # once surfaced a prior day's index spread that should have been FOMC-blacked-out.
    print(f"BRIEF DATE: {date.today().isoformat()}")
    print(judge.dial_header(posture))
    print(f"Book ${book['book_value']:,.0f} (-{dd:.0f}% from peak) | "
          f"active ${book['active_capital']:,.0f} | free ${book['free_cash']:,.0f}")
    print(f"Book exposure by bucket (% active): {exp['by_bucket_pct']}")
    if vol["regime"] is None:
        print("Vol regime: unknown (VIX/VIX3M quote unavailable — gate not applied)")
    else:
        tail = (" — short-premium stood down" if vol["regime"] == "backwardation" else "")
        print(f"Vol regime: VIX/VIX3M {vol['vix_term_ratio']:.2f} {vol['regime'].upper()}{tail}")
    if degross:
        print(f"  ⚠ DRAWDOWN BRAKE: {degross}")
    fomc = fomc_in_days()
    if fomc is not None:
        when = "TODAY" if fomc == 0 else f"in {fomc} day{'s' if fomc > 1 else ''}"
        print(f"FOMC announcement {when} (press-conference meeting; pre-FOMC drift "
              f"window — awareness, not a gate)")
    print("=" * 64)

    print("\nPUT SLEEVE (VRP single-name):")
    if passing:
        for g in passing:
            c = g["cand"]
            vrp = f"{c['vrp']:+g}" if c.get("vrp") is not None else "n/a"
            print(f"  ✅ {g['verdict'].upper()} {c['symbol']} ${c.get('strike')}p "
                  f"{c.get('expiration')} — ${c.get('premium') or 0:,.0f}/{c.get('collateral') or 0:,.0f} collat, "
                  f"VRP {vrp}; {'; '.join(g['reasons'])}")
    elif put_stale:
        print(f"  ⚠ SCREEN STALE (last scan {put_stale}, not today) — sleeve dropped; "
              f"re-run strategies/csp_401k screener. No put surfaced.")
    else:
        print("  (nothing clears the gates today)")
    for g in rejected:
        c = g["cand"]
        print(f"  ✗ {c['symbol']:5} — {'; '.join(g['reasons'])}")

    # JUDGE — the dial gate sits on top of the sleeve's own gates. A spread that cleared
    # risk.evaluate still has to clear the active posture's cushion/VRP floors before it may
    # surface; killed spreads drop to the JUDGE line below with a terse why (FUND.md §6).
    idx_surf, idx_flag, idx_kill = judge.partition_spreads([g["cand"] for g in idx_pass], posture["cfg"])
    _idx_gate = {id(g["cand"]): g for g in idx_pass}
    _flagged_ids = {id(it["cand"]) for it in idx_flag}

    print("\nINDEX-VRP SLEEVE (defined-risk put spreads, best-evidence edge):")
    if idx_surf:
        for it in idx_surf:
            c = it["cand"]; g = _idx_gate[id(c)]
            warn = "  ⚠ JUDGE-FLAGGED (thin): " if id(c) in _flagged_ids else ""
            n = c.get("contracts", 1)
            pop = f", ~{(1 - c['short_delta']) * 100:.0f}% POP" if c.get("short_delta") else ""
            print(f"  ✅ {g['verdict'].upper()} {c['symbol']} {c['short_strike']:g}/{c['long_strike']:g}p "
                  f"{c['expiration']} x{n} — ${c['premium_dollars']} credit / ${c['collateral']} risk "
                  f"({c['credit_pct_width']:.0f}% of width), {c['cushion_pct']:.0f}% cushion, "
                  f"VRP {c.get('vrp')}{pop}; {'; '.join(g['reasons'])}")
            # The exact Schwab ticket + the standing order to place on fill (75% take:
            # GTC buy-to-close at 25% of the net credit — index_vrp/rules.PROFIT_TARGET_PCT).
            gtc = round(c["net_credit"] * (1 - IVRP_RULES.PROFIT_TARGET_PCT / 100), 2)
            print(f"     ORDER: Sell to Open {n} {c['symbol']} {c['expiration']} "
                  f"${c['short_strike']:g} Put / Buy to Open {n} {c['symbol']} {c['expiration']} "
                  f"${c['long_strike']:g} Put — net credit ${c['net_credit']:.2f} limit, DAY")
            print(f"     ON FILL: GTC buy-to-close the spread at ${gtc:.2f} "
                  f"({IVRP_RULES.PROFIT_TARGET_PCT:g}% of max), end date {c['expiration']}")
            if warn:
                print(f"  {warn}{it['why']}")
    elif idx_kill:
        print(f"  (no spread clears the {posture['dial'].upper()} dial — see JUDGE below)")
    elif idx_cands:
        for g in idx_graded:
            c = g["cand"]
            print(f"  ✗ {c['symbol']} — {'; '.join(g['reasons'])}")
    elif idx_stale:
        print(f"  ⚠ SCREEN STALE (last scan {idx_stale}, not today) — sleeve dropped; "
              f"re-run strategies/index_vrp/scan.py. No spread surfaced.")
    else:
        print("  (run strategies/index_vrp/scan.py first)")

    if idx_kill:
        print(f"\nJUDGE ({posture['dial'].upper()} dial) — killed before surfacing:")
        for it in idx_kill:
            print(f"  🛑 {it['why']}")

    # Trend-flip exit (index_vrp/rules.TREND_EXIT_ON_FLIP, backtest-promoted 2026-08-24):
    # when the regime flips risk_off, open spreads are CLOSED, not just new entries
    # blocked — blocking-only rode 2022 down (-$74k vs -$39k in the replay). Daily check
    # is the design: the signal is computed on closes, same as the backtest. Tickets
    # only; the account owner executes. A stale signal emits nothing (the entry gate above already
    # failed closed and said so).
    flip_exits = []
    if IVRP_RULES.TREND_EXIT_ON_FLIP and trend_fresh and trend.get("regime") == "risk_off":
        for t in load_open_index_spreads():
            n = t.get("contracts", 1)
            flip_exits.append(
                f"EXIT {t['symbol']} {t.get('sell_strike'):g}/{t.get('buy_strike'):g}p "
                f"{t.get('expiration')} x{n} — trend flipped risk_off. Cancel the resting "
                f"GTC first, then: Buy to Close {n} {t['symbol']} {t.get('expiration')} "
                f"${t.get('sell_strike'):g} Put / Sell to Close {n} {t['symbol']} "
                f"{t.get('expiration')} ${t.get('buy_strike'):g} Put — net debit at the mid "
                f"(check the live quote; this is a worked limit, not a market order)")
    if flip_exits:
        print("\nTREND-FLIP EXITS (close open spreads — risk_off):")
        for line in flip_exits:
            print(f"  🚪 {line}")

    _pead_live = R.sleeve_is_live("pead")
    _pead_status = "" if _pead_live else " — PAPER (proving out, NOT actionable)"
    print(f"\nPEAD SLEEVE (post-earnings drift, long-only, taxable, recommendation-only){_pead_status}:")
    if pead_note:
        print(f"  ({pead_note})")
    elif pead_pass:
        for g in pead_pass:
            c = g["cand"]
            size = f" ~${c['collateral']:,.0f}" if c.get("collateral") else ""
            tag = "✅" if _pead_live else "📄"
            print(f"  {tag} {g['verdict'].upper()} BUY-DRIFT {c['symbol']}{size} — beat by "
                  f"{c['surprise_pct']:+.0f}% (reported {c['report_date']}), "
                  f"hold to ~{c['expiration']}; {'; '.join(g['reasons'])}")
    elif pead_cands:
        for g in pead_graded:
            c = g["cand"]
            print(f"  ✗ {c['symbol']} — {'; '.join(g['reasons'])}")
    else:
        print("  (no decisive beats in the entry window — run strategies/pead/scan.py)")

    print("\nCOVERED-CALL SLEEVE:")
    if cc:
        for c in cc:
            print(f"  • {c['symbol']} ${c['strike']}c {c['expiration']} — "
                  f"${c['premium_dollars']:,.0f}, {c['otm_pct']:.0f}% OTM, ${c['dollars_per_day']:.1f}/day")
    else:
        print("  (none actionable)")

    factor = load_signal("factor")  # trend already loaded above (it gates the index sleeve)
    print("\nTREND / REGIME:")
    if trend:
        print(f"  {trend['benchmark']} ${trend['price']} vs SMA ${trend['sma']} "
              f"({trend['pct_above']:+}%) -> {trend['regime'].upper()}"
              + (f" — de-gross into {', '.join(trend['ballast'])}" if trend['regime'] == 'risk_off' else ""))
    else:
        print("  (run strategies/trend/scan.py)")

    print("\nFACTOR TILT (12-1 momentum):")
    if factor:
        bench = factor.get("benchmark_mom")
        bench_s = f"{bench:+g}%" if bench is not None else "n/a"
        print(f"  tilt toward {', '.join(factor['leaders'])}  (vs SPY {bench_s})")
    else:
        print("  (run strategies/factor/scan.py)")

    print()
    grade.run()
    try:
        grade.run_recommendations(client)
    except Exception as e:  # network grading is best-effort; never blocks the brief
        print(f"  (recommendation grading skipped: {e})")

    print("\nPORTFOLIO FLAGS (recommendation-only accounts):")
    for fl in flags[:4]:
        print(f"  ⚠ {fl['message']}")

    # Tax-aware de-gross lens: how to raise cash with the least tax + which
    # concentrated winners have fallen past their trailing stop. The agent folds
    # the material lines into Slack; recommendation-only, never an order.
    reb = load_rebalance()
    print("\nTAX-AWARE REBALANCE (taxable de-gross, recommendation-only):")
    if not reb:
        print("  (run strategies/portfolio_watch/rebalance.py first)")
    else:
        harvests = reb.get("harvests", [])
        if harvests:
            saved = -sum(h["tax_to_exit_full"] for h in harvests)
            names = ", ".join(f"{h['symbol']} ({_money(h['gain'])})" for h in harvests)
            print(f"  HARVEST now (~{_money(saved)} tax saved by banking losses): {names}")
        for t in reb.get("trailing_stops", []):
            print(f"  ⚠ STOP: {t['message']} Full taxable-exit tax ~{_money(t['tax_to_exit_taxable'])}.")
        ladder = reb.get("cash_ladder", {})
        if ladder.get("rungs"):
            path = " → ".join(r["symbol"] for r in ladder["rungs"])
            print(f"  Cheapest-tax path to raise {_money(ladder['target'])} spendable: "
                  f"{path}  (net tax {_money(ladder['total_tax'])}, "
                  f"{ladder['blended_rate'] * 100:.0f}% blended)")
        free = reb.get("free_moves", [])
        if free:
            dp = sum(m["market_value"] for m in free)
            print(f"  Sheltered dry powder (Roth/401k, $0 tax to rotate): {_money(dp)}")
        for u in reb.get("needs_review", []):
            print(f"  • review: {u['symbol']} — {u['reason']}")

    print("\nSLEEVES DEFERRED (need infra, not built — no slop): "
          "SPX/XSP §1256 upgrade for index-VRP.")
    print("Earnings IV-crush is handled inside the put screener (cushion covers the implied move).")

    # Structured brief for the ONE Slack renderer (slack_format.py). Text brief stays for
    # humans/agent reading; this is the machine handoff so the renderer never parses prose.
    # A non-live (paper) sleeve's PASS surfaces here under "paper" with its scorecard
    # progress — visible and tracked, but never as a NEW (actionable) trade.
    _scores = {r["strategy"]: r for r in grade.scorecard()}

    def _paper_line(strat, label):
        sc = _scores.get(strat, {})
        prog = f"{sc.get('n', 0)}/{R.MIN_TRADES_FOR_EDGE} forward trades" if sc else "no track record"
        return f"{strat}: {label} — sleeve unvalidated ({prog})"

    paper = []
    if not R.sleeve_is_live("pead") and pead_pass:
        for g in pead_pass:
            paper.append(_paper_line("pead", f"{g['cand']['symbol']} buy-drift"))
    # (trend/factor are signals, not discrete trades — surface only if a PASS exists)

    brief_json = {
        "dial": {"label": posture["dial"],
                 "floors": f"min cushion {posture['cfg']['min_cushion_pct']:.0f}%, "
                           f"VRP +{posture['cfg']['min_vrp']:.0f}"},
        "near_misses": [it["why"] for it in idx_kill],
        "exit_tickets": flip_exits,
        "paper": paper,
    }
    (_ROOT / "state").mkdir(exist_ok=True)
    (_ROOT / "state" / "brief.json").write_text(json.dumps(brief_json, indent=2))

    try:
        append_journal(book, exp, dd, degross, vol, trend, factor,
                       graded, idx_graded, pead_graded, passing, idx_pass, pead_pass)
    except Exception as e:
        print(f"  (brief journal append failed: {e})")
    return {"passing": passing, "rejected": rejected}


if __name__ == "__main__":
    run()
