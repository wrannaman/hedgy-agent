# Retired: paper-variant lane (2026-04-20 → 2026-07-23)

Ran rule variants as paper trades against real Schwab quotes to A/B-test against live
rules. Retired 2026-07-23 — full reasoning and the final result in **RULES.md §12**.
Short version: it duplicated the rules engine (`variants/` — a DRY violation), its
"baseline" drifted three rule-generations stale within weeks, ~50 correlated
trades/quarter has no statistical power, and it influenced zero rule decisions in three
months.

Its one finding, preserved in §12: the April-rules control (shallow 7–10% OTM strikes,
75% target, no VRP gate) lost −$3,729 at a 51% win rate over the same window the live
book (delta gate, 50% target, VRP floors) went 9/9 +$3,582 — supporting evidence for the
June–July rule changes.

Journal frozen at `../../state/paper_options.json` (open positions stamped `retired`).
`experiments/snapshot.py` and the real-trade audit loop (shadow_tracker,
skipped_backcheck, decision_journal) were kept — they measure the book we actually run.
