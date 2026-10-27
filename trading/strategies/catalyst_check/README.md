# catalyst_check

Bad-news checker for the morning trade candidate.

It reads `strategies/morning_decision/state/morning_decision.json`, fetches recent public headlines for the top candidate, and writes:

- `state/latest.json`
- `state/latest_summary.txt`

Verdicts:

- `clean`: no obvious company-specific blocker found in recent headlines.
- `caution`: news fetch failed, news is noisy, or headlines contain moderate risk terms.
- `block`: headlines contain severe company-specific risk terms such as fraud, SEC probe, accounting issue, lawsuit ruling, guidance cut, or regulatory action.

The verdict is input to `morning_decision`; it is not an order.
