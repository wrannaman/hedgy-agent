# Cash-secured-put strategy

Inherit `../../AGENTS.md`. The historical folder name is retained for compatibility.
Scope is only the explicitly configured options account (`SCHWAB_ACCOUNT_SUFFIX`).
Other accounts provide context and receive review-only portfolio analysis.

- Instruments: cash-secured puts; covered-call recommendations only on owned shares.
  No new share purchases except a recorded put assignment; no spreads in this module.
- Entry, sizing, and management are defined by `rules.py`, `RULES.md`, and `decision.py`.
  Do not restate or invent thresholds in prompts or renderers.
- Inherited sizing can deploy all available strategy cash, with one position per
  underlying. Require owner policy review before live use; installation is not approval.
- `monitor.py` emits the canonical CLOSE/CUT/HOLD verdict; renderers transcribe it.
- Standing risk facts are local. Agents may add discovered disqualifiers, never
  clear one, delete one, or trade around its written clearing criterion.
- Never submit orders, send unrequested notifications, or widen configured account scope.
- Read `../portfolio_watch/state/latest.json` only for authorized portfolio context;
  its contents never authorize orders in any other account.
