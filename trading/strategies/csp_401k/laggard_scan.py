"""
laggard_scan.py — the willing-owner laggard surfacer (dry-day idea generator).

The put screener answers "is any option rich enough to sell today?" This answers a
different research question: "which quality
names are the market hating right now — beaten down on sentiment, not broken — that
we'd be genuinely happy to own cheaper?" (the 2026-07-06 MSFT/META conversation).

It ranks a CURATED willing-owner set (quality large-caps only — no meme, crypto
proxies, space, China ADRs, or leveraged ETFs; getting assigned one of those fails
the willing-owner gate) by trailing 6- and 12-month return, and flags the names
underperforming the peer median by a wide margin. For the top laggards it also pulls
the best put via the SAME screener logic (screener.best_put), so the surfaced note is
honest about whether a tradeable option even exists at a safe cushion.

IMPORTANT — this is an IDEA surfacer, never an auto-trade. A laggard is a WATCH:
- It does NOT loosen any gate. The VRP / cushion / actionable rules still decide.
- "Down a lot" is not "safe": elevated realized vol means another big move is very
  much in range. The scanner prints RV and the put's cushion-vs-implied-move so the
  reader can see that, instead of assuming the drop is a floor.
- The output feeds the morning recap as a discuss line on DRY screener days, tilting
  the hunt toward willing-owner names — it is the WORLDVIEW "willing-owner laggards"
  hook made mechanical. Acting on one is always a live human call.

Recommendation-only, read-only. Writes state/laggards.json + state/laggards.txt.
"""
import sys, json, math, statistics
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared.auth import get_client
from shared.universe import display_name
from shared.marketdata import realized_vol_30d

STATE = Path(__file__).resolve().parent / "state"
STATE.mkdir(exist_ok=True)

# Curated willing-owner set: quality large-caps we'd be content owning at a discount.
# Deliberately a SUBSET of shared.universe.UNIVERSE — the speculative buckets (meme,
# crypto proxies, new-space, China ADRs, leveraged/ARKK) are excluded on purpose: a
# beaten-down lottery ticket is not a "park cash safely" name, it's just a falling
# knife. Edit here when the willing-owner thesis genuinely changes.
WILLING_OWNER = [
    # mega / large tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "NFLX", "ORCL",
    "CRM", "ADBE", "CSCO", "QCOM", "TXN",
    # quality semis (own the leaders, not the lottery tickets)
    "AMD", "TSM", "ASML", "AMAT", "KLAC", "LRCX", "ADI", "ANET",
    # quality software / platforms
    "NOW", "PANW", "CRWD", "UBER", "ABNB",
    # healthcare / pharma
    "LLY", "UNH", "JNJ", "MRK", "ABBV", "AMGN", "VRTX", "GILD",
    # financials
    "JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "SCHW", "BLK",
    # consumer / staples / defensives
    "WMT", "COST", "HD", "MCD", "SBUX", "NKE", "DIS", "KO", "PEP",
    # energy
    "XOM", "CVX",
    # data-center buildout / skilled-labor infrastructure (WORLDVIEW T2) — the
    # durable ones only: FIX excluded on per-contract size (~$150k collateral at
    # 2026-07 prices), VRT/CARR/HUBB on the T1 quality bar. Universe-only names
    # still get screened; they just can't reach the discuss tier.
    "ETN", "PWR", "EME", "TT", "WSO",
]

LAGGARD_LOOKBACK_DAYS = 126   # ~6 trailing months — the primary underperformance window
LAGGARD_GAP_PCT = 15.0        # flag names trailing the peer MEDIAN 6m return by >= this
TOP_N_WITH_PUTS = 3           # pull the option chain only for the N worst (limit I/O)


def daily_closes(client, symbol):
    r = client.get_price_history_every_day(symbol=symbol)
    r.raise_for_status()
    return [c["close"] for c in r.json().get("candles", [])]


def _ret(closes, n):
    """Trailing return over n trading days, as a percentage, or None if too short."""
    if len(closes) <= n:
        return None
    return round((closes[-1] / closes[-n - 1] - 1) * 100, 1)


def run():
    client = get_client()
    rows = []
    for sym in WILLING_OWNER:
        try:
            closes = daily_closes(client, sym)
        except Exception as e:
            print(f"  {sym}: price history failed ({e}) — skipped", file=sys.stderr)
            continue
        if len(closes) < LAGGARD_LOOKBACK_DAYS + 1:
            continue
        spot = closes[-1]
        hi_252 = max(closes[-252:]) if len(closes) >= 252 else max(closes)
        rows.append({
            "symbol": sym,
            "name": display_name(sym),
            "spot": round(spot, 2),
            "ret_3m": _ret(closes, 63),
            "ret_6m": _ret(closes, LAGGARD_LOOKBACK_DAYS),
            "ret_12m": _ret(closes, 252),
            "off_high_pct": round((spot - hi_252) / hi_252 * 100, 1),
        })

    if not rows:
        raise RuntimeError("no willing-owner names priced — cannot rank laggards")

    med_6m = statistics.median([r["ret_6m"] for r in rows if r["ret_6m"] is not None])
    for r in rows:
        r["gap_vs_peers"] = (round(r["ret_6m"] - med_6m, 1)
                             if r["ret_6m"] is not None else None)
        # A laggard = materially below the peer median over 6 months. This is the account owner's
        # exact framing ("underperforming everyone else"), made a number.
        r["is_laggard"] = (r["gap_vs_peers"] is not None
                           and r["gap_vs_peers"] <= -LAGGARD_GAP_PCT)

    rows.sort(key=lambda r: (r["ret_6m"] if r["ret_6m"] is not None else 999))
    laggards = [r for r in rows if r["is_laggard"]]

    # For the worst few, attach the put reality via the canonical screener logic so
    # the surfaced note can't imply a trade exists when the cushion/edge isn't there.
    from screener import best_put
    for r in laggards[:TOP_N_WITH_PUTS]:
        try:
            best, _, _ = best_put(client, r["symbol"])
        except Exception as e:
            best = None
            r["put_error"] = str(e)
        r["rv_30d"] = realized_vol_30d(client, r["symbol"])
        if best is None:
            r["put"] = None
            r["put_note"] = ("no put clears the strict cushion/premium gate — "
                             "strike that would be safe pays too little")
        else:
            r["put"] = {k: best.get(k) for k in
                        ("strike", "dte", "mid", "cushion_pct", "premium_pct",
                         "vrp", "vrp_ratio", "edge_ok", "actionable",
                         "p_assign_pct", "fits_cash")}

    out = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "peer_median_6m": round(med_6m, 1),
        "universe_size": len(rows),
        "laggard_gap_pct": LAGGARD_GAP_PCT,
        "laggards": laggards,
        "ranked": rows,
    }
    (STATE / "laggards.json").write_text(json.dumps(out, indent=2))
    (STATE / "laggards.txt").write_text(render(out))
    print(render(out))
    return out


def render(out):
    lines = [f"WILLING-OWNER LAGGARDS — {out['date']}  "
             f"(peer 6m median {out['peer_median_6m']:+.1f}%, "
             f"flag = trailing peers by {out['laggard_gap_pct']:.0f}%+)"]
    if not out["laggards"]:
        lines.append("  none — no quality name is badly out of step with its peers today.")
        return "\n".join(lines)
    for r in out["laggards"]:
        head = (f"  {r['name']} — {r['ret_6m']:+.0f}% 6mo "
                f"({r['gap_vs_peers']:+.0f}% vs peers), {r['off_high_pct']:+.0f}% off high")
        lines.append(head)
        put = r.get("put")
        if "put" in r and put is None:
            lines.append(f"      put: {r.get('put_note','none')}")
        elif put:
            edge = "ACTIONABLE" if put["actionable"] else ("edge" if put["edge_ok"] else "NO edge")
            rv = r.get("rv_30d")
            lines.append(
                f"      best put ${put['strike']:g} ({put['dte']}d): {put['cushion_pct']:.0f}% cushion, "
                f"${put['mid']*100:.0f}, ~{put['p_assign_pct']:.0f}% assign, VRP {put['vrp']:+.1f} [{edge}]"
                + (f", stock vol {rv:.0f}%" if rv else ""))
    lines.append("  (WATCH only — willing-owner idea, not a trade. Gates still decide; "
                 "a big drop is not a floor.)")
    return "\n".join(lines)


if __name__ == "__main__":
    run()
