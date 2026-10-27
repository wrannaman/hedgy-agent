"""
pead — canonical numbers for the post-earnings-announcement-drift sleeve.

Reasoning + citations: FUND.md §2A (PEAD row). The anomaly: stocks with large
positive earnings surprises keep drifting up for ~60 days after the report
(Bernard & Thomas 1989/1990; Foster, Olsen & Shevlin 1984 — the drift is
concentrated in the extreme surprise deciles and accrues over roughly the next
quarter). Long-only, recommendation-only, taxable accounts (FUND.md §3/§5).
Single source for this sleeve's thresholds; code imports, never hardcodes.
"""

# Entry window: how many days after the report a name is still a candidate.
# The drift accrues over ~60 days, so entering a few days late sacrifices little
# of the move while letting a once-a-morning scanner catch every reporter.
ENTRY_WINDOW_DAYS = 5

# Hold horizon: Bernard & Thomas measure the bulk of the drift completing within
# ~60 days of the announcement (before the next report). This is also the grading
# horizon the rec-grading loop uses (grade.py marks the rec at entry + HOLD_DAYS).
HOLD_DAYS = 60

# Surprise gate. The literature ranks by SUE (standardized unexpected earnings)
# deciles; without an estimate-dispersion feed we proxy with EPS surprise % =
# (actual - estimate) / |estimate|. 10%+ positive keeps only decisive beats.
# PROXY THRESHOLD — sanity-check against observed scanner output before
# tightening (LEARNINGS #2: gate numbers are set against real output, not guesses).
MIN_SURPRISE_PCT = 10.0

# Reaction gate: the stock must be UP since the close before its report. The
# drift follows the market's verdict on the whole report, not the headline EPS
# number — the earnings-announcement return is itself a stronger drift predictor
# than the surprise (Brandt, Kishore, Santa-Clara & Venkatachalam 2008, "Earnings
# Announcements Are Full of Surprises"). A name selling off on a "beat" means
# guidance/revenue disappointed; buying it fights the signal. (Found the hard way:
# CHWY 2026-06-10, +50% EPS beat, stock down ~2% on the report.)
MIN_REACTION_PCT = 0.0

# Penny-stock floor: drift findings are weakest / costs highest in tiny names
# (Bernard & Thomas note the effect concentrates in small caps, but sub-$5 names
# trade too wide to capture it at retail).
MIN_PRICE = 5.0

# Keep the brief readable — the top decisive beats, not every reporter.
MAX_CANDIDATES_PER_DAY = 3
