"""Local account metadata, independent of brokerage authentication."""
import json
import os
from pathlib import Path

TRADING_ROOT = Path(__file__).resolve().parents[1]


def load_accounts(path=None):
    """Load private account aliases; an unconfigured installation has no accounts."""
    path = Path(path or os.environ.get('HEDGY_ACCOUNTS_CONFIG', TRADING_ROOT / 'accounts.local.json'))
    if not path.exists():
        if os.environ.get('HEDGY_ACCOUNTS_CONFIG') or path != TRADING_ROOT / 'accounts.local.json':
            raise ValueError(f'Account configuration not found: {path}')
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError('Account configuration must be a JSON object')
    accounts = payload.get('accounts')
    if not isinstance(accounts, dict):
        raise ValueError('Account configuration requires an accounts object')
    for key, value in accounts.items():
        if not key or not isinstance(value, dict):
            raise ValueError('Each account must have a nonempty ID and metadata object')
        if value.get('tax_treatment') not in {'taxable', 'tax_deferred', 'tax_free'}:
            raise ValueError(f'Invalid tax_treatment for account {key}')
        if not isinstance(value.get('bucket'), str) or not value['bucket'].strip():
            raise ValueError(f'Account {key} requires a bucket')
    return accounts
