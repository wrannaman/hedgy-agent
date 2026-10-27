"""Agent first-run contracts: isolated synthetic input and explicit local setup."""
import json
import os
from pathlib import Path
import subprocess
import sys

from hedgy import cli

ROOT = Path(__file__).resolve().parents[2]


def command(*args, env=None):
    return subprocess.run([sys.executable, '-m', 'hedgy', *args], cwd=ROOT,
                          env=env, text=True, capture_output=True, timeout=30)


def test_demo_ignores_external_private_settings_and_reports_known_totals(tmp_path):
    env = os.environ.copy()
    env['HEDGY_ACCOUNTS_CONFIG'] = str(tmp_path / 'nonexistent-private-mapping.json')
    env['SCHWAB_APP_KEY'] = 'do-not-display-this'
    env['SLACK_TRADING_WEBHOOK'] = 'https://invalid.example/private'
    output = tmp_path / 'demo'
    result = command('demo', '--output', str(output), env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DEMO OK' in result.stdout
    assert 'do-not-display-this' not in result.stdout + result.stderr
    manifest = json.loads((output / 'manifest.json').read_text())
    report = json.loads(Path(manifest['portfolio']).read_text())
    assert manifest['synthetic'] is True
    assert report['quotes'] == 'skipped'
    assert report['accounts'][0]['account_suffix'] == 'demo-brokerage'
    assert report['accounts'][0]['total_market_value'] == 7000
    assert report['accounts'][0]['cash_value'] == 2000
    assert Path(manifest['rebalance']).is_file()


def test_demo_never_overwrites_existing_data(tmp_path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('keep')
    result = command('demo', '--output', str(tmp_path))
    assert result.returncode == 2
    assert marker.read_text() == 'keep'
    assert 'never overwritten' in result.stderr


def test_doctor_is_credential_free_and_does_not_display_secret_values(monkeypatch, capsys):
    monkeypatch.setenv('SCHWAB_APP_SECRET', 'private-secret-value')
    assert cli.main(['doctor']) == 0
    captured = capsys.readouterr()
    assert 'DOCTOR OK' in captured.out
    assert 'private-secret-value' not in captured.out + captured.err


def test_init_is_private_and_preserves_existing_files(tmp_path, capsys):
    trading = tmp_path / 'trading'
    trading.mkdir()
    for name in ['accounts.example.json', '.env.example', '.env.local.example']:
        (trading / name).write_text('blank-template')
    cli.init_config(tmp_path)
    private = trading / '.schwab'
    assert private.read_text() == 'blank-template'
    if os.name == 'posix':
        assert private.stat().st_mode & 0o777 == 0o600
    private.write_text('existing-private-data')
    cli.init_config(tmp_path)
    assert private.read_text() == 'existing-private-data'
    assert 'existing-private-data' not in capsys.readouterr().out


def test_noneditable_install_fails_with_checkout_guidance(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, '__file__', str(tmp_path / 'site-packages/hedgy/cli.py'))
    import pytest
    with pytest.raises(cli.SetupError, match='source checkout'):
        cli.checkout_root()


def test_portfolio_is_offline_by_default(tmp_path):
    result = command('portfolio', 'sweep', '--positions-dir', str(ROOT / 'trading/examples/positions'),
                     '--state-dir', str(tmp_path / 'reports'))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/latest.json').read_text())
    assert report['quotes'] == 'skipped'
    assert len(report['accounts']) == 1
