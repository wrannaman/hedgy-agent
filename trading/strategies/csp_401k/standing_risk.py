"""Standing per-symbol risk gates — the two things the daily agent must not re-decide.

Both gates exist for the same reason: a fact that is true on Monday and still true on
Friday was being re-adjudicated from scratch every morning by whichever agent ran the
cron, and the answer drifted. SPCX is the worked example — dropped on the same
Colossus 2 disqualifier on 07-28, 07-29 and twice on 07-31, then surfaced as ACT on
08-03 with the disqualifier declared "lifted" on mitigation news that did not meet the
bar written for it. Same numbers, opposite verdict, five days apart. That is not
judgment, it is variance in who read the rulebook that morning.

So both gates are DATA (`standing_risk.json`, tracked in git) plus CODE (this module,
called by `screener.py`), not prose an agent re-interprets:

1. **Standing disqualifiers** — a confirmed company-specific risk (RULES.md §4) with a
   pre-written, falsifiable `clears_when` bar. The gate holds until that exact bar is
   met and a human sets `cleared`. An agent may ADD one; it may never clear one. This
   is Kydland-Prescott rules-over-discretion applied to the one decision where the
   agent has a standing incentive to defect: the disqualified name is usually the
   richest thing on the board, so "re-check whether it's still bad" reliably decays
   into "find a reading under which it is fine".

2. **Scheduled share-supply events** — an IPO lockup expiry, a secondary, or an
   index deletion dated inside the contract's life. RULES.md §5 blesses selling
   *through* earnings because the post-print IV crush is the harvest. A supply event
   has no such payoff: the shares arrive, and the premium you sold does not crush on
   a schedule you get paid for. Blocking these keeps §5 from being read as "all
   dated events are fine, IV already prices them".

Neither gate rejects a name outright — both demote ACT to WATCH with a `watch_reason`,
the same mechanism the no-chase guard uses. The name stays ranked, logged and visible;
it just never reaches the account owner as a "sell this".
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STANDING_RISK_PATH = HERE / "standing_risk.json"


def configured_risk_path():
    explicit = os.environ.get("HEDGY_STANDING_RISK_CONFIG")
    if explicit:
        return Path(explicit)
    local = HERE / "standing_risk.local.json"
    return local if local.exists() else STANDING_RISK_PATH


def _parse_date(value):
    """'YYYY-MM-DD' (or an ISO datetime) -> date; None on anything unparseable."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip()[:10]).date()
    except ValueError:
        return None


def load_standing_risk(path: Path | None = None) -> dict:
    """Read standing_risk.json. A missing/corrupt file yields empty gates, never a crash.

    Deliberately fail-open: this module is called from inside the screener's per-name
    loop, and a typo in the JSON must not take down the whole morning run. The cost of
    failing open is a missed gate for one session; the cost of failing closed is no
    screen at all. `standing_risk_health()` surfaces the breakage so it is not silent.
    """
    try:
        data = json.loads((path or configured_risk_path()).read_text())
    except Exception:
        return {"disqualifiers": [], "supply_events": [], "load_error": True}
    return {
        "disqualifiers": data.get("disqualifiers") or [],
        "supply_events": data.get("supply_events") or [],
        "load_error": False,
    }


def active_disqualifier(symbol: str, risk: dict | None = None) -> dict | None:
    """The uncleared standing disqualifier for `symbol`, or None.

    `cleared` is the only thing that lifts it, and only a human writes that field
    (RULES.md §5b). Anything else in the record — including a `checked` log full of
    encouraging findings — leaves the gate closed.
    """
    risk = risk if risk is not None else load_standing_risk()
    for entry in risk.get("disqualifiers", []):
        if str(entry.get("symbol", "")).upper() != symbol.upper():
            continue
        if not entry.get("cleared"):
            return entry
    return None


def supply_events_in_window(symbol: str, expiration, today=None, risk: dict | None = None) -> list[dict]:
    """Scheduled share-supply events falling in [today, expiration] for `symbol`.

    Inclusive of both ends: an event ON expiration day still lands while the contract
    is alive, and an event today has not been absorbed by the tape yet.
    """
    risk = risk if risk is not None else load_standing_risk()
    today = today or date.today()
    exp = _parse_date(expiration)
    if exp is None:
        return []
    hits = []
    for entry in risk.get("supply_events", []):
        if str(entry.get("symbol", "")).upper() != symbol.upper():
            continue
        when = _parse_date(entry.get("date"))
        if when is not None and today <= when <= exp:
            hits.append(entry)
    return sorted(hits, key=lambda e: str(e.get("date")))


def standing_block(symbol: str, expiration, today=None, risk: dict | None = None) -> str | None:
    """One reason string if this symbol/expiration is blocked from ACT, else None.

    Disqualifier first — it is the more serious of the two and reads better as the
    headline when both fire.
    """
    risk = risk if risk is not None else load_standing_risk()
    dq = active_disqualifier(symbol, risk)
    if dq is not None:
        return (f"standing disqualifier since {dq.get('opened', '?')}: {dq.get('reason', 'unspecified')} "
                f"Clears only when: {dq.get('clears_when', 'unspecified')} (RULES.md §5b)")
    events = supply_events_in_window(symbol, expiration, today=today, risk=risk)
    if events:
        listed = "; ".join(
            f"{e.get('date')} {str(e.get('kind', 'supply event')).replace('_', ' ')}"
            f"{' — ' + e['note'] if e.get('note') else ''}"
            for e in events)
        return (f"scheduled share-supply event inside the contract ({listed}) — no IV-crush "
                f"harvest to pay for it, unlike earnings (RULES.md §5a)")
    return None


def standing_risk_health(risk: dict | None = None) -> str | None:
    """A warning line if the file failed to load, else None. Keeps a typo from being silent."""
    risk = risk if risk is not None else load_standing_risk()
    if risk.get("load_error"):
        return (f"WARNING: {STANDING_RISK_PATH.name} failed to parse — standing disqualifier and "
                f"supply-event gates are NOT being applied this run (RULES.md §5a/§5b)")
    return None


if __name__ == "__main__":
    import sys

    risk = load_standing_risk()
    warning = standing_risk_health(risk)
    if warning:
        print(warning)
        sys.exit(1)
    print(f"{STANDING_RISK_PATH.name}: {len(risk['disqualifiers'])} disqualifier(s), "
          f"{len(risk['supply_events'])} supply event(s)")
    for entry in risk["disqualifiers"]:
        state = "CLEARED" if entry.get("cleared") else "ACTIVE"
        print(f"  [{state}] {entry.get('symbol')} since {entry.get('opened')}")
        print(f"      clears when: {entry.get('clears_when')}")
    for entry in risk["supply_events"]:
        print(f"  [{entry.get('date')}] {entry.get('symbol')} {entry.get('kind')}")
    if len(sys.argv) > 2:
        symbol, expiration = sys.argv[1], sys.argv[2]
        blocked = standing_block(symbol, expiration)
        print(f"\n{symbol} exp {expiration}: {'BLOCKED — ' + blocked if blocked else 'no standing block'}")
