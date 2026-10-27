# Architecture and preserved core

`hedgy/cli.py` is a small entry point over the existing independent research modules.
It runs scripts in separate processes so each strategy keeps its own imports and
rules. Installation is editable from a checkout; report/state paths are never
inferred from a standalone installed wheel.

| Area | Responsibility |
| --- | --- |
| `trading/shared/` | CSV parsing, account configuration, optional API authentication/data, notifications |
| `strategies/portfolio_watch/` | Cross-account portfolio exposure and tax-aware review reports |
| `strategies/csp_401k/` | Cash-secured puts, owned-share covered calls, canonical management verdicts, journals |
| `strategies/morning_decision/` | Deterministic recommendation ranking from current outputs |
| `strategies/catalyst_check/` | Public-news risk checks with explicit uncertainty on failures |
| `strategies/index_vrp/`, `trend/`, `factor/`, `pead/` | Additional research sleeves |
| `fund_engine.py`, `risk.py`, `judge.py` | Unified research brief and portfolio/strategy risk gates |
| `trading/archive/`, strategy `archive/` | Historical research/reference implementations, not maintained entry points |

The CSP folder retains its historical `csp_401k` name; live account scope is explicitly
selected locally. No broker client has order-submission code here. A recommended
order is still a proposal requiring the account owner's live confirmation.

Rules and reasoning are separate: `rules.py` owns numbers; each `RULES.md` and
`trading/FUND.md` explain policy and evidence. The open-source cleanup preserves
calculation and gate behavior. Inherited defaults are a research policy, not an
appropriate risk mandate for every account. Review them before live use.

`hedgy demo` always uses the synthetic sample and account mapping in a subprocess,
then writes a fresh report manifest. `hedgy portfolio` analyzes the user's explicit
snapshot directory. State and logs are private, ignored, and never part of a release.
The optional scheduler reads `CRON_PROMPT.md`, runs a judgment agent, verifies fresh
outputs, and delegates the single notification to `post_once.py`.
