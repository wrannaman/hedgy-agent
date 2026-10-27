# Agent quickstart

Goal: get a new user from checkout to an explained research report in minutes,
without credentials or brokerage access. Works with any coding agent and a terminal.
The project is a headless scheduled research bot, not a trading app UI.

**Toy project: do not use with real money.** Assume complete loss of any capital
exposed; options/leverage can lose more than initial capital. Read
[the disclaimer](DISCLAIMER.md). Help users learn through the offline demo and paper
experiments, not real-money execution.

## 1. Inspect and install

Read root `AGENTS.md`. Confirm Python 3.11–3.13, then from the checkout root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/hedgy doctor
.venv/bin/hedgy demo
```

Windows: replace `python3` with `py -3` for venv creation and executable paths with
`.venv\Scripts\python` / `.venv\Scripts\hedgy`.

Expected signals: `DOCTOR OK`, `DEMO OK`, `Reports: <new directory>`, and
`Manifest: <directory>/manifest.json`. Read the manifest, then its two JSON reports.
The bundled account has $7,000 total: $5,000 in an example SPY position and $2,000
cash. Explain concentration and the cash-raise example, including assumed tax rates.
Dates are fixed; a stale-sample warning is expected. Reports never represent a real
person or account. No network requests occur in the demo.

The demo deliberately ignores inherited integration and account-configuration
environment variables. Each run creates a new private temporary directory, or use
`hedgy demo --output <new-directory>` for an explicit destination. Existing report
folders are never overwritten. It does not initialize real account settings.

## 2. Choose the user's path

- **CSV-only:** `hedgy init`; user edits `trading/accounts.local.json` locally and
  saves snapshots in `trading/positions/`. Follow `trading/examples/README.md`.
  Run `hedgy portfolio sweep --positions-dir trading/positions`. No live account needed.
- **Schwab live research:** follow `docs/SETUP.md`. Install `.[schwab]`; the user
  supplies app credentials locally and completes `hedgy auth` themselves.
  Never ask for a redirect URL, token, or secret in chat.
- **Development:** install `.[dev]`; run `hedgy test`. Use `docs/ARCHITECTURE.md`
  before changing strategy modules.

Do not silently choose the live or scheduled path. Do not enable Slack or launchd
while merely installing or demonstrating the software.

## 3. Preserve the boundary

`hedgy portfolio` uses snapshot prices unless the user explicitly adds
`--live-quotes`. It writes private reports, not orders. The optional options
scanners recommend candidates; the account owner makes investment decisions and
places any confirmed order manually. Read the full sizing/management policy before
interpreting live candidates. A candidate passing a gate is never permission to trade.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `hedgy` not on PATH | Use `.venv/bin/hedgy` (Windows `.venv\Scripts\hedgy`) |
| Python below 3.11 | Install a supported Python and recreate the virtual environment |
| `Source checkout` error | Run editable installation from a clone or extracted source ZIP; standalone wheel installs are unsupported |
| Demo cannot write output | Choose a new writable directory; it never overwrites an existing directory |
| Stale sample warning | Expected for fixed synthetic input; use a dated current snapshot for real analysis |
| Missing CSVs | Check `--positions-dir` and required columns; one account/date per file |
| Optional Schwab package missing | Stay offline or install `.[schwab]`; no need to create an account for the demo |
| Missing/expired OAuth token | User runs `hedgy auth` interactively; scans never prompt or create tokens |
| Strategy import/test errors | Use `hedgy test`, not a broad `pytest trading` command |

Finish onboarding with the commands run, report paths, what the report says, and the
next chosen path. Do not invent performance claims from sample data.
