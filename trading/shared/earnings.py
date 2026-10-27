"""Earnings-surprise feed (Finnhub) — plumbing, no strategy logic or thresholds.

The PEAD sleeve was deferred for lack of an actual-vs-estimate feed (LEARNINGS
backlog #2); Finnhub's free tier provides it (https://finnhub.io/docs/api/
earnings-calendar, 60 calls/min — the sleeve uses ~1 calendar call per morning).
FINNHUB_API_KEY lives in the repo-root .schwab dotenv next to the other secrets;
it is never logged or printed.

Fail-soft contract: missing key or network failure raises EarningsFeedError with
a clean message — callers surface it and keep the morning run alive.
"""
import os

import requests
from shared.settings import load_local_env

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_local_env()

_BASE = "https://finnhub.io/api/v1"


class EarningsFeedError(RuntimeError):
    pass


def _api_key():
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise EarningsFeedError(
            "FINNHUB_API_KEY missing from .schwab — create a free key at finnhub.io")
    return key


def earnings_calendar(from_date, to_date):
    """Earnings reports between two ISO dates (inclusive), with actual vs estimate.

    Returns Finnhub's rows: [{symbol, date, epsActual, epsEstimate, hour, ...}].
    epsActual is None for not-yet-reported entries.
    """
    try:
        r = requests.get(f"{_BASE}/calendar/earnings",
                         params={"from": str(from_date), "to": str(to_date)},
                         headers={"X-Finnhub-Token": _api_key()},
                         timeout=30)
        r.raise_for_status()
        return r.json().get("earningsCalendar", [])
    except EarningsFeedError:
        raise
    except Exception:
        raise EarningsFeedError("Earnings calendar fetch failed; check network and Finnhub configuration.") from None


def earnings_surprises(symbol, limit=4):
    """Recent quarterly EPS surprises for one symbol:
    [{actual, estimate, period, surprise, surprisePercent}]."""
    try:
        r = requests.get(f"{_BASE}/stock/earnings",
                         params={"symbol": symbol, "limit": limit},
                         headers={"X-Finnhub-Token": _api_key()},
                         timeout=30)
        r.raise_for_status()
        return r.json() or []
    except EarningsFeedError:
        raise
    except Exception:
        raise EarningsFeedError("Earnings surprises fetch failed; check network and Finnhub configuration.") from None
