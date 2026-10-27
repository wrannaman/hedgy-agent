# Cash-secured-put research

The historical `csp_401k` name is retained; users explicitly select their options
account in local configuration. This module screens cash-secured puts, monitors
recorded positions, and recommends covered calls against already-owned shares.
It never submits orders.

Read `AGENTS.md`, `RULES.md`, and `rules.py` before live research. The inherited
sizing policy may deploy all available strategy cash into one approved position.
The project preserves that policy; it does not prescribe it for a new user.

## Maintained flow

1. `daily_scan.py`: current market context and daily scan log.
2. `screener.py` / `screener_select.py`: option-chain candidates, rejected-gate
   telemetry, and local standing-risk checks.
3. `pretrade.py`, catalyst checker, and the judgment runbook: validation/context
   before a recommendation. A passed candidate is not trade permission.
4. `monitor.py` / `decision.py`: canonical management verdict for each logged position.
   Renderers do not independently reinterpret the verdict.
5. `recommend.py`: exact proposed order details for manual owner review.
6. `trade_log.py` and `reconcile.py`: recorded fills vs observed account positions.
   Recommendations are never recorded as fills.
7. `shadow_tracker.py`, `decision_journal.py`, `skipped_backcheck.py`: evaluate
   outcomes and missed opportunities without inventing performance history.

`covered_calls.py` is a separate recommendation-only scan against owned shares.
`experiments/snapshot.py` records market snapshots for research. `backtest/` holds
modeled historical experiments; `archive/paper_variants/` is reference code, not the
live workflow. None of these outputs is a proof of future returns.

## Running

See root `docs/SETUP.md` for optional Schwab setup. From this directory, using the
checkout's environment:

```sh
../../../.venv/bin/python daily_scan.py
../../../.venv/bin/python screener.py
../../../.venv/bin/python monitor.py
```

`CRON_PROMPT.md` is the scheduled judgment runbook; the optional macOS wrapper is
`run_daily.sh`. Runtime JSON lives in ignored `state/`, daily logs in ignored
`logs/`, and generated `POSITIONS.md` is private. Fresh installations start with
no trade history. Only explicit fills supplied by the owner enter the journal.
