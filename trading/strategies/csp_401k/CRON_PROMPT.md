# Scheduled options research runbook

Working directory: `trading/strategies/csp_401k/`. Commands below use `python3`
from the scheduler's configured checkout environment. Command paths are relative
to this working directory. All output paths listed in prose are relative to the
**trading root**, unless prefixed `../../` in a shell command.

Read this strategy's `AGENTS.md`, `RULES.md`, and `rules.py`. They own policy and
account scope. Never invent gates, override standing risk, alter rules/code/config,
place orders, or ask for credentials during a scheduled session. This is research
only; live owner confirmation is required for every proposed order.

## Run to completion

Run each scan in the foreground and wait for completion. Do not yield the session
while a background task is pending; the scheduler verifies fresh scan, screen,
and decision outputs from this attempt before accepting success.

```sh
python3 monitor.py
python3 daily_scan.py
python3 screener.py
python3 ../portfolio_watch/sweep.py
python3 covered_calls.py
```

Some scripts use nonzero exits to mean no action; read their output and documented
exit semantics. Missing data/auth is a failure, not a no-trade verdict. Do not use
yesterday's state after a failed scan.

Read the fresh `strategies/csp_401k/state/last_screen.json` candidate list, market
scan, monitor results, and authorized portfolio context. `run_daily.sh` pre-runs
the extra sleeves, portfolio rebalancer, worldview review, and laggard scan.

Read `state/morning_brief.txt`. Its `BRIEF DATE` must be today; otherwise ignore all
sleeve candidates in it and explain unavailability. The independent put hunt still
requires its own fresh screen. Respect every canonical risk/judge/blackout verdict;
a paper or discussion-only candidate never becomes an actionable trade.

Read `state/risk_posture.json` and the brief's risk dial, if present. The renderer
carries the dial; do not silently override its killed candidates. Cross-account
holdings are context under the canonical mandate, never permission to trade another
account. Non-options-account ideas belong only in `portfolio_review` as review items.

## Decide using checked evidence

Review the most promising fresh screened candidates. Confirm live quote quality,
company-specific adverse news and supply events, and all canonical pretrade gates.
Run `pretrade.py` / `event_scanner.py` as documented in those modules. Research
unknown company risks with current credible sources; a failed news check is not a
clean bill of health. An agent may add a discovered standing disqualifier to the
owner's local risk file; it may never clear or delete one.

For each open position, transcribe `monitor.py`'s canonical management verdict.
Do not rederive a HOLD/CLOSE/CUT in a renderer or let a search for a new opportunity
suppress an unconditional management exit. Log material judgment forks with
`decision_journal.record(...)`, including observed inputs and rationale.

Run the deterministic candidate/catalyst pair, up to three passes so a demoted
candidate can be replaced and checked:

```sh
python3 ../morning_decision/decide.py
python3 ../catalyst_check/check.py
```

Then run `python3 ../morning_decision/decide.py` once more. Read
`strategies/morning_decision/state/morning_decision.json` and per-symbol catalyst
verdicts tied to the current screen. A nomination is not a completed pretrade check.

## Evaluate outcomes

```sh
python3 shadow_tracker.py
python3 decision_journal.py --grade
python3 skipped_backcheck.py
python3 experiments/snapshot.py
```

Missing history means there is nothing to grade, not invented trades. Write a
no-action hunt explanation through `scan_log.log_no_action(..., source="agent")`
when no candidate qualifies. Describe the names checked and concrete rejection
reasons, not a repeat of held positions already rendered elsewhere.

## Write one fresh decision

**Do NOT format the Slack message yourself, and do NOT post it.**
Never call the Slack webhook for any content. The scheduler owns delivery through
`post_once.py`; `slack_format.py` owns OPEN / NEW / WATCH / PORTFOLIO / NEAR MISS / PAPER.

Write `../../state/agent_decision.json` (trading-root `state/agent_decision.json`,
not this strategy's state directory), with today's actual date:

```json
{
  "date": "YYYY-MM-DD",
  "new_trades": [],
  "hunt_reason": "Screened the fresh candidate list; explain checked reasons here.",
  "watch": [],
  "portfolio_review": [],
  "notes": []
}
```

`new_trades` is empty unless every required check supports a concrete proposed
options-account action. Each ticket is an object with short string fields:
`do` (symbol/quantity/contract/action), `open` (price/type/duration), `collect`,
`frozen` (cash required and percent), `buy_price` (possible purchase level and
risk context), and `note` (exact management instructions and material checked risk).
Use observed values only. A recommendation is never a fill or an authorization.

`watch` contains discussion-only/near-low ideas, never actionable tickets.
`portfolio_review` contains authorized review-only items for other accounts.
`notes` can carry stale worldview/config warnings. Read
`state/worldview_review.json`; a stale belief must not silently drive a decision.
A useful laggard in `strategies/csp_401k/state/laggards.txt` may be one watch item
on a no-trade day, never a reason to waive math gates or place idle cash.

Use company name plus ticker, short plain-English lines, exact numbers, and
checked dates. Avoid promotional narratives and performance promises. To preview:

```sh
python3 ../../slack_format.py
```

That prints only. Correct decision data if needed, then stop. Do not send a second
message, create an order, log a suggested trade as filled, or change code to force
a passing recommendation. If blocked, report the failed command and a safe error
summary without request URLs, credential values, or token contents.
