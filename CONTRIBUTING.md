# Contributing

Use Python 3.11–3.13 in a source checkout. No private accounts or credentials are
needed to contribute.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/hedgy doctor
.venv/bin/hedgy demo
.venv/bin/hedgy test
```

The test command runs suites in separate processes with strategy-specific import
paths. A single broad pytest run can load the wrong `rules` module. Preserve this
isolation and all existing verification.

For optional local commit checks, install [Gitleaks](https://github.com/gitleaks/gitleaks)
(`brew install gitleaks` on macOS) and enable the tracked hook:

```sh
git config core.hooksPath .githooks
gitleaks git . --pre-commit --staged --redact=100 --no-banner
```

CI runs clean installation, the offline demo, isolated tests, and a secret scan.
Use synthetic fixtures and make API tests fail if unexpected network calls occur.
Do not include portfolio exports, real fills, account IDs, logs, tokens, or local
settings in issues or pull requests. See `SECURITY.md`.

Each strategy owns its policy. For a rule change, explain the rationale, update its
canonical `rules.py` / rulebook, and test the behavior. For a maintenance change,
preserve thresholds and decisions. Keep shared code about plumbing rather than
cross-strategy business logic.
