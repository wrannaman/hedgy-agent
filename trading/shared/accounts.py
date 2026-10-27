"""Account selection helpers for Schwab clients."""

from shared.settings import setting


def configured_account_suffix():
    """Require an explicitly selected account; never fall back to another one."""
    suffix = setting("SCHWAB_ACCOUNT_SUFFIX").strip()
    if not suffix or not suffix.isdigit():
        raise ValueError("Set SCHWAB_ACCOUNT_SUFFIX in trading/.env.local")
    return suffix


def account_by_suffix(client, suffix):
    """Return the Schwab account-number record ending in the given suffix."""
    if not str(suffix).strip() or not str(suffix).isdigit():
        raise ValueError("Account suffix must contain digits")
    resp = client.get_account_numbers()
    resp.raise_for_status()
    accounts = resp.json()
    matches = [a for a in accounts if str(a.get("accountNumber", "")).endswith(str(suffix))]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No Schwab account ending in ...{suffix}")
    raise ValueError(f"Multiple Schwab accounts ending in ...{suffix}")
