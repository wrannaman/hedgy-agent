"""
judge.py — the pre-send gate (FUND.md §6).

The morning engine ranks sleeve survivors into a brief, then the agent composes ONE
Slack message from it. The judge sits between: it re-checks every surfaced short-premium
trade against the active RISK DIAL (fund_rules.RISK_DIALS) and emits a one-line verdict +
terse WHY for each. Nothing here places or blocks an order — it decides what is allowed to
SURFACE, and documents why, so a thin trade is either killed or surfaced-with-a-warning,
never quietly sold.

Why it exists: the sleeve scanners gate on their own mechanics (e.g. index_vrp sells a
~30-delta spread, whose cushion is ~4% at high IV by construction). The dial is the
book-wide posture on top of that — "how hot do I think the market is right now." Defensive
demands real cushion; aggressive lets the raw sleeve through. One knob, one source of truth.

SCOPE — deliberate. The dial governs the INDEX-VRP sleeve (taxable, recommendation-only
short premium), and any future taxable short-premium sleeve. It does NOT re-gate:
  - the csp_401k single-name PUT sleeve — it runs independently with its OWN canonical
    verdict (RULES.md, the tastytrade triad); double-gating it from here would create two
    verdicts that disagree on the same position. The dial header still PRINTS as awareness;
    the put verdict stays the sleeve's.
  - the PEAD sleeve — long-only post-earnings drift, no short strike and no cushion, so a
    cushion/VRP floor is meaningless for it.
"""
import json
from pathlib import Path

import fund_rules as R

_POSTURE_FILE = Path(__file__).resolve().parent / "state" / "risk_posture.json"

_DEFAULT_OUTLOOK = "No outlook set — using the default posture floors."


def load_posture():
    """Current risk posture: {dial, cfg, outlook, set_date, set_by}.

    Reads state/risk_posture.json (editable data, no code change to re-dial). Falls back to
    fund_rules.DEFAULT_DIAL on any problem — a missing/garbled file must NOT silently drop
    the floors to nothing, so the fallback is the conservative default, never 'aggressive'.
    """
    dial, outlook, set_date, set_by = R.DEFAULT_DIAL, _DEFAULT_OUTLOOK, None, None
    try:
        d = json.loads(_POSTURE_FILE.read_text())
        cand = str(d.get("dial", "")).lower()
        if cand in R.RISK_DIALS:
            dial = cand
        outlook = d.get("outlook") or outlook
        set_date, set_by = d.get("set_date"), d.get("set_by")
    except Exception:
        pass
    return {"dial": dial, "cfg": R.RISK_DIALS[dial], "outlook": outlook,
            "set_date": set_date, "set_by": set_by}


def judge_spread(cand, cfg):
    """Judge one index-VRP put-spread candidate against the dial floors.

    Returns {verdict, why} where verdict is 'surfaced' | 'flagged' | 'killed'.
    Expects cand to carry cushion_pct and (optionally) vrp — the fields index_vrp/scan.py
    already writes. A candidate missing cushion data is FLAGGED, not trusted.
    """
    cushion = cand.get("cushion_pct")
    vrp = cand.get("vrp")
    sym = cand.get("symbol", "?")
    # Defined-risk spreads judge against their own (lower) cushion floor: a ~30-delta
    # spread has 3-4% cushion by construction and its tail is capped by the wing, so the
    # naked-put floor was a structural ban at NEUTRAL (see fund_rules.RISK_DIALS note).
    if cand.get("strategy") == "put_spread":
        floor_c = cfg.get("min_cushion_pct_defined", cfg["min_cushion_pct"])
    else:
        floor_c = cfg["min_cushion_pct"]
    floor_v = cfg["min_vrp"]

    if cushion is None:
        return {"verdict": "flagged", "why": f"{sym}: no cushion data — verify manually before trusting"}

    if cushion < floor_c:
        return {"verdict": "killed",
                "why": f"{sym}: cushion {cushion:.1f}% below the {floor_c:.0f}% floor for this posture"}
    if vrp is not None and vrp < floor_v:
        return {"verdict": "killed",
                "why": f"{sym}: VRP {vrp:+.0f} below the +{floor_v:.0f} edge floor for this posture"}

    if cushion < floor_c + R.DIAL_FLAG_MARGIN_PCT:
        return {"verdict": "flagged",
                "why": f"{sym}: cushion {cushion:.1f}% only just clears the {floor_c:.0f}% floor — thin, size small"}

    extra = f", VRP {vrp:+.0f}" if vrp is not None else ""
    return {"verdict": "surfaced", "why": f"{sym}: cushion {cushion:.1f}%{extra} clears the {floor_c:.0f}% floor"}


def partition_spreads(cands, cfg):
    """Split surfaced spread candidates into (surfaced, flagged, killed), each item a
    dict {cand, why}. 'surfaced' includes flagged trades (they still reach the account owner, labeled);
    'flagged' is a separate list so the brief can mark them. 'killed' never surfaces.
    """
    surfaced, flagged, killed = [], [], []
    for c in cands:
        v = judge_spread(c, cfg)
        item = {"cand": c, "why": v["why"]}
        if v["verdict"] == "killed":
            killed.append(item)
        elif v["verdict"] == "flagged":
            flagged.append(item); surfaced.append(item)
        else:
            surfaced.append(item)
    return surfaced, flagged, killed


def dial_header(posture):
    """The one-line RISK DIAL banner for the top of the brief (and the Slack message)."""
    cfg = posture["cfg"]
    stamp = f" (set {posture['set_date']})" if posture.get("set_date") else ""
    defined = cfg.get("min_cushion_pct_defined", cfg["min_cushion_pct"])
    return (f"RISK DIAL: {posture['dial'].upper()}{stamp} — "
            f"min cushion {cfg['min_cushion_pct']:.0f}% naked / {defined:.1f}% defined-risk, "
            f"min VRP +{cfg['min_vrp']:.0f}\n"
            f"  Outlook: {posture['outlook']}")
