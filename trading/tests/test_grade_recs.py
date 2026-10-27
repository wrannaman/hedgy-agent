"""Tests for the recommendation-grading loop (grade.py over brief_journal.jsonl).

Pure where possible (the per-strategy graders, close lookup) plus an end-to-end
pass over a synthetic journal with a canned price-history client — no network.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grade


def _ms(d):
    """Epoch ms for a date, matching Schwab candle timestamps."""
    from datetime import datetime, timezone
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def test_csp_otm_keeps_premium():
    assert grade.grade_csp_at_expiry(strike=80, premium_dollars=189, spot_at_expiry=92.5) == 189


def test_csp_blown_through_strike():
    # $80 put, $1.89 credit, stock at $70: keep $189, eat $1,000 shortfall.
    assert grade.grade_csp_at_expiry(80, 189, 70.0) == 189 - 1000


def test_spread_full_credit_partial_and_max_loss():
    # 660/610 spread, $788 credit, $4,212 max risk.
    assert grade.grade_put_spread_at_expiry(660, 610, 788, 4212, 680.0) == 788
    assert grade.grade_put_spread_at_expiry(660, 610, 788, 4212, 655.0) == 788 - 500
    assert grade.grade_put_spread_at_expiry(660, 610, 788, 4212, 600.0) == -4212


def test_close_on_date_falls_back_but_not_weeks():
    candles = [
        {"datetime": _ms(date(2026, 7, 15)), "close": 101.0},
        {"datetime": _ms(date(2026, 7, 17)), "close": 103.0},
    ]
    assert grade.close_on_date(candles, date(2026, 7, 17)) == 103.0   # exact day
    assert grade.close_on_date(candles, date(2026, 7, 16)) == 101.0   # prior session
    assert grade.close_on_date(candles, date(2026, 8, 30)) is None    # series ends weeks early


class _FakeResp:
    def __init__(self, candles):
        self._candles = candles

    def raise_for_status(self):
        pass

    def json(self):
        return {"candles": self._candles}


class _FakeClient:
    def __init__(self, series):
        self.series = series
        self.calls = 0

    def get_price_history_every_day(self, symbol):
        self.calls += 1
        return _FakeResp(self.series.get(symbol, []))


def _journal_entry(day, recs):
    return {"v": 1, "date": day, "recommended": recs}


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_grade_recommendations_end_to_end(tmp_path):
    journal = tmp_path / "brief_journal.jsonl"
    grades = tmp_path / "rec_grades.jsonl"
    csp = {"sleeve": "csp_401k", "rank": 1, "verdict": "pass", "symbol": "MSTR",
           "strategy": "cash_secured_put", "strike": 80, "premium": 189,
           "collateral": 8000, "expiration": "2026-07-17"}
    spread = {"sleeve": "index_vrp", "rank": 1, "verdict": "pass", "symbol": "QQQ",
              "strategy": "put_spread", "short_strike": 660, "long_strike": 610,
              "premium_dollars": 788, "collateral": 4212, "expiration": "2026-07-17"}
    not_matured = dict(csp, expiration="2026-09-18")
    _write_jsonl(journal, [
        _journal_entry("2026-06-10", [csp, spread, not_matured]),
    ])
    client = _FakeClient({
        "MSTR": [{"datetime": _ms(date(2026, 7, 17)), "close": 92.0}],
        "QQQ": [{"datetime": _ms(date(2026, 7, 17)), "close": 655.0}],
    })

    new = grade.grade_recommendations(client, today=date(2026, 7, 20),
                                      journal_path=journal, grades_path=grades)
    assert len(new) == 2                                  # the September rec isn't matured
    by_sym = {r["symbol"]: r for r in new}
    assert by_sym["MSTR"]["pnl"] == 189 and by_sym["MSTR"]["win"]
    assert by_sym["QQQ"]["pnl"] == 788 - 500              # partial: $655 between strikes

    # Idempotent: a re-run grades nothing new and the file doesn't grow.
    again = grade.grade_recommendations(client, today=date(2026, 7, 21),
                                        journal_path=journal, grades_path=grades)
    assert again == []
    assert len(grades.read_text().splitlines()) == 2


def test_pead_long_graded_on_excess_return(tmp_path):
    journal = tmp_path / "j.jsonl"
    grades = tmp_path / "g.jsonl"
    pead = {"sleeve": "pead", "rank": 1, "verdict": "pass", "symbol": "RKLB",
            "strategy": "pead_long", "spot": 20.0, "collateral": 26000,
            "report_date": "2026-06-08", "expiration": "2026-08-07"}
    _write_jsonl(journal, [_journal_entry("2026-06-10", [pead])])
    client = _FakeClient({
        "RKLB": [{"datetime": _ms(date(2026, 8, 7)), "close": 22.0}],   # +10%
        "SPY": [{"datetime": _ms(date(2026, 6, 10)), "close": 700.0},
                {"datetime": _ms(date(2026, 8, 7)), "close": 728.0}],   # +4%
    })
    new = grade.grade_recommendations(client, today=date(2026, 8, 10),
                                      journal_path=journal, grades_path=grades)
    assert len(new) == 1
    r = new[0]
    assert r["pnl"] == 2600 and r["win"]
    assert r["return_pct"] == 10.0
    assert r["excess_vs_spy_pct"] == 6.0


def test_ungradeable_price_is_retried_not_lost(tmp_path):
    # No usable close near expiry -> rec stays ungraded and is picked up next run.
    journal = tmp_path / "j.jsonl"
    grades = tmp_path / "g.jsonl"
    csp = {"sleeve": "csp_401k", "rank": 1, "verdict": "pass", "symbol": "MSTR",
           "strategy": "cash_secured_put", "strike": 80, "premium": 189,
           "collateral": 8000, "expiration": "2026-07-17"}
    _write_jsonl(journal, [_journal_entry("2026-06-10", [csp])])

    empty = _FakeClient({"MSTR": []})
    assert grade.grade_recommendations(empty, today=date(2026, 7, 20),
                                       journal_path=journal, grades_path=grades) == []

    ok = _FakeClient({"MSTR": [{"datetime": _ms(date(2026, 7, 17)), "close": 92.0}]})
    new = grade.grade_recommendations(ok, today=date(2026, 7, 21),
                                      journal_path=journal, grades_path=grades)
    assert len(new) == 1 and new[0]["pnl"] == 189
