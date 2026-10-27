"""Explicit, read-only Schwab authentication; interactive login lives in login.py."""
import os
from pathlib import Path

from shared.settings import TRADING_ROOT, setting

REPO_ROOT = str(TRADING_ROOT)
TOKEN_PATH = str(TRADING_ROOT / 'token.json')


def schwab_auth():
    try:
        from schwab import auth
    except ImportError:
        raise RuntimeError('Install the optional integration: python -m pip install -e ".[schwab]"') from None
    return auth


def credentials():
    key = setting('SCHWAB_APP_KEY')
    secret = setting('SCHWAB_APP_SECRET')
    if not key or not secret:
        raise RuntimeError('Configure your own Schwab app credentials in trading/.schwab (see docs/SETUP.md), '
                           'or use `hedgy demo` / offline portfolio analysis.')
    return key, secret, setting('SCHWAB_CALLBACK_URL', 'https://127.0.0.1:8182')


def get_client():
    """Reuse an existing token. Never prompt or launch OAuth from a scan/job."""
    key, secret, _ = credentials()
    if not Path(TOKEN_PATH).is_file():
        raise RuntimeError('Schwab login is required. Run `hedgy auth` in an interactive terminal.')
    os.chmod(TOKEN_PATH, 0o600)
    provider = schwab_auth()
    try:
        return provider.client_from_token_file(TOKEN_PATH, key, secret)
    except Exception:
        # OAuth errors can contain request metadata. Keep it out of agent/cron logs.
        raise RuntimeError('Schwab authentication failed. Run `hedgy auth` in an interactive terminal.') from None
