# sources.md — tracked thinkers for the worldview intake

The people/outlets whose thinking we deliberately pull from to draft candidate
worldview theses. This is a **registry only** — a source being listed here does NOT
put anything into `WORLDVIEW.md`. The pipeline is always:

    source content  →  drafted candidate in WORLDVIEW_INBOX.md  →  live discussion  →  (survivors) WORLDVIEW.md

Nothing skips the live-discussion gate (WORLDVIEW.md rule: "New theses enter only
after a live discussion — never from me reading an article alone").

## Guardrails (why one stale voice can't hurt the system)
- **Tilt, never override.** A worldview thesis can nudge a marginal call or a
  watchlist; it can never loosen a number in any `rules.py`, flip a gate, or force
  a trade. Worst case = a flagged conflict for a human. (FUND.md, WORLDVIEW.md.)
- **Per-source cap = 2.** No single thinker may own more than 2 of the 6 active
  theses. Enforced by `worldview.py` (`PER_SOURCE_CAP`); it nags if a voice
  over-indexes.
- **Freshness gate.** Every drafted candidate is stamped with the source's publish
  date and the price/level the author assumed. A candidate whose source is older
  than ~3 months, or whose assumed level the market has already reached, is flagged
  stale at intake and does not graduate.
- **Review-by + staleness nag.** Post-ingestion drift is caught by `worldview.py`,
  which flags any active thesis past its review-by date.

## Tracked sources

| Source | Medium | Access | Cadence | Notes |
|---|---|---|---|---|
| Aswath Damodaran | Blog / Substack (Musings on Markets) + interviews | text (web) — easy | monthly-ish + data updates | Point-in-time valuations w/ explicit assumptions → perfect for falsifiers. Anchor every thesis to his assumed price. |
| Scott Galloway (Prof G) | Podcast — *Prof G Markets*, *Pivot* | audio — needs transcript (RSS + Whisper, or published transcript) | weekly | Deferred until transcript path is built. Directional/narrative, not valuation — treat conviction lower. |

Add a row before drafting from a new voice. Keep this list short — a source you
don't actually read is noise.
