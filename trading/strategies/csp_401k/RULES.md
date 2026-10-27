# csp_401k — Evidence-Based Rulebook

**This is the authoritative rulebook for the csp_401k strategy.** Every rule below
is tied to a real source with a confidence rating. Where reputable sources
disagree, both are shown.

**One canonical rule set, two files, no copies:** this file (`RULES.md`) holds the
rules + reasoning + citations; **`rules.py`** holds the exact same thresholds as
numbers, and **every script imports them from there** — nothing hardcodes a rule.
The numbers quoted in this doc (50%, 21 DTE, 2×, 1.5×, 10%, 2%, 28–45) are the ones
defined in `rules.py`; change them there and the whole system changes. `POSITIONS.md`,
`CLAUDE.md`, `CRON_PROMPT.md`, and `README.md` restate **no** rules — they point here.
The only place allowed to use different values is `variants/` (the paper sandbox).

Last rebuilt: 2026-06-05, from a three-desk research pass (tastytrade mechanical
studies, the academic VRP / Cboe index literature, and the profit-target /
stop-loss / sizing backtests). Sources are listed at the bottom.

---

## 0. What edge are we actually harvesting? (Read this first.)

Be honest about the engine, because it sizes everything else:

- **Index put-writing has a robust, decades-long edge.** The Cboe PUT index
  returned ~9.5%/yr 1986–2018 with ~⅓ less volatility than the S&P, Sharpe ~0.65,
  max drawdown −32.7%. The fuel is the **variance risk premium (VRP)**: implied
  vol exceeds subsequent realized vol by ~4 points on average, persistently, and
  the gap survives CAPM/Fama-French controls. *(Bondarenko 2019; Carr-Wu 2009;
  Bakshi-Kapadia 2003; Bollerslev-Tauchen-Zhou 2009. Confidence: HIGH.)*

- **That edge mostly does NOT transfer to single names.** The single-stock VRP is
  much smaller — often ~zero or positive — because much of the index premium is
  *correlation risk* a single-name seller never collects. *(Carr-Wu 2009;
  Bakshi-Kapadia JoD 2003; Gourier. Confidence: HIGH.)* Meanwhile we take on the
  **full idiosyncratic gap risk** (earnings, guidance cuts, single-name 20–40%
  overnight moves) the diversified index never sees in one print.

- **And the index edge itself may be gone (2026-07-07 review).** Dew-Becker & Giglio
  (Chicago Fed WP 2025-17) show delta-hedged S&P 500 option **alphas converged to
  zero after a May-2012 structural break** — post-2012 index put-selling earns beta
  compensation, not alpha. Caveats: unrefereed working paper, sample ends 2022,
  index-only, and the dealer-gamma mechanism is index-market-structure specific — it
  *qualifies* rather than kills a single-name book. Net: the historical PUT-index
  numbers in §9 are a ceiling from a regime that may no longer exist; this book's
  edge lives or dies on the single-name/earnings premium, measured on our own trades
  (§10, §12). Nobody has published post-2020 single-name alphas — open question.
  *(Verified 3-0 on all three sub-claims. Confidence: HIGH that the finding is real;
  MEDIUM on what it implies for single names.)*

- **The one real single-name edge is the earnings event premium.** Options are
  systematically overpriced into earnings — the implied move exceeds the realized
  move ~72% of the time, straddle buyers earn significantly negative returns,
  sellers collect the IV crush. *(Alexiou-Goyal-Kostakis-Rompolis, Review of
  Finance 2025; Cboe earnings study. Confidence: HIGH on direction.)* But it is
  explicitly compensation for **bimodal jump risk** — the other 28% are the big
  gaps. Pennies in front of a steamroller unless the strike sits well outside the
  implied move.

**Implication for this book:** our structural edge is thin and tail-heavy. We are
not running the PUT index. The disciplines that actually drive the equity curve
are, in order: (1) **cut losers** — it matters more than profit-taking; (2) **size
for the tail / assignment**, not for the premium; (3) harvest the **earnings event
premium** with deep cushions; (4) **mechanical, pre-committed exits.** Win rate is
the *least* informative number we track.

---

## 1. Entry — when and what to sell

| Rule | Basis | Confidence |
|------|-------|------------|
| **Positive VRP is the edge gate, not a preference** (`MIN_VRP`, RULES.md §1; enforced in `screener.py` via the `edge_ok` flag). **VRP = underlying IV − 30d realized vol.** We have an edge only when options price *more* vol than the stock has realized; at or below `MIN_VRP` we'd be selling fairly- or under-priced vol and collecting raw premium with no edge. A candidate without `edge_ok` is **never actionable, however fat the premium** — raw premium size is not edge. The risk dial (`fund_rules`) may demand more positive VRP in a defensive regime; it can only tighten this floor. | tastytrade IV-rank studies; VRP literature (Carr-Wu, BTZ). | HIGH that edge concentrates where IV > RV; the 0 floor is a hard invariant (never sell underpriced vol), the dial's extra cushion is MODERATE. |
| **Two bars, not one: `edge_ok` (has edge) vs `actionable` (rich enough to trade)** (`ACTIONABLE_VRP`, enforced in `screener.py` via the `actionable` flag; RULES.md §1a). Clearing `MIN_VRP` (0) means a candidate has *some* edge and is worth logging — it does **not** mean surface it as a trade. Single-name VRP is thin and often barely positive (§0), so a +5-to-+14 VRP name is a **WATCH**: ranked and tracked, never pitched to the account owner as a sell and never wrapped in "options pricing far more swing than the stock moves" copy. A fresh put is **ACT** only when VRP clears the higher `ACTIONABLE_VRP` floor **in points AND as a ratio** (`ACTIONABLE_VRP_RATIO`, added 2026-07-01: a flat point floor is easier for violent names to clear on noise — 15 pts on a 90-vol name is only 1.17× rich vs 1.6× on a 25-vol name — so points-alone tilts the screen toward the most dangerous underlyings), **or** it is an earnings-premium harvest with a deep cushion (the one real single-name edge, §0 — an earnings print inside the contract's life justifies thinner steady-state VRP *because* the strike sits outside a large implied move). Separating edge from actionability avoids presenting thin positive VRP as a fully qualified trade. The floor value is a judgment dial (alert appetite), not a backtested constant. | §0 (single-name VRP ~zero); the same VRP literature as the row above. | HIGH that bare +VRP is not enough on single names; the specific 15 floor is a MEDIUM judgment dial. |
| **DISCUSS tier — surface a beaten-down name for a human look, never as a trade** (`NEAR_52W_LOW_BAND_PCT`, enforced via the `discuss`/`gate_cleared` flags; RULES.md §1b). A high-IV name near its 52-week low is *structurally* squeezed out of the screen: its large implied move forces the strike past the expected-move cushion, and that deep it no longer pays 2% — so nothing clears and the name silently vanishes. That is exactly the "sell into fear on a quality name" setup the account owner wants to *see* and talk through. So when a name trades within `NEAR_52W_LOW_BAND_PCT` of its 52-week low **and is on the curated willing-owner list** (`laggard_scan.WILLING_OWNER`; gate added 2026-07-07 — the tier's shallow cushion makes assignment a real outcome, so only names the account owner would genuinely own cheaper qualify; a beaten-down lottery ticket near its low is a falling knife, not a discount — JOBY/ACHR were the motivating noise) and offers a put clearing the **flat** `MIN_CUSHION_PCT` floor + premium + liquidity (but not the expected-move cushion), it surfaces tagged `discuss` — visible, carrying a `surface_reason`, **never `actionable`, never auto-recommended.** ACT candidates are not gated by the list: their deep expected-move cushion makes assignment a tail, not a plan. The trade is shallower than the strict gate allows (assignment is a real outcome, not a tail), so it's a conversation starter only; a ticket gets composed only if the account owner asks. | Display policy; mean-reversion on quality names is a *different* edge than VRP-harvest (§0). | LOW — a display heuristic, not an edge claim; the trade it shows is deliberately shallow. |
| **Sell on red days, not green — because that's where VRP is richest.** Fear bids up premium; you're paid most for the same strike exactly when the tail is most feared. Red-day selling is the *mechanism* that produces the positive VRP the gate above requires; it is not a separate rule. A profitable outcome on a sharp up-day would not validate chasing a thin-fear entry. Caveat: a 10% drop pays more only if it's an overreaction; if it's the first leg of a real repricing you've sold into a crash, so it's "red day **and** VRP-positive **and** cushion covers the move," never red alone. **Enforced 2026-07-01** as the no-chase guard (`NO_CHASE_SIGMA`, `screener.py`): a day up-move above 1 daily sigma of the name's own realized vol demotes ACT → WATCH for the day (with a `watch_reason`); it re-surfaces on the next non-chasing screen. Sigma-scaled, not a flat %, so a +4% day on an 83-vol name is correctly ignored while +4% on a 20-vol staple correctly blocks. | tastytrade; VRP is regime-dependent. | MODERATE (sound, not precisely quantified); the 1.0σ line is a judgment dial. |
| **Enter ~28–45 DTE; lean to 45.** Balances meaningful theta against tame gamma. Closer-dated decays faster per-day but carries far more path/gamma risk. | tastytrade "45 DTE" convention. | MODERATE as a convention; WEAK as a precisely-optimized number. |
| **VRP caveat on single names:** a high IV *Rank* on one stock usually just means "earnings is near," which is a *different* trade than high IV on the index. Don't read single-name IVR as if it were SPY's. | Carr-Wu; tastytrade help center. | HIGH. |

## 2. Strike selection

| Rule | Basis | Confidence |
|------|-------|------------|
| **`MAX_DELTA` sets the shallowest permitted strike.** The selector maximizes premium as a percentage of collateral among puts clearing all gates, so the result often approaches the permitted delta boundary. Review the canonical value in `rules.py` as an intentional policy setting rather than assuming the optimizer will choose a deeper strike. | Tom Sosnoff's short-put setup: roughly 12 delta, 45 DTE, managed at 50% of maximum credit. | Literature-informed policy; single-name application requires ongoing evaluation. |
| **Distinguish the cited index setup from the single-name implementation.** The reference setup uses an index future, roughly 12 delta, a 45-day term, and management at 50% of maximum credit. This screener permits the canonical term window and optimizes cash-secured premium; its minimum-premium gate can exclude lower-yielding index puts and favor high-IV single names. The index-level VRP evidence must not be assumed to transfer unchanged. | Sosnoff's /ES setup uses futures margin; cash-securing an index put has different capital requirements. `strategies/index_vrp/` separately researches defined-risk index put spreads. Cboe PUT research and FUND.md §0/§2A support the index distinction. | HIGH on the structural distinction; single-name performance requires independent evaluation. |
| **Strike depth is gated on delta: `delta ≤ MAX_DELTA`, plus a flat `cushion ≥ 10%` floor** (`rules.MAX_DELTA`, enforced in `screener_select._score_put`). Delta is the market's own probability the put finishes ITM, so an earnings print inside the contract's life is already priced into it and pushes the strike deeper automatically — the same property the old cushion gate was reaching for. **Changed 2026-07-13** (see the row below): the screener previously enforced `cushion ≥ max(10%, implied move)` where `implied move = IV × √(DTE/365)` — a **linear** price drop standing in for a 1-SD move. A 1-SD move is *lognormal*, so the linear form over-deepens the strike and the error grows with IV: measured live, it landed on a 0.13-delta strike at IV 20 (about right) but a **0.07-delta strike at IV 120** — less than half the intended depth. Those strikes are so deep they no longer pay `MIN_PREMIUM_PCT`, so nothing cleared and the name vanished **with no log line at all**. On 2026-07-13 that silently deleted **54 of 169 names** — the median one a 0.25-delta put paying 4.88% — i.e. it misfired hardest on exactly the high-IV names the universe exists to harvest. Gating on delta directly makes the code select what the row below already said to select, and adds no model assumption (delta is quoted in the chain; the −999 sentinel filter is now load-bearing twice over). Not a loosening: it does **not** reach the ~0.25-delta strikes a human might pick — those stay outside the published band on purpose. | Delta↔probability is definitional; the 16-delta anchor is the row below. Replaces the old earnings ban (see §5). | HIGH — the anchor is STRONG (below) and the rest is arithmetic. |
| **~16-delta is the canonical "1 SD OTM" anchor** (≈84% chance of expiring OTM, higher POP after credit). This **is** the screener's strike gate as of 2026-07-13 (`MAX_DELTA`); before that it was only a manual sanity check, and the screener was quietly failing it by ~2× on high-IV names. | tastytrade. | STRONG on the delta↔probability map. |
| **A name the gates delete must leave a record** (`screener_select.near_miss_from_chain` → `state/near_miss.jsonl`, added 2026-07-13). `skipped_log.jsonl` only ever logged candidates that **already cleared**, so the 30-day "did we miss edge?" back-check was structurally blind to every name the gates threw out — the bug above hid inside that blind spot for as long as it existed. A name where nothing clears now logs its best one-gate-away put and the gate that killed it. Telemetry only: a near-miss is never a candidate, never ranked, never actionable. It must clear the flat 10% cushion floor to be logged, or the argmax-by-premium hands back the at-the-money put every time (same shape as the DVN −999 bug, §12). | Auditability principle: gate failures must remain measurable rather than disappear silently. | HIGH — it is an audit trail, not an edge claim. |
| **High win rate ≠ profitable.** 16-delta strangles win 65–84% of the time yet produced poor long-run returns in independent SPX backtests because the losers dwarf the winners. Never let a high POP talk you out of cutting a loser. | SJ Options / SteadyOptions independent backtests. | STRONG. |

## 3. Managing winners — the canonical tastytrade triad (nothing invented)

We use the simple, pre-backtested rules tastytrade publishes, not thresholds we
made up. Three rules, evaluated by `monitor.py` into one verdict (`do` =
CLOSE / CUT / HOLD) that every renderer transcribes. **There is no velocity rule,
no 75% near-max rule, and no keep-vs-redeploy gate** — those were removed 2026-06-18
(see the note below) because their overlap produced a wrong HOLD on a 57%-in-3-days
WDC winner that should have been an obvious close.

| Rule | Basis | Confidence |
|------|-------|------------|
| **Close at 50% of max credit.** This is the primary exit, applied unconditionally — not gated on cushion, redeployment, or whether the screener found a new trade. It shortens tail exposure and raises win rate (you exit before a winner can reverse); aggregate return comes from turnover, not from squeezing past 50%. | tastytrade mechanical studies — short premium on SPY/QQQ, ~15 yrs incl. the 2020 crash and 2022 bear, "close at 50% profit OR 21 DTE, whichever first." [tastytrade: Close at Profit Percent](https://support.tastytrade.com/support/s/solutions/articles/43000435423) | STRONG that managing at 50% beats hold-to-expiry on a risk-adjusted basis. |
| **At 21 DTE, close a winner — but do NOT cut a loser on the clock alone** (`MANAGE_DTE_CUTS_LOSERS = False`, changed 2026-06-29). Closing a *winner* near the timer harvests it before rising gamma can flip it overnight — that half stands. But a position still *down* at the timer has, by construction, already cleared the 2× stop and the 5% strike-proximity gate above it, so it is far OTM and down only on **IV markup, not assignment risk**. Cutting it realizes a loss at elevated IV on a bet whose strike isn't threatened. Time is not a risk signal; the stop, proximity, and bad-news exits (§4) are. So a far-OTM loser **holds to expiry**. **A "winner" here means up at the ASK, not the mid** (added 2026-07-31): a close pays the ask, and on a deep-OTM put the spread routinely exceeds the whole remaining win, so a mid-only test flips sign on quote noise and books a real loss while calling it a win. Up at the mid but down at the ask falls through to the same hold. | tastytrade + gamma mechanics for the winner side ("50% or 21 DTE, whichever first"); **§4 for the loser side** — Project Finance's 41,600-trade short-put study found a fixed mechanical stop the *worst* outcome and that loss management should be regime-dependent (hold tested positions in calm tapes; don't stop into noise). | STRONG on closing winners at the timer. The loser-side hold is **literature-backed (§4, HIGH)** but **NOT yet confirmed on our own book** — the modeled backtest is inconclusive (§12). |
| **Cut at 2× the credit collected — but conditioned, not gospel** (`STOP_MULTIPLE`, `STOP_CONFIRM_RUNS`, `STOP_HIGH_VIX_ENTRY`; changed 2026-07-07 from the deep-research review). Two conditions on the mark-based stop, each from independently verified evidence: **(a) Confirmation** — the 2× mark must persist across `STOP_CONFIRM_RUNS` consecutive monitor runs before the verdict is CUT (first sighting = alerted STOP-PENDING hold). The stop is the only exit that fires off a *quote* rather than the underlying, and deep-OTM put mids are exactly where quotes lie: in the 5 Aug 2024 VIX spike, deep-OTM put bid-ask spreads hit >80% of mid vs ~25% normal, mechanically inflating marks (BIS Bulletin 95) — our 5–7-delta zone is where this is worst. If the loss is real it's still there 3–4 hours later. **(b) VIX-at-entry regime** — the stop auto-CUTs only for trades entered at VIX ≥ `STOP_HIGH_VIX_ENTRY`; on calm-tape entries a confirmed 2× mark surfaces as an alerted STOP-ADVISORY judgment call (logged), because in the 41,600-trade Project Finance study loss-taking stops improved P/L and drawdowns *only* in high-VIX entries — passive management won in low-VIX regimes. Unknown entry VIX (legacy trades, backtest) = stop active, conservative. **Never conditioned:** strike-proximity and bad-news exits read the underlying, not the quote — they stay immediate (§4). `entry_vix` is recorded at fill by `log_trade_open`. | tastytrade's standard stop, now conditioned by Project Finance (41,600 trades, regime split) + BIS Bulletin 95 (Todorov & Vilkov, Aug-2024 quote-artifact evidence); both verified 3-0 in the 2026-07-07 adversarial research review. | HIGH on both directions (regime-dependence, quote-artifact risk). The specific dials (2 runs, VIX 20) are judgment values, MEDIUM. BIS data is SPX and partly pre-market; single-name transfer is a conservative extrapolation. |

**How we run it without babysitting — the standing-order pair (canonical tastytrade workflow).** The moment a put fills, place a **GTC buy-to-close limit at the 50% mark** (`limit_price × 0.50` ≈ `credit × 0.50`), and **set its end date to the 21-DTE `manage_date`** (Schwab supports a custom GTC end date). It rests across days and closes the winner by itself the instant the put trades there — no watching, no timing — and auto-cancels on the manage date. On that date the **system** re-evaluates the position and posts the exact next order (close if up, cut if down): the engine owns the management decision and produces the ticket. The 401k is read-only, so the account owner's only step is confirming/placing that order — never tracking the date or making the call himself. The order's own expiry is the engine's trigger, not a to-do for the account owner. Also cancel the GTC any time you close by another route: once you are flat, that resting order is no longer a close — it is a naked BUY, and filling it opens a **long** put position (a debit), not another short put. The GTC catches only the *win* — the downside (2× stop, strike proximity, bad news) is the monitor's job, which runs 3×/day and emits `CUT`. `monitor.py` surfaces both numbers per position (`gtc_price`, `manage_date`) and every new-trade rec states the GTC to set on fill, so neither has to be remembered or computed.

**Changed 2026-06-29 — the 21-DTE timer no longer cuts a far-OTM loser** (`MANAGE_DTE_CUTS_LOSERS = False`).
A far-out-of-the-money put can show a mark-to-market loss solely because implied
volatility rose, while the underlying remains far above its strike. A timer based
only on calendar age and the P&L sign would realize that loss without a new risk
signal. This contradicted §4's own HIGH-confidence guidance (hold tested positions in calm
tapes; fixed stops can be the worst outcome). The rule now resolves that conflict toward §4: at the
timer we close winners but hold a still-far-OTM loser to expiry, with the 2× stop and strike-proximity
gates as the real risk floor. **What did NOT change:** the cut still fires the instant a position is
*actually* threatened (≥2× credit, or within 5% of the strike, or confirmed bad news — §4). This is a
mandate + literature change, **not** a backtest-promoted one; the modeled backtest was inconclusive (§12).
**Changed 2026-07-31 — the 21-DTE winner test reads the ask, not the mid** (`current_ask` arg to
`management_verdict`; None keeps mid-only behavior for the backtest, whose Black-Scholes marks have
no spread). A synthetic illustration: a put sold at $1.00 with a $0.90 mid and a
$1.10 ask looks profitable at the mid, but closing at the ask would realize a loss.
The apparent win sits inside the bid-ask spread. This is the §4 quote-artifact problem (BIS Bulletin 95, deep-OTM
mids lie) reaching a branch that had no guard for it: `STOP_CONFIRM_RUNS` protects the loss side, and
nothing protected the win side. Now a timer CLOSE requires P&L > 0 at **both** the mid and the ask;
up-at-mid-only holds (and does not alert — there is nothing to act on). **What did NOT change:** the
50% target, the stop, and the proximity gate. Their verdicts are unchanged; they now merely *quote*
the ask in the action string, since those strings get copied into Schwab tickets and the mid is not a
price you can pay. Confidence: **HIGH** on the direction (you cannot transact at the mid; this is
arithmetic, not a modeled edge), and the guard is conservative — it can only ever defer a close, never
force one. Not backtest-promoted: the backtest has no spreads to test it against.

**Corrected 2026-08-03 — a close is a LIMIT worked over a session, so never go quiet when the
target is a few cents away** (`decision.fill_odds_today`, `rules.FILL_ODDS_WORKABLE_PCT`). The
07-31 fix above was right that you cannot pay the mid, but it turned "the ask is 5c too high
*right now*" into a silent HOLD (`alert=False`). That is the wrong output: the account owner rests the
order himself and watches whether it hits, so one instantaneous quote must not decide the day
for him. The 21-DTE up-at-the-mid-only branch is now verdict **WORK** — an action, not a hold
— carrying the limit to place (the mid, clamped below the credit so a fill is a real win), the
P&L if it fills, and the **modelled odds it trades there before the bell**. It still never
CUTs, and if the limit doesn't fill the position simply rides. The 50% branch got the same
treatment: it quotes the 50% mark (or the offer, when the offer is already through it) rather
than an ask that isn't a 50% close.
**How the odds are computed:** the offer has to fall by `d`, which through delta is an
underlying move of `d/|delta|`, against the name's own daily sigma `price × RV/√252` (the same
RV and √252 as the no-chase guard, §1) scaled by `√(fraction of session left)`. Then
`P(touch) = 2·Φ(−move/σ)` — the reflection principle, whose factor of 2 *is* the "many chances
during the day" effect, since the price need only trade there once. Session fraction is why
the available time matters: the same target generally has more modeled chances
to be touched early in the session than shortly before the close.
**Confidence: MEDIUM, and printed as an estimate everywhere it appears.** It is P(the price
*trades* there), which overstates P(*we are filled*) — someone still has to cross to us. It
ignores IV drift and spread narrowing, both of which usually *help* a resting buy limit, so it
errs low, the safe direction for a "should I bother" call. Driftless is the deliberate null:
assuming an intraday direction would be the no-chase mistake in a new place. Trailing RV is a
poor guide on an event day (§5a). `FILL_ODDS_WORKABLE_PCT` is a **wording** dial only — it
never suppresses an alert, because an unfilled limit costs nothing and there is no probability
at which silence beats telling him the number.

**Implemented 2026-06-29 — opportunity-cost surfacing.** The *right* trigger to close
an unthreatened position is **opportunity cost** — free the collateral only when there's a materially
better home for it — not the clock. `monitor.py` now reads the day's screener candidates
(`state/last_screen.json`, today's only) and, for any position it is **holding**, surfaces an advisory
note when a candidate (a) has a real edge (positive `ev_dollars`), (b) fits the cash the hold would free,
and (c) earns at least `REDEPLOY_BEAT_RATIO`× the hold's annualized premium yield. The yardstick is
symmetric: annualized premium yield on the collateral committed, where the hold's "premium still at
stake" is its current mid (what holding to a clean OTM expiry recovers vs closing now). `opportunity.py`
holds the pure logic. **This SURFACES, it does not decide** — it never flips the verdict or pings; the
close stays a logged judgment call. This is deliberately *not* the invented `OPPORTUNITY_EXIT_BEAT_RATIO`
removed above (which auto-decided CLOSE/HOLD in code off a made-up number); it is an eligibility/
surfacing split like the covered-call gate (§11), and `REDEPLOY_BEAT_RATIO` is a labeled, tunable
appetite knob, not a backtested edge. The yield math is self-regulating: a fresh position has most of
its premium still at stake (high hold-yield, hard to beat → no note), while a matured or near-expiry
hold has little left (low hold-yield, easy to beat → note), so churn pressure rises exactly as the hold's
remaining edge thins.

**Removed 2026-06-18 (was invented or borrowed):** the 75% "near-max" rule came from
an Option Alpha study on *defined-risk SPY credit spreads* optimizing Sharpe — wrong
instrument, wrong metric for our cash-secured puts. The "fast capture (50% in ≤⅓ of
window)", "profit-velocity (50% in ≤½)", and the keep-vs-redeploy gate
(`OPPORTUNITY_EXIT_BEAT_RATIO`) were our own additions with no backtest behind them.
If we ever want to beat plain "close at 50%", the move is to **backtest a specific
alternative**, not to hand-tune thresholds. The idle-cash / SWVXX discussion that fed
the redeploy gate is no longer part of winner management; `IDLE_CASH_APY` / `SWVXX_APY`
remain defined only as context for the entry-side cash-fit check.

## 4. Managing losers — the highest-value lever (and the most counterintuitive)

**Cutting losers preserves the equity curve far more than locking winners does.**
In a SPY 16-delta strangle backtest, closing *only losers* at −100% ended **76%
more profitable with ~80% lower max drawdown** than closing only winners at +50% —
*despite a ~17-point-lower win rate.* *(Project Finance. Confidence: HIGH.)* This
is the single most important empirical result in this document.

**But a rigid fixed-multiple stop is NOT clearly good and can be the worst
outcome:**

| Rule | Basis | Confidence |
|------|-------|------------|
| **Do not treat "stop at 2× credit" as mechanical gospel.** A −200% stop was the *worst* performer in an 11-yr strangle study: in trending tapes you stop out of trades that mean-revert, and in a real crash (Feb 2018) losses blow *through* the stop — you can't get filled near it. | Project Finance short-strangle & short-put (41,600-trade) studies. | HIGH. |
| **Make loss management regime-dependent.** When VIX is elevated, be more willing to cut/defend (adding a loss-exit improved both average P&L and drawdowns in high-VIX states). In calm regimes, lean toward holding/rolling a tested position rather than stopping into noise. **Enforced in code 2026-07-07** — `STOP_HIGH_VIX_ENTRY` conditions the 2× stop on the VIX at entry (§3): auto-CUT for high-VIX entries, alerted advisory for calm-tape entries. | Project Finance short-put study (verified 3-0, 2026-07-07 review). | HIGH on direction; the VIX-20 line is a MEDIUM judgment dial. |
| **A mark is not a loss — deep-OTM quotes lie under stress.** In the 5 Aug 2024 VIX spike, bid-ask spreads on deep-OTM puts blew out to >80% of mid (vs ~25% normal) with *asymmetric* widening that mechanically inflated mids; SEC DERA corroborates. A P&L-based exit that reads one mid print can realize a fake loss at the worst possible price. **Enforced 2026-07-07** — `STOP_CONFIRM_RUNS` requires the 2× mark to persist across consecutive monitor runs before CUT (§3). Exits that read the *underlying* (strike proximity) or *facts* (bad news) are never deferred. | BIS Bulletin 95 (Todorov & Vilkov, 2024), verified 3-0. Consistent with the IV-markup failure mode described in §3. | HIGH on the artifact mechanism (SPX data; single-name transfer is conservative extrapolation). The 2-run dial is MEDIUM. |
| **Risk exits remain unconditional:** stock within ~5% of strike, or a confirmed company-specific bad-news catalyst (guidance cut, fraud, regulatory action, exec departure) → act immediately, regardless of P&L. Capital preservation first. | Repo discipline + Sinclair (plan risk in advance). | HIGH. |
| **A mean-reversion story never overrides a risk exit — the steady-state trap.** "It's only IV markup, it'll come back, hold it" assumes the move was noise in a stationary world. Markets aren't stationary; sometimes the move is a real repricing and the put never reverts. So a 2× stop, a 5%-strike-proximity touch, or confirmed bad news fires *regardless* of any "it'll revert" reasoning — that is precisely what the stop is for. The variance premium is the pay we already collected for the non-steady-state tail; the stop is the circuit breaker for when the tail actually arrives. (Note the asymmetry vs §3: time alone never *forces* a cut on a far-OTM loser, but a real adverse move always does — the difference is whether the strike is genuinely threatened, not whether we have a comforting story.) | Risk-policy principle; Kydland-Prescott rules-over-discretion; Sinclair. | HIGH on the principle. |

## 5. Earnings & catalysts — the reconciled rule (replaces the old blackout)

**Earnings is NOT a disqualifier, and a scheduled earnings date is NOT a reason to
close early.** This reverses the old `POSITIONS.md` "earnings blackout / close at
50% on catalyst" rule, which was un-sourced *and* contradicted the screener's
design.

- **Why:** the earnings event premium is the one place single-name selling has a
  documented edge (§0). Selling a put **structured outside the implied earnings
  move** harvests the post-earnings IV crush. Fleeing the print throws the edge
  away. *(Review of Finance 2025; Cboe. Confidence: HIGH on direction.)*
- **The condition that makes it safe:** the strike must sit **outside the implied
  move over the contract's life**, which is now enforced by the `delta ≤ MAX_DELTA`
  gate (§2) — delta *is* the market's probability of finishing ITM, and a dated
  event inside the contract is already priced into it. Older implied-move
  wording must not be used to reinterpret the current delta gate; otherwise one
  candidate could receive opposite verdicts depending on which rule the reader
  assumes. If you want the cross-check by hand, use the **lognormal** 1-SD floor —
  `spot × exp(−IV × √(DTE/365))`, not `spot × (1 − IV × √(DTE/365))`; the linear
  form is exactly the error that got the old gate deleted (§2). A typical
  single-name earnings move is ~5–15%; a 30%+ cushion sits far outside it. Earnings
  risk is bimodal — size for the 28% tail (§7).
- **The play when you hold a deep-cushion winner into its earnings:** capture the
  **IV crush** — hold through the print, then **close right after** on the
  collapse, rather than (a) closing early and forgoing the crush, or (b) carrying
  needless assignment risk into the final days. Log it as a deliberate
  earnings-crush hold, not a passive default.
- **Macro catalysts (CPI/FOMC/geopolitical)** are not company-specific bad news;
  the cushion covers ordinary macro vol. Only a *confirmed company-specific*
  bad-news catalyst disqualifies (§4, risk exit).

## 5a. Scheduled share-supply events — the limit of the §5 blessing

**A dated share-supply event inside the contract's life blocks ACT.** IPO lockup
expiries, announced secondaries, and index deletions. Enforced in code
(`standing_risk.py`, called from `screener.py`); the calendar lives in
`standing_risk.json`. The name demotes to WATCH with a `watch_reason` — it is not
deleted from the screen.

- **Why this is not just §5 again:** §5 blesses selling through *earnings* for a
  specific mechanical reason — you are paid an inflated IV going in and you harvest
  the crush coming out. A lockup expiry has no crush to harvest. The IV is elevated
  for the same "known dated event" reason, but the event resolves as **supply
  arriving**, and nothing about it repays you on a schedule. Treating all dated
  events alike is how §5 gets over-read into "IV already prices it, so sell it".
- **What the literature actually supports:** lockup expiries carry small but real
  negative abnormal returns, ~1–3% around the unlock, concentrated in VC-backed
  names with heavy insider overhang *(Field & Hanka 2001; Bradley et al. 2001;
  Brav & Gompers 2003)*. **That average is not the reason for this rule** — a 1–3%
  drift does not threaten a 30% cushion. The reason is that it is an *uncompensated*
  exposure: we hold the tail without the offsetting crush that makes §5 work, and
  the tail is fat precisely in the cases this gate will fire on (huge float
  increase, thin trading history, no prior print to anchor on). **Confidence:
  MEDIUM** — the direction is documented, the block itself is a judgment call about
  what this book is willing to be unpaid for, not a backtest of this book.
- **Generic example:** a recently listed company can have earnings and a large
  lockup expiry within the same contract window. Elevated option volatility may
  reflect both events, but only earnings provides the anticipated post-event
  volatility crush. A short price history also makes IV-rank estimates unstable;
  passing the VRP arithmetic does not remove the separate supply-event block.

## 5b. Standing disqualifiers — an agent may open one, only the account owner closes one

A confirmed company-specific bad-news catalyst (§4) becomes a **standing
disqualifier**: a row in the owner's local `standing_risk.local.json` carrying a pre-written, falsifiable
`clears_when` bar. Enforced in code (`standing_risk.py` → `screener.py`), which
demotes the name to WATCH with the reason attached.

- **The daily agent MAY add a disqualifier it discovers. It may NEVER set `cleared`,
  delete a row, or trade around one.** Only the account owner clears it, and only against the
  written bar. Mitigation short of the bar — a settlement schedule, a supportive
  filing, an absence of fresh headlines — is logged under `checked` and changes
  nothing.
- **Why the asymmetry:** the disqualified name is usually the richest thing on the
  board (that is *why* its IV is fat), so the agent re-checking it every morning has
  a standing incentive to find a reading under which it is fine. A supportive
  filing or mitigation schedule may change the narrative without satisfying the
  documented clearing criterion. Keeping the written bar stable prevents the same
  unresolved facts from producing opposite entry verdicts on successive runs.
  *(Kydland-Prescott rules-over-discretion; §8. Confidence: HIGH on the principle.)*
- **"No fresh bad news today" is not evidence the risk resolved.** Absence of
  headlines is the normal state of live litigation.

## 6. Rolling

Roll **down-and-out only when all four hold**, else close and redeploy:
1. it's a genuine **net credit**, 2. the new strike is still **above meaningful
support**, 3. you'd be **content owning shares** at the new strike, 4. the duration
extension is **modest** (not a 3–4 month "rescue" roll). Repeated rescue-rolls just
compound losses and lock up capital in a broken trade. *(Project Finance / options
practitioners. Confidence: MEDIUM — framework, not a clean backtest.)* This aligns
with our close-vs-open $/day opportunity-cost math.

## 7. Position sizing

| Rule | Basis | Confidence |
|------|-------|------------|
| **Size on assignment exposure (strike × 100 × contracts), not premium at risk.** **Inherited full-deployment policy:** every approved CSP uses 100% of deployable 401k cash, rounded down to whole cash-secured contracts. The strategy is intentionally selective; a rare approved trade must be meaningful. One POSITION per underlying (`MAX_POSITIONS_PER_UNDERLYING`), no averaging down, and no second CSP while the first fully sized position is open. | Configured reference strategy policy. | Policy, requiring owner review. |
| **Full deployment is intentional concentration.** This is a high-conviction mandate, not a diversification claim. A bad assignment or stop can materially impair the whole sleeve; approval requires accepting that risk before the order is shown. | Configured reference strategy policy. | Policy, requiring owner review. |
| **Correlated-group cap** (`CORR_GROUP_CAP_PCT`, 100%): it remains a structural check but cannot reduce a first fully sized position. Since full deployment leaves no capital for another put, it prevents only an accidental second position in partial/future states. Shares held in the account remain FYI-only. | Configured reference strategy policy. | Policy, requiring owner review. |
| **"Trade often" only diversifies if trades are uncorrelated.** 30 short puts on 30 tech names is **not** 30 independent occurrences — in a selloff they lose together (correlations → 1). Treat the book's real exposure as far more concentrated than the trade count suggests. | tastytrade LLN logic + independent critiques. | STRONG. |
| **Concentration is an inherited policy choice.** The configured full-deployment sizing intentionally concentrates strategy cash. One position per underlying is allowed, with contract count computed from cash-secured assignment exposure by `rules.position_contracts`. A new owner must review this mandate before using live candidates. | Chosen strategy policy vs concentration evidence above. | Policy, not a diversification or return claim. |
| **Cross-account holdings are FYI-only — never a verdict input**. What the account owner owns in other accounts may surface as a one-line "heads up, you already hold $X of this" note in the Slack copy, and that is its entire role. It never gates, demotes, score-penalizes, or vetoes a 401k candidate, and never appears in an override rationale. Reason: this book's mandate is to find rich, high-probability premium and execute; portfolio-level risk is the account owner's job, and the system only sees a partial slice of net worth — scoring "total portfolio risk" on incomplete data is theater that distorts the ranking away from the richest edge (the deterministic engine's 0.65 overlap penalty was removed the same day). **Still gating, because it is THIS book's own risk:** one position per underlying, no duplicate underlying, no correlated names stacked inside the 401k. | Configured policy; separation-of-concerns (the human is the portfolio risk layer). | Mandate, not an edge claim. The §7 concentration evidence above still stands — it is simply owned by the account owner, not the bot. |

## 8. Mechanical discipline

- **Pre-commit exits while calm; never improvise risk management.** "Decisions must
  be planned in advance, when emotions are calm." The documented edge of mechanical
  systems is mostly the *elimination of discretionary mistakes* (panic, hope).
  *(Sinclair; Kydland-Prescott rules-over-discretion. Confidence: HIGH on the
  principle.)*
- **The defensible claim is "any consistent rule beats ad-hoc decisions,"** not
  "mechanical always wins." Best practical form is **structured discretion**: fixed
  rules with bounded, pre-defined latitude — which is exactly the
  screener-(deterministic)-then-judgment-layer design in `CRON_PROMPT.md`. Every
  override of the deterministic decision must be logged for later grading.

## 9. The benchmark reality (keep expectations honest)

- Even the *diversified* PUT index draws down **~30%+ in crashes** (−32.7% in 2008,
  −28.4% PUTW in 2020) and **lags badly in V-shaped recoveries** (2020 nearly flat
  while the S&P roared back). Put-writing is fat-left-tail / thin-right-tail.
- The investable ETF (PUTW) returned ~8.3%/yr vs the S&P's ~13.3%/yr over the last
  bull-heavy decade. **A single-name book should expect a thinner edge and a fatter
  tail than that.** Our job is to be paid for the VRP and the earnings premium
  while surviving the tail — not to beat the S&P in a bull market.

---

## 10. Known development gaps (the "underdeveloped" backlog)

Honest list of what this system still lacks to be genuinely best-in-class:

- **IV Rank / IV percentile per name** is not yet tracked over time; the screener
  has VRP but not a true IVR (needs a rolling 1-yr IV history). `experiments/snapshot.py`
  accumulates the data to compute it eventually.
- **No realized edge measurement.** Without a supplied local fill history, none of the rules
  above are validated *on this book*. The decision-journal / grading loop
  (`decision_journal.py`, `skipped_backcheck.py`, expiry snapshots) exists to build
  that evidence — but it needs trades and time. Until then we borrow the index/SPY
  evidence and discount it for single-name transfer.
- **No correlation/exposure model.** We have no aggregate beta or crypto-exposure
  measure across the 401k's holdings + open puts, so "no correlated positions" is
  enforced by eyeball, not math.
- **Loss management is not yet VIX-state-dependent in code.** `monitor.py` reads the
  `STOP_MULTIPLE` flag from `rules.py` and labels it correctly as regime-dependent,
  but it does not yet pull live VIX to auto-escalate; the judgment layer does that.
- ~~Code vs docs gap~~ **CLOSED 2026-06-05:** `monitor.py`, `screener.py`, and the
  cash/recommend path now import every threshold from `rules.py`. There is no longer
  a hardcoded rule number anywhere in the live code.

---

## 11. Covered-call overwrite sub-sleeve — eligibility vs. verdict

The covered-call scanner (`covered_calls.py`) writes calls against shares already held
in the 401k. It runs in two stages, and the distinction is the whole point:

1. **Eligibility** (`CC_MIN_OTM_PCT`, `CC_MAX_SPREAD_PCT`, `CC_MIN_PREMIUM_DOLLARS`) —
   cheap pre-filters that answer "is this contract tradeable?" They say nothing about
   whether the trade is *worth doing*. `CC_MIN_PREMIUM_DOLLARS` is an absolute floor
   ($25); a thin overwrite on a big position clears it trivially.

2. **Verdict** (`CC_MIN_ANNUALIZED_PCT`) — the decision. A candidate earns **SELL**
   only if its premium, annualized over the capital it would cap (`spot × 100 ×
   contracts`), clears the floor. Otherwise the verdict is **SKIP** and we hold the
   shares uncapped. This is the same contract as `monitor.py`'s `do`: one verdict,
   decided in code, transcribed verbatim by every renderer, never re-derived in chat.

**Why this exists.** Without the verdict gate the scanner surfaced "check IBIT $39
call" — $88 premium, 16% OTM — as if it were a recommendation. Annualized on the
$6,720 it caps, that's ~11%/yr to sell the upside of a convex bitcoin proxy: the exact
asset you hold *for* its right tail. Eligibility passed it; judgment rejects it. A
surfaced trade must be an actionable trade (SELL with an order ticket, or SKIP with a
reason) — never homework punted to a chat session.

**Status:** heuristic, not backtested like the §3 triad. `CC_MIN_ANNUALIZED_PCT = 20`
is a tunable overwrite-appetite knob, not a measured edge — raise it to cap less,
lower it to cap more. The sleeve is recommendation-only; it never places orders.

---

## 12. Measured on our book (backtest)

**The paper-variant lane is retired (2026-07-23) — its final result is the one finding it
ever produced, and it's worth keeping.** From 2026-04-20 to 2026-07-17 a paper book ran
"baseline" rules that froze the **April** regime (7–10% OTM strikes ≈ 0.25–0.35 delta, 75%
profit target, red-day entry, no VRP gate) against real Schwab quotes on imaginary money.
Result: **38 closed, 51% win rate, −$3,110** (plus a 3-trade post-earnings variant, −$619);
every large loser was a shallow strike stopped out at 2× (HUBS −$2,011, META −$1,441, NET
−$1,361). The live book over the same window — deep delta-gated strikes, 50% target, VRP
gates — went **9/9, +$3,582**. That is the closest thing we have to on-book evidence that
the June–July rule changes (delta gate §2, 50% triad §3, VRP floors §1) beat the rules they
replaced. Confounds, stated honestly: different names, different entry days, live strikes
sometimes hand-walked deeper, small n, one correlated market regime — supporting evidence,
not proof. **Why retired rather than fixed:** the lane duplicated the whole rules engine in
`variants/` (a DRY violation this repo bans elsewhere), drifted stale within weeks (its
"baseline" claimed to mirror live while being three rule-generations behind), had no
statistical power at ~50 correlated trades/quarter, and in three months influenced zero
rule decisions — every actual rule change came from live-trade postmortems, literature, or
measured screener output. Code preserved in `archive/paper_variants/`; the journal
(`state/paper_options.json`) is stamped concluded. What remains of the experiments lane is
`experiments/snapshot.py` (daily IV history → future IV-rank, §10) and the passive audit
loop on **real** trades (shadow_tracker, skipped_backcheck, near_miss, decision_journal) —
those measure the book we actually run, which is where §10's "no realized edge measurement"
gap closes at n≥20.

A replay engine (`backtest/`) runs the **actual production decision functions** — the
real entry gate (`screener_select.best_put_from_chain`) over a synthetic Schwab-shaped
chain, and the real management core (`decision.management_verdict`) — over historical
underlying closes for our universe. It exists to replace borrowed conviction (the §3
triad is backtested by tastytrade on *at-the-money index* premium; we apply it to
*deep-OTM single-name* puts) with conviction measured on our own instruments.

**What this can and cannot prove — the load-bearing boundary.** We have free historical
*underlying* closes (Schwab) but **not** historical *option* prices/greeks. So the
engine **reconstructs** each option's price path with Black-Scholes from the close plus
a **modeled** vol input (`RealizedVolModel`: trailing realized vol × an assumed `vrp_mult`).
Consequently:

- It **cannot measure absolute edge** — that lives in the IV-vs-RV gap, which a modeled
  vol *assumes* rather than observes.
- It **can measure relative rule behavior** — given a modeled path, does managing at
  21 DTE beat holding to expiry? Does a 2x stop help or hurt the distribution?
- Every result ships with a **`vrp_mult` sensitivity sweep** (1.0 / 1.2 / 1.5). A
  finding earns promotion **only if its ranking holds across all columns** (the
  robustness gate in `report.py`). A finding that flips when the vol assumption moves
  is "we don't know," not evidence, and is flagged NOT robust.

The pricer is **pluggable**: the day paid recorded-chain data lands, swap
`BSReconstructedPricer` for a `RecordedChainPricer` and rerun the identical harness —
no engine rewrite — and §12 graduates from *relative/modeled* to *absolute/measured*.

**Modeling limitations (documented, not hidden):** European exercise, no dividends, no
early assignment (negligible for deep-OTM managed puts); a **flat vol across strikes**
(no put skew), which understates OTM-put premium — so under the free model the 2%
premium gate clears mainly in high-vol regimes, and entry counts rise with `vrp_mult`.
`RISK_FREE_RATE = 0.04` is a constant, not a strategy knob (sweeps are insensitive at
our DTEs).

**Run it:**
```
backtest/run.py   --symbol NVDA --start 2018-01-01 --vrp-mult 1.0,1.2,1.5   # one name
backtest/sweep.py --start 2018-01-01                                        # universe grid
```

**Findings.** *(Populated by `sweep.py` → `report.py`. Until a robust finding lands here,
no threshold in `rules.py` changes on backtest grounds.)* Promotion of any threshold is
still a **human** editing the number in `rules.py` and citing the robust finding here —
identical to every other rule's discipline. Modeled-backtest evidence (relative,
assumption-swept) and live-trade evidence (absolute, tiny-n) are kept separate and never
conflated.

- **2026-06-29 — 21-DTE timer, loser side (`MANAGE_DTE_CUTS_LOSERS`). Modeled backtest:
  INCONCLUSIVE — did NOT drive the rule change.** On NVDA (2018–2026, the only universe name
  cached at write time), `MANAGE_DTE=21` vs `MANAGE_DTE=None` are *identical* at vrp 1.0/1.2
  (the 50% target fires before the timer ever binds) and differ only marginally at vrp 1.5
  (n=68 vs 64; total return +1.23% vs +1.26%). The single large drawdown (~213% at vrp 1.5) is
  present **with and without** the timer — the timer did not prevent the tail it exists to guard.
  Thin n, one name, modeled flat-vol: this neither promotes nor vetoes the change. The change to
  stop cutting far-OTM losers on the clock was therefore adopted on **§4 literature (HIGH) +
  configured strategy policy**, and is labeled as such — not as a measured finding. Re-measure across the
  full universe (needs a Schwab price fetch per name) and again with recorded chains before
  upgrading confidence.

---

## 13. The wheel — an assignment starts a cycle, not a bag

Built 2026-07-23 (`wheel.py`) from the IDEAS.md #2 analysis. No CSP has ever been assigned
(9-for-9 closed early), so this is dormant plumbing until one is: it changes no live verdict,
gate, or sizing. The put half (`csp_401k`) and the call half (`covered_calls.py`) already
existed; the wheel is *connecting* them into one tracked cycle — put → shares → calls → cash —
plus one discipline rule.

| Rule | Basis | Confidence |
|---|---|---|
| **Never sell a call struck below the cycle's cost basis (strike − credit/share).** The canonical wheel trap: assigned on a falling name, sell calls at/below basis "to keep the income coming", and a bounce calls the shares away at a **locked-in loss**. Enforced twice: `covered_calls.best_call` floors the strike at `wheel.min_call_strikes()` for wheel symbols, and `wheel.record_call` refuses to link a below-basis call. If no call ≥ basis clears the CC gates (§11), the verdict is the ordinary SKIP — hold the shares uncapped and wait; that *is* the discipline. | Documented wheel failure mode (IDEAS.md #2); arithmetic. | HIGH on the mechanism — it is bookkeeping, not an edge claim. |
| **One cycle, one P&L.** Assignment closes the put trade as `result: "assigned"` with `pnl = credit` (the option leg realized in full); the cycle record links the put, every call sold against the shares, and the share disposition. Cycle P&L = put credit + call P&Ls + (share exit − put strike) × shares — the share leg is measured vs **strike**, not basis, because the credit already lives in the put trade's pnl (vs-basis would double-count it). Per-trade pnl stays authoritative for the circuit breaker and receipts; the cycle is a **view** that stops an assignment from becoming a disconnected bag whose true cost nobody remembers. | DRY with the trade log; `reconcile.warn` now points an in-the-money "close" at `wheel.py assign` instead of a cash close. | HIGH — bookkeeping. |
| **The wheel adds no new edge and no loosening.** It is the same long-beta + short-vol trade in a second wrapper (FUND.md §2C) — running it does not diversify the book. Wheel calls reuse every CC gate unchanged (§11: OTM %, spread, premium floor, `CC_MIN_ANNUALIZED_PCT` verdict). Realistic disciplined yield is ~1–2%/month of deployed capital, not the advertised 2–3% (which only appears in high-IV windows, exactly when assignment risk peaks); income is small and linear, the tail large and sudden (a 30% gap-down erases ~10 months of premium). | FUND.md §2C; IDEAS.md #2 yield analysis. | MEDIUM on the yield numbers (literature/practitioner consensus, not our data — 0 cycles closed). |

---

## Sources

**Index performance & VRP (HIGH confidence, peer-reviewed / Cboe-commissioned):**
- Bondarenko, *Historical Performance of Put-Writing Strategies* (Cboe, 2019) — https://cdn.cboe.com/resources/education/research_publications/PutWriteCBOE19_v14_by_Prof_Oleg_Bondarenko_as_of_June_14.pdf
- Asset Consulting Group, *Index Option Writing for Liquid Enhanced Risk-Adjusted Returns* (Cboe, 2012) — https://cdn.cboe.com/resources/indices/documents/pap-assetconsultinggroup-cboe-feb2012.pdf
- Carr & Wu, *Variance Risk Premia*, RFS 2009 — https://engineering.nyu.edu/sites/default/files/2019-01/CarrReviewofFinStudiesMarch2009-a.pdf
- Bakshi & Kapadia, *Delta-Hedged Gains and the Negative Market Volatility Risk Premium*, RFS 2003 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=267106
- Bakshi & Kapadia, *Volatility Risk Premiums in Individual Equity Options*, JoD 2003 — https://people.umass.edu/~nkapadia/docs/Bakshi_Kapadia_JoD_Fall_2003.pdf
- Bollerslev, Tauchen & Zhou, *Expected Stock Returns and Variance Risk Premia*, RFS 2009 — https://public.econ.duke.edu/~boller/Published_Papers/rfs_09.pdf
- Gourier, *Pricing of Idiosyncratic Equity and Variance Risks* — https://www.aeaweb.org/conference/2016/retrieve.php?pdfid=20683&tk=dkQRZR5n

**Earnings event premium (HIGH on direction):**
- Alexiou, Goyal, Kostakis & Rompolis, *Pricing Event Risk*, Review of Finance 29(4), 2025 — https://academic.oup.com/rof/article/29/4/963/8079062

**Management backtests (HIGH where backtested):**
- Project Finance — short strangle management (11-yr) — https://www.projectfinance.com/short-strangle-management/
- Project Finance — taking losses vs taking profits — https://www.projectfinance.com/taking-losses-vs-taking-profits/
- Project Finance — short put management (41,600 trades) — https://www.projectfinance.com/short-put-management/
- Option Alpha — SPY put credit spread backtest (75% vs 50%) — https://optionalpha.com/blog/spy-put-credit-spread-backtest
- tastytrade — Managing Winners / Varying Profit Targets — https://www.tastytrade.com/tt/shows/market-measures/episodes/managing-winners-varying-profit-targets-12-04-2015

**2026-07-07 adversarial research review (103-agent deep-research pass; 25 claims
adversarially verified, 14 confirmed / 11 refuted).** Outcome: one rule changed (the
2× stop conditioning above); 50%-target, 28–45 DTE, and fractional-Kelly all
re-confirmed on current evidence; skew filters, formulaic VIX sizing, and ML/IV-surface
signals evaluated and rejected (skew is ~44% structural default/cyclicality risk —
Wu & Tian, Management Science 2024; the residual-skew-tradability and VIX-scaler claims
failed verification 0-3). **Also refuted 0-3: that IV−RV *predicts* subsequent
variance-selling returns** — so the §1a VRP gate is conservatism (only sell rich vol),
not a validated timing signal, exactly as its MEDIUM label says. New sources:
- Dew-Becker & Giglio, *The Death of Alpha in Index Options?* (Chicago Fed WP 2025-17) — https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf
- Todorov & Vilkov, *The August 2024 spike in the VIX* (BIS Bulletin 95) — https://www.bis.org/publ/bisbull95.pdf
- Heston & Todorov, variance risk premia across assets (AEA 2024) — https://www.aeaweb.org/conference/2024/program/paper/hiTeT8SE
- Wu & Tian, implied-vol skew structural decomposition, Management Science 70(6) 2024 — https://ideas.repec.org/a/inm/ormnsc/v70y2024i6p3566-3580.html

**Independent skeptical backtests (cite alongside tastytrade claims):**
- SJ Options — *Does Tastytrade Work?* — https://www.sjoptions.com/does-tastytrade-work/
- SteadyOptions — *Selling Short Strangles and Straddles: Does it Work?* — https://steadyoptions.com/articles/selling-short-strangles-and-straddles-does-it-work-r516/

**Sizing & discipline:**
- Sinclair interview (Amberdata) — https://blog.amberdata.io/euan-sinclair-on-volatility-risk-management-and-trading-psychology
- Sinclair, *Confidence Intervals for the Kelly Criterion* — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2457368
- Kydland & Prescott, *Rules Rather Than Discretion*, JPE 1977 — https://ideas.repec.org/a/ucp/jpolec/v85y1977i3p473-91.html

**Caveat on sourcing:** tastytrade publishes findings as TV segments, not papers, and
under-reports variance/drawdown; their study *designs* are consistent and reproduced
by the independent backtests above, but treat their precise P&L decimals as
approximate. Several earnings/IV-crush magnitude figures come from practitioner
sites, not primary docs, and are rated MEDIUM accordingly.
