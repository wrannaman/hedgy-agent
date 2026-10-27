"""Broker-independent inputs and explicit local account configuration."""
import json
from datetime import date
from pathlib import Path

import pytest

from shared.config import load_accounts
from shared.positions import latest_position_files, parse_position_file

HEADER = 'account_id,account_name,as_of,symbol,quantity,price,market_value,cost_basis,asset_type\n'


def write_csv(path, stamp='2026-01-02'):
    path.write_text(HEADER + f'demo,Demo,{stamp},SPY,10,500,5000,4000,etf\n'
                    + f'demo,Demo,{stamp},CASH,2000,1,2000,,cash\n')
    return path


def test_normalized_positions_derive_totals_basis_and_cash(tmp_path):
    snapshot = parse_position_file(write_csv(tmp_path / 'demo.csv'), today=date(2026, 1, 3))
    assert snapshot.account_suffix == 'demo'
    assert snapshot.total_market_value == 7000
    assert snapshot.cash_value == 2000
    assert snapshot.holdings[0].gain_dollars == 1000
    assert snapshot.holdings[0].account_pct == pytest.approx(5000 / 7000 * 100)
    assert not snapshot.stale


def test_latest_snapshot_uses_as_of_not_filename(tmp_path):
    write_csv(tmp_path / 'newer-name.csv', '2026-01-02')
    newer = write_csv(tmp_path / 'another.csv', '2026-01-03')
    assert latest_position_files(tmp_path) == {'demo': newer}


def test_mixed_accounts_rejected(tmp_path):
    p = write_csv(tmp_path / 'bad.csv')
    p.write_text(p.read_text().replace('demo,Demo,2026-01-02,CASH', 'other,Demo,2026-01-02,CASH'))
    with pytest.raises(ValueError, match='one account'):
        parse_position_file(p)


def test_missing_required_value_rejected(tmp_path):
    p = write_csv(tmp_path / 'bad.csv')
    p.write_text(p.read_text().replace('5000,4000', ',4000'))
    with pytest.raises(ValueError, match='market_value'):
        parse_position_file(p)


def test_account_tax_classification_is_explicit(tmp_path):
    p = tmp_path / 'accounts.json'
    p.write_text(json.dumps({'accounts': {'demo': {'tax_treatment': 'tax_free', 'bucket': 'retirement'}}}))
    assert load_accounts(p)['demo']['tax_treatment'] == 'tax_free'
    p.write_text(json.dumps({'accounts': {'demo': {'tax_treatment': 'invalid', 'bucket': 'retirement'}}}))
    with pytest.raises(ValueError, match='tax_treatment'):
        load_accounts(p)


def test_no_quotes_workflow_does_not_import_schwab_auth(tmp_path, monkeypatch):
    import sys
    from strategies.portfolio_watch import sweep
    monkeypatch.setitem(sys.modules, 'shared.auth', None)
    positions = tmp_path / 'positions'
    positions.mkdir()
    write_csv(positions / 'demo.csv')
    payload = sweep.run(no_quotes=True, positions_dir=positions, state_dir=tmp_path / 'reports')
    assert payload['quotes'] == 'skipped'
    assert payload['accounts'][0]['total_market_value'] == 7000
