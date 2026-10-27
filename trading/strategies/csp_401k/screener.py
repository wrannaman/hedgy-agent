"""
Market-wide cash-secured-put screener — the new heart of the morning hunt.

The old scan watched 16 names and only reacted to red-day dips, so on a calm or
green day it found nothing and the bot never traded. This sweeps the whole
universe every run and finds, per name, the best put that clears the strategy's
own gates: a strike at least MIN_CUSHION_PCT below the current price, 28-45 days
out, liquid, paying at least the premium floor.

It does NOT wait for a name to drop — a high-volatility name pays fat premium on
a far-out put on any day. That is the "roam".

Output: ranked candidates to state/last_screen.json + a readable table.
It only surfaces candidates — it never sends Slack and never places orders.
The judgment layer (willing-owner, concentration, noise-vs-news) still runs on
top of this before anything is recommended.

Run:  python3 screener.py
"""
import math
import sys
import time
import json
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from shared.marketdata import realized_vol_30d
from schwab.client import Client
from universe import UNIVERSE
from daily_scan import get_cash_status

# --- gates: canonical values live in rules.py (single source of truth) ---
from rules import (
    MIN_CUSHION_PCT, MIN_PREMIUM_PCT, DTE_MIN, DTE_MAX,
    MAX_SPREAD_PCT, MAX_DELTA, MIN_VRP, ACTIONABLE_VRP,
    ACTIONABLE_VRP_RATIO, NO_CHASE_SIGMA, NEAR_52W_LOW_BAND_PCT,
)
from screener_select import (
    best_put_from_chain, near_miss_from_chain, underlying_iv_and_spot, compute_iv_ranks,
)
from standing_risk import load_standing_risk, standing_block, standing_risk_health

STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_PATH = STATE_DIR / "last_screen.json"
IV_HISTORY_PATH = STATE_DIR / "iv_history.jsonl"     # per-name daily IV — feeds IV-rank once ~60 days of data exist
SKIPPED_LOG_PATH = STATE_DIR / "skipped_log.jsonl"   # every candidate ever surfaced — for 30d back-check
NEAR_MISS_LOG_PATH = STATE_DIR / "near_miss.jsonl"   # names the gates DELETED — the other half of the back-check


def best_put(client, symbol, near_52w_low=False, day_change_pct=None, standing_risk=None):
    """Fetch symbol's chain, return (best gate-clearing put | None, IV obs | None, near-miss | None).

    The selection logic itself lives in screener_select.best_put_from_chain (pure,
    unit-tested, and home to the Schwab -999 greek-sentinel filter). This wrapper
    only does the I/O: pull the chain and the realized vol.

    The IV observation is returned for EVERY name whose chain priced (not just
    gate-clearers) so iv_history.jsonl accrues a dense per-name series — the
    prerequisite for IV-rank.

    The near-miss is returned ONLY when nothing cleared, and is telemetry, never a
    candidate — see near_miss_from_chain. It is what makes a silently-deleted name
    visible rather than silently omitted.
    """
    today = date.today()
    resp = client.get_option_chain(
        symbol,
        contract_type=Client.Options.ContractType.PUT,
        from_date=today + timedelta(days=DTE_MIN),
        to_date=today + timedelta(days=DTE_MAX),
    )
    resp.raise_for_status()
    payload = resp.json()
    iv, spot = underlying_iv_and_spot(payload)
    iv_obs = None
    if iv is not None:
        iv_obs = {"symbol": symbol, "underlying_iv": round(iv, 1), "spot": round(spot, 2)}
    best = best_put_from_chain(payload, symbol)
    # DISCUSS tier (RULES.md §1b): if nothing cleared the strict gate but this name is near its
    # 52-week low, retry with the expected-move cushion relaxed to the flat floor. A put found
    # only this way is shallower than the strict gate allows — surfaced for a human look, never
    # actionable. This is what stops beaten-down high-IV names (META near its low) from
    # vanishing silently. It IS a screened trade; it's just tagged "talk about it first".
    discuss = False
    if best is None and near_52w_low:
        best = best_put_from_chain(payload, symbol, require_delta_gate=False)
        discuss = best is not None
    # Nothing cleared and the discuss tier didn't catch it either => the name is about to
    # vanish. Record WHAT the gates threw away and WHICH gate did it, before it does.
    near_miss = None
    if best is None:
        nm, gate_counts = near_miss_from_chain(payload, symbol)
        if nm is not None:
            nm["gate_fail_counts"] = gate_counts
            near_miss = nm
    if best is not None:
        best["discuss"] = discuss
        best["gate_cleared"] = not discuss
        # Variance risk premium — the real short-premium edge metric.
        # IV - RV > 0 means options are pricing in more vol than the stock has
        # been realizing, which is when selling premium has historical edge.
        # If VRP is near zero or negative, you're selling fairly-priced or
        # underpriced vol — no edge, regardless of how fat the raw premium looks.
        #
        # Measure VRP at the money, not at the candidate's strike. Put skew can
        # lift deep-out-of-the-money strike IV above ATM IV; treating that gap as
        # VRP would relabel skew as edge and make the gate stop discriminating.
        # The cited variance-premium literature compares ATM implied to realized.
        # The strike-vs-ATM gap is logged instead, as `skew_pts` (screener_select), where it
        # can be evaluated against outcomes before anything is allowed to trade on it.
        rv = realized_vol_30d(client, symbol)
        best["realized_vol_30d"] = rv
        best["vrp"] = round(best["underlying_iv"] - rv, 1) if rv is not None else None
        # The edge gate (RULES.md §1): a candidate is only actionable when options price
        # MORE vol than the stock has realized (VRP > MIN_VRP). Raw premium size is not
        # edge — without positive VRP we'd be selling fairly/underpriced vol. None RV =>
        # edge unconfirmed => not actionable. The dial may demand more, never less.
        best["edge_ok"] = best["vrp"] is not None and best["vrp"] > MIN_VRP
        # ACT vs WATCH (RULES.md §1a): edge_ok means "has some edge, worth logging"; actionable
        # means "rich enough to surface as a trade". A thin +1-to-+14 VRP name is edge_ok but
        # NOT actionable — it stays ranked/tracked but never reaches the account owner as a sell. This is
        # what stops calm-day, no-catalyst puts (INTC +9.6) from being pitched as "act now".
        # ...and as a PROPORTION: a flat point floor is easier for violent names to clear on
        # noise (15 pts on a 90-vol name is 1.17x; on a 25-vol name 1.6x), tilting the screen
        # toward the most dangerous underlyings. Both must hold (RULES.md §1a).
        best["vrp_ratio"] = round(best["underlying_iv"] / rv, 2) if rv else None
        best["actionable"] = (best["edge_ok"] and best["vrp"] >= ACTIONABLE_VRP
                              and (best["vrp_ratio"] or 0) >= ACTIONABLE_VRP_RATIO)
        # No-chase (RULES.md §1, enforced 2026-07-01): initiating right after a sharp up-move
        # sells insurance the pop just deflated. Sharp = above NO_CHASE_SIGMA daily sigmas of
        # the name's OWN realized vol (a +4% day on an 83-vol INTC is normal; on a 20-vol
        # staple it's an event). Demote ACT -> WATCH for today; re-surfaces next screen.
        best["day_change_pct"] = day_change_pct
        if best["actionable"] and day_change_pct is not None and rv:
            daily_sigma = rv / math.sqrt(252)
            if day_change_pct > NO_CHASE_SIGMA * daily_sigma:
                best["actionable"] = False
                best["no_chase"] = True
                best["watch_reason"] = (
                    f"up {day_change_pct:+.1f}% today (> {NO_CHASE_SIGMA:g} sigma = "
                    f"{daily_sigma:.1f}%) — premium just deflated; re-check on a flat/red day")
        # A discuss-tier candidate is shallow by construction (RULES.md §1b) — surfaced for a
        # human look, NEVER auto-actionable, whatever its VRP. Keep edge_ok/vrp populated so the
        # conversation has the numbers, but strip the ACT.
        if discuss:
            best["actionable"] = False
            best["surface_reason"] = (
                f"within {NEAR_52W_LOW_BAND_PCT:g}% of its 52-week low; the ${best['strike']:g} "
                f"put clears the {MIN_CUSHION_PCT:g}% floor but is {best['delta']:.2f} delta, past "
                f"the {MAX_DELTA:g} band — DISCUSS, not a screened trade")
        # Standing risk (RULES.md §5a/§5b) — LAST, so it overrides every tier above it,
        # including a discuss-tier surface. Two facts that are true today because they were
        # true yesterday: an uncleared company-specific disqualifier, and a dated
        # share-supply event inside the contract. Both live in standing_risk.json, both are
        # gates rather than prose, because re-deciding them each morning is exactly what
        # produced four straight SPCX drops followed by an ACT on the fifth day with nothing
        # material changed. Demote, don't delete: the name stays ranked and logged.
        block_reason = standing_block(symbol, best["expiration"], risk=standing_risk)
        if block_reason:
            best["actionable"] = False
            best["standing_block"] = block_reason
            best["watch_reason"] = block_reason
        if iv_obs is not None:
            iv_obs["realized_vol_30d"] = rv
            iv_obs["vrp"] = best["vrp"]
        # Entry edge, grounded in data we already have (no extra calls):
        #   p_assign ≈ |delta| = market-implied prob the put finishes ITM.
        #   variance-premium EV = premium received (priced at IV) minus the put's
        #   fair value priced at REALIZED vol. IV > RV => we sold rich => positive
        #   expected value. This is the edge thesis as a number, per contract-lot.
        from blackscholes import put_price
        best["p_assign_pct"] = round(best["delta"] * 100, 1)   # delta already abs()
        if rv is not None:
            fair_at_rv = put_price(best["spot"], best["strike"], best["dte"], rv)
            best["ev_dollars"] = round((best["mid"] - fair_at_rv) * 100)
        else:
            best["ev_dollars"] = None
    return best, iv_obs, near_miss


def append_iv_history(iv_rows):
    """Append today's underlying IV for every screened name to a long-running log.
    Once this file has >=60 trading days for a name, true IV-rank becomes
    computable (current IV vs that name's own 60-day high/low).

    Rows for gate-clearing hits also carry realized vol + VRP (fetched only for
    hits — RV is an extra price-history call per name); IV alone is what the
    rank needs, so every priced chain contributes a row.
    """
    today = str(date.today())
    with IV_HISTORY_PATH.open("a") as f:
        for h in iv_rows:
            f.write(json.dumps({
                "date": today,
                "symbol": h["symbol"],
                "underlying_iv": h["underlying_iv"],
                "realized_vol_30d": h.get("realized_vol_30d"),
                "vrp": h.get("vrp"),
                "spot": h["spot"],
            }) + "\n")


def append_near_miss_log(near_misses):
    """Snapshot every name the gates DELETED today, and the one gate that deleted it.

    The companion to append_skipped_log, and the half that was missing. skipped_log
    answers "of the puts we SAW and passed on, which were good skips?" — but it only ever
    contained names that already cleared the gates, so it could never answer the more
    expensive question: "what did the gates throw away, and should they have?" A name where
    nothing cleared can otherwise leave no trace of the rejected name or failing gate.

    Same 30-day back-check shape as skipped_log — spot at log, strike, expiry — so the two
    files can be evaluated by the same machinery. Nothing here is a recommendation.
    """
    now = datetime.now().isoformat()
    with NEAR_MISS_LOG_PATH.open("a") as f:
        for h in near_misses:
            f.write(json.dumps({
                "logged_at": now,
                "symbol": h["symbol"],
                "spot_at_log": h["spot"],
                "strike": h["strike"],
                "expiration": h["expiration"],
                "dte_at_log": h["dte"],
                "mid_at_log": h["mid"],
                "premium_pct": h["premium_pct"],
                "cushion_pct": h["cushion_pct"],
                "required_cushion_pct": h["required_cushion_pct"],
                "spread_pct": h["spread_pct"],
                "iv": h["iv"],
                "underlying_iv": h["underlying_iv"],
                "skew_pts": h["skew_pts"],
                "delta": h["delta"],
                "failed_gate": h["failed_gate"],
                "gate_fail_counts": h.get("gate_fail_counts"),
            }) + "\n")


def append_skipped_log(hits):
    """Snapshot every candidate the screener surfaced today, so we can
    back-check in 30+ days whether the puts we didn't trade expired worthless
    (missed edge) or got blown through (good skip).

    We log ALL candidates, not just the ones we passed on, because at log-time
    we don't know which one we'll actually trade — the judgment layer decides
    that later. The back-check cross-references trade_log.json to determine
    which were traded vs skipped.
    """
    now = datetime.now().isoformat()
    with SKIPPED_LOG_PATH.open("a") as f:
        for h in hits:
            f.write(json.dumps({
                "logged_at": now,
                "symbol": h["symbol"],
                "spot_at_log": h["spot"],
                "strike": h["strike"],
                "expiration": h["expiration"],
                "dte_at_log": h["dte"],
                "premium_dollars": h["premium_dollars"],
                "premium_pct": h["premium_pct"],
                "cushion_pct": h["cushion_pct"],
                "implied_move_pct": h["implied_move_pct"],
                "underlying_iv": h["underlying_iv"],
                "realized_vol_30d": h.get("realized_vol_30d"),
                "vrp": h.get("vrp"),
            }) + "\n")


def run_screen():
    client = get_client()
    try:
        free = get_cash_status(client)["net_available"]
    except Exception:
        free = None

    # Which names sit within NEAR_52W_LOW_BAND_PCT of their 52-week low — the discuss-tier
    # trigger (RULES.md §1b). One batched quote sweep up front (cheap next to 160 chain calls)
    # so best_put can relax the cushion only for beaten-down names. Failure here is non-fatal:
    # an empty map just means no discuss candidates this run.
    #
    # WILLING-OWNER gate on the discuss tier: the
    # tier's premise is "sell into fear on a QUALITY name the account owner wants to own cheaper" —
    # its shallow cushion means assignment is a real outcome, so only names on the curated
    # willing-owner list qualify. A beaten-down lottery ticket (JOBY/ACHR near their lows)
    # is a falling knife, not a discount — it never surfaces here. ACT candidates are NOT
    # gated by this list: their deep expected-move cushion makes assignment a tail, not a
    # plan (MARA can be an ACT without being a willing-owner name).
    from laggard_scan import WILLING_OWNER
    near_low, day_chg = {}, {}
    for j in range(0, len(UNIVERSE), 100):
        try:
            resp = client.get_quotes(UNIVERSE[j:j + 100])
            resp.raise_for_status()
            for sym, rec in resp.json().items():
                q = rec.get("quote", {})
                lo, last = q.get("52WeekLow"), q.get("lastPrice")
                if lo and last:
                    near_low[sym] = (sym in WILLING_OWNER
                                     and last <= lo * (1 + NEAR_52W_LOW_BAND_PCT / 100))
                day_chg[sym] = q.get("netPercentChange")   # feeds the no-chase guard
        except Exception:
            continue

    # Expanding-window IV rank from the accrued per-name history (RULES.md §1a).
    # INFORMATIONAL until ~60 days accrue — iv_rank_days says how much to trust each rank.
    iv_ranks = {}
    if IV_HISTORY_PATH.exists():
        try:
            iv_ranks = compute_iv_ranks(
                json.loads(line) for line in IV_HISTORY_PATH.open() if line.strip())
        except Exception:
            iv_ranks = {}

    # Load the standing-risk gates ONCE for the whole sweep (RULES.md §5a/§5b) — 169 names
    # must not each re-read the file, and a mid-sweep edit must not change the rules under us.
    standing_risk = load_standing_risk()

    hits, iv_rows, near_misses, errors = [], [], [], 0
    for i, sym in enumerate(UNIVERSE, 1):
        try:
            b, iv_obs, nm = best_put(client, sym, near_52w_low=near_low.get(sym, False),
                                     day_change_pct=day_chg.get(sym),
                                     standing_risk=standing_risk)
            if iv_obs:
                iv_rows.append(iv_obs)
            if nm:
                near_misses.append(nm)
            if b:
                b["fits_cash"] = free is None or b["collateral"] <= free
                rank = iv_ranks.get(sym)
                b["iv_rank"], b["iv_rank_days"] = rank if rank else (None, None)
                hits.append(b)
        except Exception:
            errors += 1
        if i % 25 == 0:
            print(f"  ...screened {i}/{len(UNIVERSE)}  ({len(hits)} candidates)", flush=True)
        time.sleep(0.2)

    # Rank by tier, premium % breaking ties within a tier (RULES.md §1, §1a, §1b):
    #   3 ACT       — gate-cleared + VRP >= ACTIONABLE_VRP: the only surface-as-a-trade tier
    #   2 edge_ok   — gate-cleared + some positive VRP: WATCH, logged, never pitched
    #   1 cleared   — gate-cleared but no confirmed edge (VRP <= 0 / RV unknown)
    #   0 discuss   — beaten-down near its low, shallow, NOT gate-cleared: a conversation, not a trade
    #  -1 other
    def _tier(x):
        if x.get("actionable"):
            return 3
        if x.get("gate_cleared") and x.get("edge_ok"):
            return 2
        if x.get("gate_cleared"):
            return 1
        if x.get("discuss"):
            return 0
        return -1
    hits.sort(key=lambda x: (_tier(x), x["premium_pct"]), reverse=True)
    # Near-misses are telemetry, never trades — ranked only so the report shows the ones
    # that came closest to clearing (biggest premium the gates rejected) at the top.
    near_misses.sort(key=lambda x: x["premium_pct"], reverse=True)

    out = {
        "timestamp": datetime.now().isoformat(),
        "universe_size": len(UNIVERSE),
        "errors": errors,
        "free_cash": free,
        "gates": {
            "min_cushion_pct": MIN_CUSHION_PCT,
            "max_delta": MAX_DELTA,
            "min_premium_pct": MIN_PREMIUM_PCT,
            "min_vrp": MIN_VRP,
            "actionable_vrp": ACTIONABLE_VRP,
            "dte": [DTE_MIN, DTE_MAX],
        },
        # What the standing gates were holding on this run, so the recap can say so and the
        # back-check can ask later whether each block was right (RULES.md §5a/§5b).
        "standing_risk": {
            "disqualified": sorted({str(d.get("symbol", "")).upper()
                                    for d in standing_risk["disqualifiers"] if not d.get("cleared")}),
            "supply_events": standing_risk["supply_events"],
            "load_error": standing_risk["load_error"],
        },
        "candidates": hits,
        # Every name the gates deleted, and which gate did it. NOT candidates — nothing
        # downstream may treat these as tradeable; they exist so the back-check can ask
        # "did the puts we never even saw expire worthless?" the same way it already asks
        # it of the ones we saw and passed on.
        "near_misses": near_misses,
    }
    STATE_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(out, indent=2, default=str))

    # Persist for future analysis. All three are append-only — never overwrite.
    if iv_rows:
        append_iv_history(iv_rows)
    if hits:
        append_skipped_log(hits)
    if near_misses:
        append_near_miss_log(near_misses)

    return out


def print_report(out):
    hits = out["candidates"]
    print(f"\n=== PUT SCREEN {datetime.now():%Y-%m-%d %H:%M} ===")
    print(f"Universe {out['universe_size']} names | "
          f"{len(hits)} cleared the gates "
          f"(delta <= {MAX_DELTA:.2f} | cushion >= {MIN_CUSHION_PCT:.0f}% | "
          f">={MIN_PREMIUM_PCT:.0f}% premium | {DTE_MIN}-{DTE_MAX} days) | "
          f"{out['errors']} errors")
    if out["free_cash"] is not None:
        print(f"401k free cash: ${out['free_cash']:,.0f}")
    # Say out loud what the standing gates held, and why. A block that happens silently
    # gets re-litigated by the next agent that sees a fat VRP and no explanation.
    health = standing_risk_health(out["standing_risk"])
    if health:
        print(health)
    for h in hits:
        if h.get("standing_block"):
            print(f"BLOCKED {h['symbol']} (VRP {h.get('vrp')}, would otherwise be "
                  f"{'ACT' if h.get('vrp') is not None and h['vrp'] >= ACTIONABLE_VRP else 'WATCH'}): "
                  f"{h['standing_block']}")
    if not hits:
        # A zero-candidate day is exactly when the near-miss list is worth the most:
        # it is the difference between "the market offered nothing" and "our gates
        # deleted everything the market offered". Never return before printing it.
        print("No candidates today.")
        print_near_misses(out)
        return
    print(f"\n{'#':>2} {'sym':<6}{'spot':>9}{'strike':>8}{'expiry':>12}{'dte':>4}"
          f"{'cush':>6}{'xmove':>7}{'prem%':>7}{'$prem':>7}{'collat':>10}"
          f"{'IV':>5}{'RV':>5}{'VRP':>5}{'IVR':>7}{'pA%':>5}{'EV$':>6}{'edge':>6}  fits")
    for i, h in enumerate(hits[:25], 1):
        rv = h.get("realized_vol_30d")
        vrp = h.get("vrp")
        rv_str = f"{rv:>5.0f}" if rv is not None else f"{'—':>5}"
        vrp_str = f"{vrp:>+5.0f}" if vrp is not None else f"{'—':>5}"
        ivr = h.get("iv_rank")
        ivr_str = f"{ivr:>3.0f}/{h['iv_rank_days']:<3d}" if ivr is not None else f"{'—':>7}"
        ev = h.get("ev_dollars")
        ev_str = f"{ev:>+6.0f}" if ev is not None else f"{'—':>6}"
        print(f"{i:>2} {h['symbol']:<6}{h['spot']:>9.2f}{h['strike']:>8.0f}"
              f"{h['expiration']:>12}{h['dte']:>4}{h['cushion_pct']:>5.0f}%"
              f"{h['implied_move_pct']:>6.0f}%{h['premium_pct']:>7.2f}"
              f"{h['premium_dollars']:>7}{h['collateral']:>10,}{h['iv']:>5.0f}"
              f"{rv_str}{vrp_str}{ivr_str}{h.get('p_assign_pct', 0):>5.0f}{ev_str}"
              f"{('ACT' if h.get('actionable') else 'BLOCK' if h.get('standing_block') else 'disc' if h.get('discuss') else 'watch' if h.get('edge_ok') else '—'):>6}"
              f"  {'yes' if h['fits_cash'] else 'NO'}")
    print(f"\nVRP = underlying IV − 30d realized vol. edge exists when VRP > {MIN_VRP:g}, but a")
    print(f"candidate is only ACT (surfaced as a trade) when VRP >= {ACTIONABLE_VRP:g} — options")
    print("genuinely rich, not marginally so (RULES.md §1a). A thin-edge name shows 'watch':")
    print("ranked and logged for the back-check, but never pitched as a sell. A name without")
    print("any edge (VRP <= 0) is never actionable regardless of premium size (RULES.md §1).")
    print("IVR = expanding-window IV rank / days observed (0=cheapest, 100=richest this name")
    print("has been). INFORMATIONAL until ~60 days accrue — small windows are weak signals.")
    print_near_misses(out)


def print_near_misses(out, limit=10):
    """What the gates DELETED today. Telemetry, not trades — never pitch one of these.

    A name here produced NO candidate: its best put failed exactly one gate. The point is
    to make a gate that is quietly eating the universe visible. If `cushion` dominates this
    list run after run, the expected-move cushion is scaling with IV faster than premium
    does and is deleting the high-IV names the screen exists to find (RULES.md §1b already
    admits this failure mode, but only rescues names near a 52-week low).
    """
    nm = out.get("near_misses") or []
    if not nm:
        return
    by_gate = {}
    for h in nm:
        by_gate[h["failed_gate"]] = by_gate.get(h["failed_gate"], 0) + 1
    tally = ", ".join(f"{g}: {n}" for g, n in sorted(by_gate.items(), key=lambda x: -x[1]))
    print(f"\n--- NEAR MISSES: {len(nm)} names produced no candidate, each one gate away ({tally}) ---")
    print(f"{'sym':<6}{'strike':>8}{'dte':>4}{'prem%':>7}{'cush':>6}{'req':>6}"
          f"{'IV':>5}{'ATM':>5}{'skew':>6}{'delta':>7}  killed by")
    for h in nm[:limit]:
        print(f"{h['symbol']:<6}{h['strike']:>8.0f}{h['dte']:>4}{h['premium_pct']:>7.2f}"
              f"{h['cushion_pct']:>5.0f}%{h['required_cushion_pct']:>5.0f}%"
              f"{h['iv']:>5.0f}{h['underlying_iv']:>5.0f}{h['skew_pts']:>+6.0f}"
              f"{h['delta']:>7.3f}  {h['failed_gate']}")
    if len(nm) > limit:
        print(f"... and {len(nm) - limit} more (full list: state/near_miss.jsonl)")
    print("NOT candidates and NOT recommendations — this is the audit trail for what the")
    print("gates rejected, so a systematically-wrong gate shows up as data, not silence.")


if __name__ == "__main__":
    print_report(run_screen())
