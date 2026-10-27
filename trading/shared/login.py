"""Explicit interactive login. Keep the redirect URL in your terminal, not chat."""
import os
from datetime import date
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.auth import TOKEN_PATH, credentials, schwab_auth
from shared.settings import TRADING_ROOT


def login():
    key, secret, callback = credentials()
    # Restrict the token from its first byte, including SDK-created files.
    if Path(TOKEN_PATH).is_file():
        os.chmod(TOKEN_PATH, 0o600)
    previous_mask = os.umask(0o077)
    try:
        client = schwab_auth().client_from_manual_flow(key, secret, callback, TOKEN_PATH)
        os.chmod(TOKEN_PATH, 0o600)
        response = client.get_account_numbers()
        response.raise_for_status()
        count = len(response.json())
    finally:
        os.umask(previous_mask)
    stamp = TRADING_ROOT / 'state/last_schwab_login.txt'
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(date.today().isoformat() + '\n')
    print(f'Login successful: {count} account(s) available. Token saved privately; no orders placed.')
    return 0


def main():
    try:
        return login()
    except Exception:
        print('Login did not complete. Check your local app credentials/callback and retry `hedgy auth`. '
              'Do not paste credentials or redirect URLs into chat.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
