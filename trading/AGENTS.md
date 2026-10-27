# Trading safety and module boundaries

Inherit root `AGENTS.md`. Code, tests, offline demos, and research requested by the
user may run interactively or in automation. Automated sessions never place orders.

- Never read, print, copy, or expose `.schwab`, `.env.local`, `token.json`, or secret values.
  Runtime integrations may consume them; a user completes explicit OAuth in their terminal.
- Every proposed order needs exact account/symbol/quantity/price/type and live owner approval.
  This repository does not submit orders.
- Each strategy owns its business rules. Read its AGENTS.md or CLAUDE.md before edits.
  Share plumbing in `shared/`, not another strategy's rules.
- The options account is selected only by explicit `SCHWAB_ACCOUNT_SUFFIX`.
  Other portfolio accounts are local CSV metadata and recommendation-only.
- Never infer balances or scope from labels, configuration examples, or account list order.
- Use the newest dated snapshot or authorized live source. Missing/stale inputs must
  stay missing/stale, not become invented current holdings.
- Do not commit real holdings, private journals, state, logs, or local account/risk settings.
- Strategy numbers belong in canonical `rules.py`; rationale in its rulebook.
  Do not change policy during an onboarding/maintenance task.
