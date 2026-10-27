"""Credential handling must remain explicit and errors must not disclose secrets."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from shared import auth, earnings, notifications, settings


def test_missing_token_never_starts_manual_oauth(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, 'credentials', lambda: ('test-key', 'test-secret', 'https://localhost'))
    monkeypatch.setattr(auth, 'TOKEN_PATH', str(tmp_path / 'absent.json'))
    def unexpected_sdk():
        pytest.fail('missing token must not start any SDK/OAuth flow')
    monkeypatch.setattr(auth, 'schwab_auth', unexpected_sdk)
    with pytest.raises(RuntimeError, match='interactive terminal'):
        auth.get_client()


def test_reused_token_permissions_are_restricted(monkeypatch, tmp_path):
    token = tmp_path / 'local-token.json'
    token.write_text('{}')
    token.chmod(0o644)
    monkeypatch.setattr(auth, 'TOKEN_PATH', str(token))
    monkeypatch.setattr(auth, 'credentials', lambda: ('test-key', 'test-secret', 'https://localhost'))
    client = object()
    monkeypatch.setattr(auth, 'schwab_auth', lambda: SimpleNamespace(client_from_token_file=lambda *a: client))
    assert auth.get_client() is client
    if os.name == 'posix':
        assert token.stat().st_mode & 0o777 == 0o600


def test_interactive_login_creates_restricted_token_and_restores_umask(monkeypatch, tmp_path):
    from shared import login
    token = tmp_path / 'new-token.json'
    mask_seen = []
    def flow(*args):
        token.write_text('{}')
        mask_seen.append(token.stat().st_mode & 0o777)
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
        return SimpleNamespace(get_account_numbers=lambda: response)
    monkeypatch.setattr(login, 'TOKEN_PATH', str(token))
    monkeypatch.setattr(login, 'TRADING_ROOT', tmp_path)
    monkeypatch.setattr(login, 'credentials', lambda: ('test-key', 'test-secret', 'https://localhost'))
    monkeypatch.setattr(login, 'schwab_auth', lambda: SimpleNamespace(client_from_manual_flow=flow))
    old = os.umask(0o022)
    try:
        assert login.login() == 0
        after = os.umask(0o022)
        assert after == 0o022
        if os.name == 'posix':
            assert mask_seen == [0o600]
            assert token.stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(old)
    assert (tmp_path / 'state/last_schwab_login.txt').is_file()


def test_finnhub_uses_header_and_sanitizes_error(monkeypatch):
    monkeypatch.setenv('FINNHUB_API_KEY', 'private-value-never-display')
    captured = {}
    def request(url, **kwargs):
        captured.update(kwargs)
        raise requests.HTTPError('private-value-never-display in a request failure')
    monkeypatch.setattr(earnings.requests, 'get', request)
    for action in [lambda: earnings.earnings_calendar('2026-01-01', '2026-01-02'),
                   lambda: earnings.earnings_surprises('EXAMPLE')]:
        with pytest.raises(earnings.EarningsFeedError) as caught:
            action()
        assert 'private-value-never-display' not in str(caught.value)
        assert caught.value.__suppress_context__ is True
        assert caught.value.__cause__ is None
        assert 'token' not in captured['params']
        assert captured['headers']['X-Finnhub-Token'] == 'private-value-never-display'


def test_optional_webhook_supports_environment_without_credentials_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'TRADING_ROOT', tmp_path)
    monkeypatch.setenv('SLACK_TRADING_WEBHOOK', 'https://example.invalid/test')
    assert notifications.webhook() == 'https://example.invalid/test'
    monkeypatch.delenv('SLACK_TRADING_WEBHOOK')
    assert notifications.webhook() == ''
    assert notifications.post_message('nothing sent') is False


def test_slack_errors_do_not_expose_webhook(monkeypatch, capsys):
    monkeypatch.setattr(notifications, 'webhook', lambda: 'https://example.invalid/private')
    def fail(*a, **k):
        raise requests.ConnectionError('https://example.invalid/private')
    monkeypatch.setattr(notifications.requests, 'post', fail)
    assert notifications.post_message('message') is False
    assert 'private' not in capsys.readouterr().out


def test_unconfigured_price_watch_does_not_authenticate(monkeypatch, tmp_path):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'strategies/csp_401k/hubs_watch.py'
    spec = importlib.util.spec_from_file_location('isolated_price_watch', path)
    watcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watcher)
    monkeypatch.setenv('HEDGY_PRICE_WATCH_CONFIG', str(tmp_path / 'absent.json'))
    monkeypatch.setattr(auth, 'get_client', lambda: pytest.fail('unconfigured watcher must not authenticate'))
    assert watcher.main() == 0


def test_first_fill_creates_journal_directory(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'strategies/csp_401k'))
    from strategies.csp_401k import trade_log
    path = tmp_path / 'new-state/trades.json'
    monkeypatch.setattr(trade_log, 'LOG_PATH', str(path))
    trade_log.save_log({'trades': [], 'config': {'max_consecutive_losses': 3}})
    assert json.loads(path.read_text())['trades'] == []


def test_sdk_auth_failure_never_exposes_exception_material(monkeypatch, tmp_path):
    token = tmp_path / "local-token.json"
    token.write_text("{}")
    monkeypatch.setattr(auth, "TOKEN_PATH", str(token))
    monkeypatch.setattr(auth, "credentials", lambda: ("test-key", "test-secret", "https://localhost"))
    def fail(*args):
        raise RuntimeError("private-request-material")
    monkeypatch.setattr(auth, "schwab_auth", lambda: SimpleNamespace(client_from_token_file=fail))
    with pytest.raises(RuntimeError) as caught:
        auth.get_client()
    assert "private-request-material" not in str(caught.value)
    assert caught.value.__suppress_context__ is True
