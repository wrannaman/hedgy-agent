# Strategy: catalyst_check

Recommendation-only catalyst and bad-news checker.

## Scope
- Reads the current `morning_decision` candidate or an explicit symbol.
- Fetches public headlines and classifies company-specific risk.
- Writes a structured verdict for the morning decision layer.

## Rules
- Never place orders.
- A `clean` verdict does not authorize a trade by itself.
- A `block` verdict means do not recommend the candidate without the account owner explicitly overriding it in live conversation.
- Network failures must produce `caution`, not `clean`.
- Do not read or print `.schwab` or `token.json`.
