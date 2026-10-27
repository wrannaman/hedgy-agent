# Local configuration

All paths below are relative to the checkout. Real account data stays local.
`hedgy init` exclusively creates missing private templates with mode 0600 on POSIX.
It never overwrites existing files or asks an agent to view secrets.

| Location / variable | Purpose |
| --- | --- |
| `trading/accounts.local.json` | Local account aliases, tax treatment, portfolio buckets |
| `HEDGY_ACCOUNTS_CONFIG` | Explicit alternate account JSON path |
| `trading/positions/` | Private CSV snapshots; optional `--positions-dir` override |
| `--state-dir` | Explicit private output directory for a portfolio command |
| `trading/.schwab` | Optional API keys, callback URL, Slack webhook |
| `trading/.env.local` | Explicit `SCHWAB_ACCOUNT_SUFFIX` selection |
| `trading/token.json` | OAuth token written by explicit user login |
| `trading/strategies/*/state/` | Private generated strategy state/journals |
| `trading/strategies/*/logs/` | Private scan and scheduler logs |
| `trading/strategies/csp_401k/standing_risk.local.json` | Owner's standing risk blocks / supply events |
| `HEDGY_STANDING_RISK_CONFIG` | Alternate risk JSON path |
| `trading/price-watch.local.json` | Optional opt-in price watcher; absent means disabled |
| `HEDGY_PRICE_WATCH_CONFIG` | Alternate watcher JSON path |
| `CLAUDE_BIN`, `CLAUDE_MODEL` | Optional scheduler CLI/model overrides; defaults to authenticated CLI settings |
| `HEDGY_PYTHON` | Explicit scheduler/test interpreter override |

The portfolio CLI defaults to offline CSV prices. `--live-quotes` explicitly opts
into Schwab requests. Explicit environment credentials take precedence over local
settings. The demo ignores inherited integration/configuration settings and reads
only bundled synthetic samples.

## Account metadata

```json
{
  "accounts": {
    "my-brokerage": {"label": "Brokerage", "tax_treatment": "taxable", "bucket": "taxable"},
    "my-retirement": {"label": "Retirement", "tax_treatment": "tax_deferred", "bucket": "retirement"}
  }
}
```

Aliases can be arbitrary strings for normalized CSVs; original Schwab CSVs use
the suffix from their metadata. Multiple accounts may share a bucket. Tax treatment
must be `taxable`, `tax_deferred`, or `tax_free`; unconfigured accounts are treated
as taxable. No account balances, names, or identifiers belong in source.
The planner's default tax rates are example US assumptions, not a tax profile
inferred from an account label. Review `portfolio_watch/rules.py`, including NIIT
and short-term treatment; `--ca-rate`, `--fed-rate`, and `--short-term` are available
on the underlying `rebalance.py` command. The CLI exposes the first two rate overrides.

## Standing risk

The shipped `standing_risk.json` is empty. Copy a local version and populate only
facts you have checked. Example schema (dummy symbol, not a recommendation):

```json
{
  "disqualifiers": [{
    "symbol": "EXAMPLE", "opened": "2026-01-02",
    "reason": "Unresolved material risk", "clears_when": "Documented resolution",
    "cleared": false
  }],
  "supply_events": [{"symbol": "EXAMPLE", "date": "2026-02-02", "kind": "secondary"}]
}
```

A disqualifier blocks action until the owner clears its stated bar; supply events
block within the contract window. An agent may record a new risk, never clear one
on its own. Missing/malformed explicit override files keep the existing loader's
fail-open behavior **and** emit a health warning: repair it before trusting research.
Do not treat the absence of a block as a current catalyst check.
