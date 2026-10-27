"""
Position monitor. Checks open trades and outputs alerts.
Run via cron 3x daily: market open (9:47 AM ET), midday (12:17 PM ET), close (3:47 PM ET).

Exit codes:
  0 = action needed (send notification)
  1 = no action needed
"""
import json
import os
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from shared.marketdata import realized_vol_30d
from scan_log import log_scan, log_alert, log_no_action
from trade_log import load_log
import rules  # canonical thresholds — single source of truth (see RULES.md)
from decision import management_verdict, session_fraction_left
from opportunity import best_redeploy


def _now_et():
    """Now, in US market time. The monitor runs on a Pacific box; the session clock is ET."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return None    # unknown clock -> session_fraction_left returns 1.0 (a full session)

from shared.notifications import post_message


def load_todays_candidates():
    """Today's screener candidates + free cash from last_screen.json, or ([], None).

    Used ONLY to surface opportunity-cost notes on HELD positions (RULES.md §3). Stale
    (not today's) or missing screen → no candidates, so no note is ever surfaced off
    yesterday's market. The monitor never trades on this; it only displays the comparison.
    """
    path = Path(__file__).resolve().parent / "state" / "last_screen.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return [], None
    if data.get("timestamp", "")[:10] != datetime.now().date().isoformat():
        return [], None
    return data.get("candidates", []), data.get("free_cash")


STOP_STREAK_PATH = Path(__file__).resolve().parent / "state" / "stop_streak.json"


def load_stop_streaks():
    """Per-trade count of consecutive monitor runs that saw the 2x mark (RULES.md §4).

    The confirmation guard on the mark-based stop: decision.py CUTs only once the mark
    has persisted STOP_CONFIRM_RUNS runs, so one artifact-inflated deep-OTM mid can't
    realize a fake loss. Keyed by trade id (str). Missing file = no pending stops.
    """
    try:
        return json.loads(STOP_STREAK_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_stop_streaks(streaks):
    STOP_STREAK_PATH.write_text(json.dumps(streaks, indent=2))


def check_position(client, trade, candidates=(), free_cash=None, stop_streak=0):
    """Check a single open trade and return status + any alerts.

    All thresholds come from rules.py (the single source of truth); the reasoning
    and citations live in RULES.md. Do not hardcode rule numbers here.

    Sets result["do"] ∈ {CLOSE, WORK, CUT, HOLD} — the single verdict the renderer
    (slack_format.py) transcribes verbatim. Nothing re-derives
    it. The canonical tastytrade triad, in priority order (values from rules.py):
    - put >= STOP_MULTIPLE × credit → CUT (2x-credit stop)
    - within STRIKE_PROXIMITY_PCT of strike → CUT (assignment risk)
    - >= PROFIT_TARGET_PCT of max profit → CLOSE (the 50% target — primary exit)
    - DTE <= MANAGE_DTE → CLOSE if up at the ask too; WORK (rest a limit, with the
      modelled odds it fills today) if the win is inside the spread; HOLD a far-OTM
      loser (time alone is not a cut — the downside is owned by the stop + proximity
      gates above). See MANAGE_DTE_CUTS_LOSERS.
    - otherwise → HOLD

    WORK is an ACTION, not a hold: it means place the limit and see if it hits. It is
    deliberately not folded into HOLD — the 2026-08-03 correction is that a target a few
    cents away must reach the account owner as an order to place, never as silence.

    Earnings is NOT handled here as a close trigger — a deep-cushion put is held
    through the print to harvest the IV crush (RULES.md §5). That override is the
    judgment layer's call, logged, not this script's.
    """
    symbol = trade["symbol"]
    sell_strike = trade["sell_strike"]
    # per-share credit: trade["credit"] is TOTAL dollars across all contracts
    # (fixed 2026-07-07 for the first multi-contract position — /100 assumed 1 contract)
    credit = trade["credit"] / (100 * trade["contracts"])

    # Get underlying price
    resp = client.get_quotes([symbol])
    resp.raise_for_status()
    q = resp.json()[symbol]["quote"]
    price = q["lastPrice"]
    change_pct = q.get("netPercentChange", 0)

    # Get current put value. Query just the expiration we hold — a strike_count
    # window around the money misses deep-OTM strikes, and the screener now opens
    # positions 20-30% out of the money, far below the at-the-money band.
    target_exp = trade.get("expiration", "")[:10]  # "2026-06-26"
    exp_date = datetime.strptime(target_exp, "%Y-%m-%d").date()
    resp2 = client.get_option_chain(
        symbol=symbol,
        contract_type=client.Options.ContractType.PUT,
        from_date=exp_date,
        to_date=exp_date,
    )
    resp2.raise_for_status()
    chain = resp2.json()

    current_mid = None
    current_bid = None
    current_ask = None
    delta = None
    dte = None

    for exp, sd in chain.get("putExpDateMap", {}).items():
        for sk, cl in sd.items():
            for c in cl:
                contract_exp = c.get("expirationDate", "")[:10]
                if abs(c["strikePrice"] - sell_strike) < 0.01 and contract_exp == target_exp:
                    current_bid = c["bid"]
                    current_ask = c["ask"]
                    current_mid = (current_bid + current_ask) / 2
                    dte = c["daysToExpiration"]
                    # Delta feeds the fill-odds estimate (decision.fill_odds_today): it is
                    # how a needed drop in the OPTION's offer translates into a move in the
                    # UNDERLYING, which is the thing we have a vol estimate for. Schwab
                    # sends -999 when it has no greek — same sentinel screener_select
                    # filters, and passing it through would fabricate a confident number.
                    raw_delta = c.get("delta")
                    if raw_delta is not None and raw_delta > -999:
                        delta = raw_delta

    if current_mid is None:
        return {"alert": False, "message": f"Could not find {symbol} ${sell_strike} put pricing."}

    contracts = trade["contracts"]
    # P&L + the canonical verdict come from the pure core (decision.py), which
    # monitor and the backtest share so the rule is never reimplemented.
    # Inputs for the fill-odds estimate. RV is the same trailing 30d measure the screener's
    # VRP uses; it fails soft to None (odds simply go unstated) rather than taking down a
    # position check over a vol lookup.
    try:
        rv_annual = realized_vol_30d(client, symbol)
    except Exception:
        rv_annual = None
    v = management_verdict(
        credit=credit, current_mid=current_mid, current_ask=current_ask,
        delta=delta, rv_annual=rv_annual,
        session_left_frac=session_fraction_left(_now_et()),
        price=price, sell_strike=sell_strike,
        dte=dte, days_in_trade=(datetime.now().date() - datetime.fromisoformat(trade["opened"]).date()).days,
        contracts=contracts,
        entry_vix=trade.get("entry_vix"),  # None (legacy trades) = stop active, conservative
        stop_streak=stop_streak,
    )
    pnl = v["pnl"]
    pct_of_max = v["pct_of_max"]
    annualized_return = v["annualized_return"]

    # Cushion: how far the stock has to fall to reach the strike.
    cushion_pct = (price - sell_strike) / price * 100 if price else 0

    # Hold-to-expiry $/day: the premium still left to capture (what you'd pay to
    # close now) spread over the days left. Theta is back-loaded, so the early
    # days run below this and the final two weeks above it — it's the average.
    # This is the number an opportunity-exit must be measured against: closing
    # only makes sense if freed capital can beat it. Idle cash can't.
    remaining_per_day = (current_ask * 100 * contracts / dte) if dte else 0

    # Calculate time metrics
    opened_date = datetime.fromisoformat(trade["opened"]).date()
    exp_date = datetime.strptime(target_exp, "%Y-%m-%d").date()
    today = datetime.now().date()

    total_trade_days = max((exp_date - opened_date).days, 1)
    days_in_trade = (today - opened_date).days
    pct_time_elapsed = days_in_trade / total_trade_days * 100

    # The standing-order pair (RULES.md §3): on fill you set a GTC buy-to-close at the
    # 50% mark so the winner closes itself; on the 21-DTE date you cancel it and manage
    # by hand. credit is already per-share, so gtc_price is the buy-to-close limit.
    gtc_price = round(credit * rules.PROFIT_TARGET_PCT / 100, 2)
    manage_date = (exp_date - timedelta(days=rules.MANAGE_DTE)).isoformat()

    result = {
        "symbol": symbol,
        "price": price,
        "change_pct": change_pct,
        "strike": sell_strike,
        "credit": credit,
        "current_mid": current_mid,
        "current_ask": current_ask,
        "dte": dte,
        "pnl": pnl,
        "pct_of_max": pct_of_max,
        "cushion_pct": cushion_pct,
        "remaining_per_day": remaining_per_day,
        "days_in_trade": days_in_trade,
        "pct_time_elapsed": pct_time_elapsed,
        "annualized_return": annualized_return,
        "gtc_price": gtc_price,
        "manage_date": manage_date,
        "do": v["do"],          # single verdict from decision.py; renderers transcribe it
        "alert": v["alert"],
        "actions": list(v["actions"]),
        "stop_streak": v["stop_streak"],  # caller persists (state/stop_streak.json)
    }

    # Opportunity cost (RULES.md §3): for a position we're HOLDING, surface — never act
    # on — whether the day's screener has a materially better, positive-edge home for the
    # collateral this hold ties up. Advisory only: it does not flip `do` or `alert`; the
    # close stays a logged judgment call. The hold's "premium still at stake" is its
    # current mid (what holding to a clean OTM expiry recovers vs closing now).
    if result["do"] == "HOLD" and candidates:
        rd = best_redeploy(
            held={"symbol": symbol, "current_mid": current_mid, "strike": sell_strike,
                  "dte": dte, "contracts": contracts},
            candidates=candidates, free_cash=free_cash,
            beat_ratio=rules.REDEPLOY_BEAT_RATIO,
        )
        if rd:
            result["actions"].append(
                f"OPPORTUNITY — holding earns ~{rd['hold_yield_pct']:.0f}%/yr on the "
                f"${sell_strike * 100 * contracts:,.0f} it ties up; today's screener has "
                f"{rd['symbol']} ${rd['strike']:g}p ({rd['dte']} DTE, VRP {rd['vrp']:+.0f}, "
                f"{rd['p_assign_pct']:.0f}% assign) at ~{rd['cand_yield_pct']:.0f}%/yr "
                f"(~{rd['beats_by']:.1f}x) that fits the freed cash. Weigh closing to redeploy "
                f"— judgment call, log it (RULES.md §3)."
            )

    # else: result["do"] stays "HOLD" — below target, outside the gamma window, no risk flag.
    return result


def format_report(results):
    """Format a monitoring report."""
    now = datetime.now()
    lines = [f"=== TRADE MONITOR {now.strftime('%Y-%m-%d %H:%M')} ===", ""]

    any_alert = False
    for r in results:
        if "symbol" not in r:
            lines.append(r.get("message", "Unknown"))
            continue

        status = r.get("do", "HOLD")
        dit = r.get("days_in_trade", "?")
        pte = r.get("pct_time_elapsed")
        time_str = f"Day {dit}" + (f" ({pte:.0f}% elapsed)" if pte is not None else "")
        # Show the ask next to the mid so an indicative midpoint is not mistaken
        # for an immediately executable buy-to-close price.
        ask = r.get("current_ask")
        put_s = (f"${r['current_mid']:.2f} mid / ${ask:.2f} ask" if ask is not None
                 else f"${r['current_mid']:.2f} mid")
        lines.append(
            f"{r['symbol']} ${r['strike']} put | "
            f"Stock: ${r['price']:.2f} ({r['change_pct']:+.1f}%) | "
            f"Put: {put_s} (sold ${r['credit']:.2f}) | "
            f"P&L: ${r['pnl']:+,.0f} ({r['pct_of_max']:.0f}% of max) | "
            f"DTE: {r.get('dte', '?')} | {time_str} | "
            f"[{status}]"
        )
        if r.get("gtc_price") is not None:
            lines.append(
                f"  GTC buy-to-close ${r['gtc_price']:.2f} (50% mark) | "
                f"cancel & manage {r.get('manage_date', '?')} (21 DTE)"
            )
        for action in r.get("actions", []):
            lines.append(f"  >>> {action}")
        # any_alert follows the verdict's own flag, not the mere presence of a reason
        # line: a HOLD can carry an explanatory note (e.g. "held past the 21-DTE timer,
        # far OTM") without it being an action that needs a notification.
        if r.get("alert"):
            any_alert = True
        lines.append("")

    if not any_alert:
        lines.append("No action needed. Positions are fine.")

    return "\n".join(lines), any_alert


def send_slack(message):
    """Explicit notification helper; safe errors never include a webhook URL."""
    if not post_message(message):
        print("Notification not delivered; check optional Slack configuration/network.")


def run_monitor():
    client = get_client()
    log = load_log()
    open_trades = [t for t in log["trades"] if t["status"] == "open"]

    if not open_trades:
        print("No open trades to monitor.")
        return 1

    candidates, free_cash = load_todays_candidates()
    streaks = load_stop_streaks()
    results = []
    for trade in open_trades:
        tid = str(trade["id"])
        result = check_position(client, trade, candidates=candidates, free_cash=free_cash,
                                stop_streak=streaks.get(tid, 0))
        if "stop_streak" in result:
            streaks[tid] = result["stop_streak"]
        results.append(result)
    # keep only open trades — a closed trade's pending stop must not leak to a reused id
    save_stop_streaks({str(t["id"]): streaks.get(str(t["id"]), 0) for t in open_trades})

    report, any_alert = format_report(results)
    print(report)

    # Log every check
    for r in results:
        if "symbol" in r:
            log_scan("monitor", {
                "symbol": r["symbol"],
                "stock_price": r["price"],
                "stock_change": r["change_pct"],
                "strike": r["strike"],
                "credit_sold": r["credit"],
                "current_mid": r["current_mid"],
                "current_ask": r["current_ask"],
                "position_pnl": r["pnl"],
                "pct_of_max": r["pct_of_max"],
                "dte": r.get("dte"),
                "do": r.get("do", "HOLD"),
                "stop_streak": r.get("stop_streak"),
                "gtc_price": r.get("gtc_price"),
                "manage_date": r.get("manage_date"),
                "alert": r["alert"],
                "actions": r.get("actions", []),
            })

    if any_alert:
        # DO NOT send Slack from here. Scripts output data only.
        # Claude reads the output, applies judgment, and sends Slack directly.
        log_alert(report, sent_slack=False)
    else:
        pnl_summary = ", ".join(f"{r['symbol']} ${r.get('pnl', 0):+.0f}" for r in results if "symbol" in r)
        log_no_action(f"Positions fine: {pnl_summary}")

    return 0 if any_alert else 1


if __name__ == "__main__":
    sys.exit(run_monitor())
