"""Load local integration settings without overriding explicit environment values."""
import os
from pathlib import Path

from dotenv import load_dotenv

TRADING_ROOT = Path(__file__).resolve().parents[1]


def load_local_env():
    if os.environ.get('HEDGY_NO_LOCAL_ENV') == '1':
        return
    load_dotenv(TRADING_ROOT / '.schwab')
    load_dotenv(TRADING_ROOT / '.env.local')


def setting(name, default=''):
    load_local_env()
    return os.environ.get(name, default)
