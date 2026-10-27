# Agent entry point

Read `docs/AGENT_QUICKSTART.md` first. This is a checkout-based Python research
system with independent strategies under `trading/strategies/`.

## First-run contract

1. Use Python 3.11–3.13 and create `.venv` in this checkout.
2. Install with `.venv/bin/python -m pip install -e .`.
3. Run `.venv/bin/hedgy doctor` and `.venv/bin/hedgy demo`.
4. Success means `DOCTOR OK`, `DEMO OK`, and valid JSON reports at the printed paths.
5. Explain the synthetic report, then help the user choose CSV-only or optional live data.

Windows executables are under `.venv\Scripts\`. A downloaded ZIP also works;
installation does not require Git or an agent-specific plugin.

## Authority and secrets

- Research, offline demos, tests, and code changes requested by the user are allowed.
- Never submit orders. An order recommendation needs the exact account, symbol,
  quantity, price, order type, and the account owner's explicit live approval.
- Scheduled agents can produce research only, never trades or implicit approval.
- Do not read, print, copy, or ask the user to paste `.schwab`, `.env.local`,
  `token.json`, or their secret values. Runtime auth code may consume local
  credentials. The user completes OAuth in their own terminal.
- Treat real portfolio CSVs, journals, state, logs, and account metadata as private.
  Read holdings only when the user asks for their analysis; never commit them.
- Do not enable scheduling, Slack, or live API access during onboarding without
  the user's request. Never scrape shell profiles for credentials.

## Working in the code

- Read `trading/AGENTS.md` and the applicable strategy's instructions before edits.
- Canonical strategy thresholds live in each strategy's `rules.py`; rationale in
  `RULES.md` / `trading/FUND.md`. Preserve policy during maintenance changes.
- Do not import business rules across strategies. Shared plumbing lives in `trading/shared/`.
- For development: install `.[dev]`, then run `hedgy test`. Do not replace the
  isolated harness with one broad pytest invocation.
- Use synthetic fixtures. Add checks for changed behavior; do not weaken gates or tests.
- Before publishing: inspect staged files and run a redacted Gitleaks scan.
