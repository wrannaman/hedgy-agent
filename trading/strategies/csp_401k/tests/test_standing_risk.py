"""Synthetic standing-risk fixtures pin verdict stability and local configuration.

A disqualifier must remain blocked until explicitly cleared; a supply event must
remain blocked inside its dated window. Tests exercise both independently.
"""

import json
from datetime import date

import pytest

from standing_risk import (
    active_disqualifier,
    load_standing_risk,
    standing_block,
    standing_risk_health,
    supply_events_in_window,
)

RISK = {
    "disqualifiers": [
        {"symbol": "SPCX", "opened": "2026-07-28", "reason": "Colossus 2 suit.",
         "clears_when": "Dismissed, settled, or turbines permitted.", "cleared": False},
        {"symbol": "OLDCO", "opened": "2026-01-01", "reason": "resolved thing.",
         "clears_when": "settled", "cleared": True},
    ],
    "supply_events": [
        {"symbol": "SPCX", "date": "2026-08-06", "kind": "ipo_lockup", "note": "~$116B unlock"},
        {"symbol": "ACME", "date": "2026-12-01", "kind": "secondary"},
    ],
    "load_error": False,
}


# --- disqualifiers ---------------------------------------------------------

def test_uncleared_disqualifier_blocks():
    assert active_disqualifier("SPCX", RISK) is not None
    assert standing_block("SPCX", "2026-09-04", today=date(2026, 8, 3), risk=RISK)


def test_cleared_disqualifier_does_not_block():
    assert active_disqualifier("OLDCO", RISK) is None
    assert standing_block("OLDCO", "2026-09-04", today=date(2026, 8, 3), risk=RISK) is None


def test_disqualifier_is_case_insensitive():
    assert active_disqualifier("spcx", RISK) is not None


def test_disqualifier_ignores_expiration_entirely():
    """It is a fact about the company, not the contract — no expiry escapes it."""
    for exp in ("2026-08-07", "2026-09-04", "2027-01-15"):
        assert standing_block("SPCX", exp, today=date(2026, 8, 3), risk=RISK)


def test_disqualifier_reason_names_the_clearing_bar():
    """The block must carry its own falsification test, so the next reader can't invent one."""
    reason = standing_block("SPCX", "2026-09-04", today=date(2026, 8, 3), risk=RISK)
    assert "Clears only when" in reason
    assert "turbines permitted" in reason


def test_encouraging_check_notes_do_not_clear_it():
    """§5b: mitigation logged under `checked` changes nothing while `cleared` is false."""
    risk = json.loads(json.dumps(RISK))
    risk["disqualifiers"][0]["checked"] = [
        {"date": "2026-08-03", "finding": "DOJ backing SpaceX, removal schedule agreed"}]
    assert standing_block("SPCX", "2026-09-04", today=date(2026, 8, 3), risk=risk)


# --- supply events ---------------------------------------------------------

def test_supply_event_inside_contract_blocks():
    reason = standing_block("ACME", "2026-12-15", today=date(2026, 11, 1), risk=RISK)
    assert reason and "supply" in reason and "2026-12-01" in reason


def test_supply_event_after_expiration_does_not_block():
    assert standing_block("ACME", "2026-11-20", today=date(2026, 11, 1), risk=RISK) is None


def test_supply_event_already_past_does_not_block():
    """Once the shares have landed the overhang is in the tape — this is the re-entry path."""
    assert standing_block("ACME", "2027-01-15", today=date(2026, 12, 2), risk=RISK) is None


def test_supply_event_on_boundary_days_blocks():
    """Inclusive both ends: an unlock today isn't absorbed yet; one on expiry day still lands."""
    assert supply_events_in_window("ACME", "2026-12-01", today=date(2026, 12, 1), risk=RISK)
    assert supply_events_in_window("ACME", "2026-12-01", today=date(2026, 11, 1), risk=RISK)


def test_unlisted_symbol_is_free():
    assert standing_block("NVDA", "2026-09-04", today=date(2026, 8, 3), risk=RISK) is None


# --- simultaneous independent risk gates -------------------------------------------

def test_fixture_candidate_is_blocked_twice_over():
    """A candidate with two independent blocks remains blocked until both resolve."""
    today, expiration = date(2026, 8, 3), "2026-09-04"
    assert standing_block("SPCX", expiration, today=today, risk=RISK)
    # ...and it would STILL be blocked on the supply event alone if the suit resolved.
    risk = json.loads(json.dumps(RISK))
    risk["disqualifiers"][0]["cleared"] = True
    reason = standing_block("SPCX", expiration, today=today, risk=risk)
    assert reason and "ipo lockup" in reason


def test_spcx_reopens_after_the_unlock_once_the_suit_clears():
    """Both gates are exits, not bans: past 8/6 with the suit cleared, nothing holds."""
    risk = json.loads(json.dumps(RISK))
    risk["disqualifiers"][0]["cleared"] = True
    assert standing_block("SPCX", "2026-09-18", today=date(2026, 8, 10), risk=risk) is None


# --- failure modes ---------------------------------------------------------

def test_bad_expiration_never_crashes_the_sweep():
    assert standing_block("ACME", "not-a-date", today=date(2026, 11, 1), risk=RISK) is None
    assert standing_block("ACME", None, today=date(2026, 11, 1), risk=RISK) is None


def test_unparseable_file_fails_open_but_loudly(tmp_path):
    """Fail-open protects the run; the health line is what stops it being silent."""
    broken = tmp_path / "standing_risk.json"
    broken.write_text("{not json")
    risk = load_standing_risk(broken)
    assert risk["load_error"] is True
    assert standing_block("SPCX", "2026-09-04", risk=risk) is None
    assert "NOT being applied" in standing_risk_health(risk)


def test_missing_file_fails_open(tmp_path):
    risk = load_standing_risk(tmp_path / "nope.json")
    assert risk["load_error"] is True


# --- the shipped file ------------------------------------------------------

def test_shipped_file_parses_and_is_well_formed():
    risk = load_standing_risk()
    assert standing_risk_health(risk) is None
    for entry in risk["disqualifiers"]:
        assert entry.get("symbol") and entry.get("clears_when"), entry
        assert "cleared" in entry, entry
    for entry in risk["supply_events"]:
        assert entry.get("symbol") and entry.get("kind"), entry
        assert date.fromisoformat(entry["date"]), entry


def test_shipped_file_has_no_user_specific_risk_theses(monkeypatch):
    from pathlib import Path
    shipped = Path(__file__).resolve().parents[1] / "standing_risk.json"
    risk = load_standing_risk(shipped)
    assert risk["disqualifiers"] == []
    assert risk["supply_events"] == []
    assert standing_risk_health(risk) is None


def test_explicit_local_override_preserves_blocking(tmp_path, monkeypatch):
    local = tmp_path / "risk.json"
    local.write_text(json.dumps(RISK))
    monkeypatch.setenv("HEDGY_STANDING_RISK_CONFIG", str(local))
    assert standing_block("SPCX", "2026-09-04", today=date(2026, 8, 3))
    local.write_text("{broken")
    risk = load_standing_risk()
    assert risk["load_error"] is True
    assert "NOT being applied" in standing_risk_health(risk)


def test_explicit_missing_override_reports_health_problem(tmp_path, monkeypatch):
    monkeypatch.setenv("HEDGY_STANDING_RISK_CONFIG", str(tmp_path / "missing.json"))
    assert load_standing_risk()["load_error"] is True
