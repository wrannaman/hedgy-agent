# FUND.md — The Canonical Fund Document

**This is THE single source of truth for the whole book.** What edges we harvest,
what we refuse to trade, how every sleeve is sized and risk-managed, how the morning
engine surfaces trades, and how the repo is organized. Everything else references
this file; nothing duplicates it.

**The DRY rule for this repo (read first, enforce always):**
- A fact lives in exactly **one** place. Fund-wide strategy/risk reasoning → here.
  Fund-wide *numbers* → `fund_rules.py`. Sleeve-specific reasoning → that sleeve's
  `RULES.md`. Sleeve-specific *numbers* → that sleeve's `rules.py`.
- Every other file (`CLAUDE.md`, each strategy's `CLAUDE.md`/`README.md`/`CRON_PROMPT.md`)
  **points** here or to a `rules.py`; it restates no rules and hardcodes no thresholds.
- Code imports numbers from a `*_rules.py`. If you're typing a rule number into a
  script, you're doing it wrong — put it in the params file and import it.
- `../../CLAUDE.md` (repo root) remains the **safety floor** (credentials, account
  scope, "never place orders without explicit confirmation"). This file never
  weakens it.
- **[`WORLDVIEW.md`](WORLDVIEW.md)** holds our current macro/discretionary theses
  (the "judgment" in systematic-with-judgment). It tilts marginal calls and
  watchlists; it never overrides a rule or a number. Consult it last, after the
  mechanical gates.

Last rebuilt: 2026-06-05, from a four-desk evidence pass (equity factors/trend,
options income/overlays, short/hedging/event-driven, portfolio construction/risk).
Sources at the bottom; confidence ratings inline.

---

## 1. Mandate & honest expectations

We run a small, multi-sleeve, **systematic-with-judgment** book across the account owner's
accounts. We harvest a few genuinely-documented edges, diversify across *uncorrelated*
return streams, size for the tail, and execute mechanically. We are not trying to
beat the S&P in a bull market — we are trying to earn a **better Sharpe** by lowering
volatility and drawdown while staying long the things that compound.

**The bar is high and we state it honestly:**
- S&P 500 buy-and-hold long-run Sharpe ≈ **0.4–0.6**. That's what the whole apparatus
  must beat *after costs and taxes* to justify the effort. *(Robust.)*
- Active retail traders historically **underperform by ~3.7%/yr** (Barber & Odean),
  taking more vol for less return. We assume we are average until the data says
  otherwise. *(Robust.)*
- **Realistic target: Sharpe ~0.6–1.0**, achieved mostly by cutting vol/drawdown, not
  by outsized returns. Any *measured* Sharpe > ~1.5 on this book almost certainly
  means too-small a sample, a hidden short-vol tail, or survivorship — not real edge.
  *(Robust.)*

---

## 2. Edge taxonomy — what we harvest, what we refuse

This is the heart of the fund. Each line is rated for whether the edge is real and
whether a small **manual retail** account can actually capture it.

### 2A. Edges we HARVEST (real, documented, retail-capturable)

| Edge | What it is | Evidence | Capturable |
|------|-----------|----------|-----------|
| **Index variance risk premium** | Sell index puts/calls (PutWrite/BuyWrite, ~30δ "BXMD" sweet spot). IV > realized by ~4 pts, persistently. | PUT index Sharpe **0.65 vs S&P 0.49**, 1986–2018; Carr-Wu, Bakshi-Kapadia. | HIGH |
| **Earnings event premium** | Sell premium struck *outside* the implied earnings move; collect the IV crush. The **one** single-name options edge. | Review of Finance 2025; implied > realized move ~72% of earnings. | MED (tail-heavy) |
| **Trend / time-series momentum** | 10-month/200-day regime + dual-momentum market-on/off. Cheapest crash protection that exists. | Faber: sidestepped the −51% 2008 DD, <1 trade/yr; Antonacci GEM ~+440bps/yr, +Sharpe, −30% DD. | HIGH |
| **Cross-sectional momentum (long-only)** | Own 12-1 winners via ETF/basket. | Jegadeesh-Titman; AQR "Fact, Fiction & Momentum," 212 yrs/40 mkts. | MED |
| **Quality / low-vol (long-only)** | Tilt to high gross-profitability, low-beta names/ETFs. Lowest turnover. | Novy-Marx (JFE 2013); Baker-Bradley-Wurgler "greatest anomaly." | HIGH |
| **Value, *paired with momentum*** | Cheap names, only as the −0.5-correlated partner to momentum. | AQR "Value & Momentum Everywhere"; combo cuts the crash tail. | MED |
| **PEAD (post-earnings drift, long-only)** | Buy large positive surprises, hold weeks. | 60 yrs documented; still persists. | YES |
| **Covered-call overwrite** | Sell ~30δ calls on shares we already own when call IV is rich. | BXMD beat S&P cumulatively; income at ⅔ the vol. | HIGH |
| **Defensive ballast** | T-bills (only unconditional hedge), managed-futures ETF (crisis alpha), small gold. | T-bills +ve 2008/2020/2022; CTAs +ve 2008/2022. | YES |

### 2B. Edges we REFUSE (−EV drags, or infeasible for retail)

| Refused | Why | Evidence |
|---------|-----|----------|
| **Single-stock shorting** | Capped gain / unbounded loss / borrow >100%/yr on 200+ names / squeeze risk. Edge accrues to lenders, not us. | Acadian; the asymmetry is fatal. Use a defined-risk long put for a bearish view. |
| **Systematic put protection / collars / long VXX** | You *pay* the same VRP we exist to *sell*. CLL collar Sharpe **0.30**; VXX **−99%** since inception (contango). | Bondarenko; CXO/AQR collar; six-figure-investing VXX. |
| **Classic pairs / stat-arb** | The simple documentable edge decayed to ~0 after ~2000; what works needs quant infra we don't have. | Gatev et al. + decay literature. |
| **Sector rotation** | Most overfit-prone, fragile to lookback/rebalance; few independent bets. | Faber sector work + fragility critiques. |
| **Merger arb** | ~4% gross, fat deal-break tail that clusters in crashes (= selling uncovered index puts); can't diversify enough at our size. | Mitchell-Pulvino. *(Tiny satellite at most.)* |
| **Turn-of-month effect** | The classic US-equity TOM premium decayed after publication; recent tests find no significant effect in US large caps (residual lives in international/EM ETFs we don't trade for it). | Quantpedia TOM; QuantSeeker 2025 re-test. |
| **Overnight drift** | Close-to-open captures most long-run equity return — statistically real, but harvesting it means daily round-trips; spread + slippage eat the per-night edge at retail size. | Overnight-anomaly literature (Cooper et al. line); cost arithmetic. |

### 2C. The one risk insight that governs everything

**Most "income" strategies are the SAME trade in different wrappers.** Cash-secured
puts, covered calls, the wheel, short strangles, PMCCs — all are **long-beta +
short-vol**. Stacking them does **not** diversify; one crash hits them all together.
Real diversification only comes from **genuinely uncorrelated streams** — the trend
overlay, managed futures, and T-bills. The free lunch (Asness/AQR) is *combining
uncorrelated edges*, and our short-vol sleeves are not uncorrelated with each other.

**The wired regime switch (2026-06-10):** because the short-vol sleeves are one
correlated bet, they share one stand-down signal — the **VIX/VIX3M term-structure
ratio**. Contango (ratio < 1, ~80% of days) is when IV most reliably overstates
realized vol and short premium earns its keep; backwardation (ratio ≥ 1) is the
near-term-fear regime where short-vol losses cluster. `risk.evaluate()` rejects
every NEW short-premium candidate in backwardation (threshold in `fund_rules.py`:
`VIX_BACKWARDATION_RATIO`); open positions are managed, not auto-closed, and an
unavailable quote fails open (unknown regime ≠ stand-down). Long-only sleeves are
untouched. *(Term-structure-as-signal: Johnson 2017 "Risk Premia and the VIX Term
Structure"; practitioner replications.)*

### 2D. Watch list (documented, not traded)

- **Pre-FOMC announcement drift** — S&P accrues ~+49bps in the 24h before scheduled
  FOMC announcements (Lucca & Moench 2015, NY Fed SR512); replications through Dec
  2024 find it persists, now concentrated in **press-conference meetings** and
  stronger in high-vol regimes. Too episodic (8 days/yr) to be a sleeve at our size;
  the morning brief prints an awareness line when an announcement is near
  (`fund_rules.py: FOMC_DATES_2026`). Awareness, not a gate, not a trade.

---

## 3. The sleeves

Each sleeve is one edge, one account scope, one rules source. Status reflects what
exists in the repo today vs. what the roadmap (§8) builds.

| # | Sleeve | Edge (§2) | Type | Account | Rules source | Status |
|---|--------|-----------|------|---------|--------------|--------|
| 1 | **csp_401k** | Index VRP + earnings premium | Uncovered puts | 401k (read-only → manual) | `strategies/csp_401k/RULES.md` + `rules.py` | **Live** |
| 2 | **Covered calls** | Overwrite premium | Covered calls | accounts holding shares | `strategies/csp_401k/covered_calls.py` → fold into sleeve | Partial |
| 3 | **Earnings IV-crush** | Earnings event premium | Short premium / spreads | 401k (in screener) | csp_401k `RULES.md` §5 | **Folded into #1** (cushion covers the implied move — not a separate sleeve) |
| 4 | **Trend overlay & ballast** | Trend + defensive | Long ETF / T-bills / mgd futures | 401k core + taxable | `strategies/trend/rules.py` | **Live** |
| 5 | **Factor tilt** | Momentum/quality/low-vol/value | Long ETF/basket | taxable + 401k core | `strategies/factor/rules.py` | **Live** |
| 6 | **PEAD** | Post-earnings drift | Long equity | taxable (rec-only) | `strategies/pead/rules.py` | **Live** (needs `FINNHUB_API_KEY` in `.schwab`) |
| 7 | **portfolio_watch** | (risk lens, not an edge) | Monitoring | all accounts | `strategies/portfolio_watch/` | Live |
| 8 | **index_vrp** | Index VRP (defined-risk) | Put spreads on index ETFs + $XSP (§1256) | recommendation-only | `strategies/index_vrp/rules.py` | **Live, scaled (Phase 8)** — trend-gated, flip-exit, 75% take, $80k width cap |

Every sleeve must declare its account scope and inherit the repo safety floor. A
sleeve never widens scope, never imports another sleeve's code (copy, don't import),
and surfaces recommendations only — **no order is placed without the account owner's explicit
confirmation in a live conversation.**

---

## 4. Portfolio construction & risk (fund-wide; numbers in `fund_rules.py`)

The two most-robust ideas in the whole research pass — and the cheapest to run:
1. **Diversify across genuinely uncorrelated sleeves.** The only free lunch. *(Robust.)*
2. **Size by volatility, not dollars.** Vol-targeting raises the equity/short-vol
   sleeves' Sharpe and cuts drawdowns everywhere. *(Robust — Harvey et al.)*

**What's enforced in code today** (`risk.py` / `fund_engine.py`, numbers in `fund_rules.py`):
single-name flag + bucket cap + cash/defense-buffer + catalyst + VRP edge; **per-trade
risk cap** (3% of book; 6% for defined-risk spreads — the backtested ladder rung);
**max concurrent positions** (2, cash-secured puts only — spreads are capped by
**total open width in dollars** instead, `SPREAD_DEPLOYMENT_CAP_DOLLARS`, because the
count cap was a committed-cash proxy sized for CSPs and the dollar cap is what bounds
the worst simultaneous crash-month loss); **trend gate + flip-exit** on the index-VRP
sleeve (no new spreads below the 40-wk SMA, close open ones when the regime flips —
Phase 8); **graduated de-gross** on book drawdown;
**grading kill** of negative-expectancy sleeves. **Future controls (need infra, not yet
built):** sleeve vol-targeting (per-sleeve vol estimation), net-long/gross caps (delta
tracking across accounts), rebalance bands (the ETF-core rebalancer). These are described
below as policy but are deliberately *not* dead config in `fund_rules.py` until wired.

**Risk dial (the posture knob, enforced by `judge.py`).** One setting — `defensive` /
`neutral` / `aggressive` — that says how much cushion and edge the book demands before a
short-premium trade may *surface*. It does not change the sleeve scanners; it sets fund-wide
FLOORS (`min_cushion_pct`, `min_vrp` in `fund_rules.RISK_DIALS`) that the **judge** applies
on top of the sleeve's own gates, between the engine's ranking and the Slack send. So the same
~30-delta index spread (whose cushion is ~3–4% at high IV *by construction* — the CBOE
PutWrite sweet spot, not a bug) **surfaces when aggressive and is killed when defensive**. The
current level + the account owner's outlook live in `state/risk_posture.json` (data, re-dialed without a
code change) and print at the top of every brief and every Slack message, so each trade shows
the lens it was judged through. A killed trade drops to a `JUDGE … 🛑 <why>` line — visible,
never silently dropped; a borderline one is `JUDGE-FLAGGED (thin)` and surfaces labeled. The
dial is why a thin trade the sleeve mechanically allows still doesn't reach the account owner in a hot
market: posture is a separate decision from mechanics, and the judge is where the two meet.

**Sizing**
- **Fractional Kelly, ¼ ceiling.** ½-Kelly keeps ~75% of growth at ~¼ the variance;
  our edge estimates are noisy, so ¼ is the practical cap. The **per-trade risk cap**
  (`PER_TRADE_RISK_PCT`) is the wired expression of this. *(Robust.)*
- **Vol-target each sleeve** *(future)* to a set annualized vol, recomputed monthly;
  scale exposure inversely to recent realized vol.
- **Risk-parity-lite across sleeves:** size so each contributes *roughly equal risk*
  (dollars ÷ sleeve vol), not equal dollars.
- **Per-trade risk cap** on top of Kelly (a small % of capital at risk per name).

**Concentration / correlation / exposure**
- **≤ max single-name %** and **≤ max sector %** of the active book (params).
- **Correlated names = one bet.** Three semis is one semi position. Short puts on
  crypto-beta names stack on existing IBIT/COIN longs — count them together.
- **Net delta-adjusted exposure cap.** Short puts add positive delta; the income
  sleeve quietly raises net-long. Track net delta across *all* accounts so the book
  doesn't become 130% long into a drawdown.

**Drawdown control — the counterintuitive, important one**
- **Mechanical portfolio price-stops HURT** (death by a thousand cuts; worst on the
  trend sleeve). We control risk by **sizing up front, not liquidating after.** *(Moderate.)*
- The only sanctioned portfolio-level brake is **graduated de-grossing** (cut gross in
  thirds at set book-drawdown levels), never a flat liquidate-everything stop.
- Per-sleeve risk exits (e.g., csp_401k strike-proximity) still apply — those are
  sizing-aware, not portfolio panic-sells.

**Rebalance / turnover**
- **Threshold (band) rebalancing, not calendar** — Swedroe 5/25. Widen bands in
  taxable (tax friction); rebalance the 401k core freely (no tax friction).

---

## 5. Accounts & tax map

Balances drift daily — **never hardcode them** (see [[no-hardcoded-balances]]); source
is the latest dated `positions/*-Positions-*.csv` or the live Schwab client.

| Account | Access | Role in the fund |
|---------|--------|------------------|
| Configured options account | Read-only Schwab | Long-term ETF/stock **core** + the csp_401k uncovered-put sleeve (recommend → the account owner executes manually). Tax-deferred, but **read-only so we can't auto-execute** here. |
| Other locally configured portfolio accounts | Not linked to a client | Recommendation-only today (CSV-sourced). The taxable accounts are where active/short-term sleeves would run if/when execution is wired. The Roth is the *tax-optimal* home for the income sleeve if it ever becomes tradeable. |

**Tax reality that shapes sleeve placement:**
- Short-horizon P&L is **ordinary income** (≤1yr); a high-turnover options/PEAD book
  in taxable carries a real **~1%+/yr tax drag** — budget for it, don't pretend it's free.
- **§1256 60/40** treatment for broad-based index options (SPX/XSP) makes index-option
  hedges/income tax-superior to single-name options.
- **Wash-sale across taxable + IRA/401k permanently forfeits the loss** (Rev. Rul.
  2008-5) — never replace a taxable loss-sale with the same name in the 401k.
- Tax-optimal placement (income/short-term in the tax shelter) **collides with the
  401k being read-only.** Until an executable IRA/Roth exists: keep the 401k as the
  long-term core, run active sleeves in taxable, and budget the tax drag.

---

## 6. The morning engine (the daily machine)

**Goal:** every morning, sweep a wide universe across all sleeves, apply the canonical
risk gates, and surface **one ranked, actionable brief** of the best trades — with the
exact orders — for the account owner to execute. Deterministic scanners do the math; the judgment
layer handles wording, catalyst checks, and overrides (structured discretion). It
**recommends only**; nothing is placed without explicit confirmation.

**Pipeline**
1. **Universe** (one canonical list): S&P 500 + liquid sector/factor ETFs + the account owner's
   watchlist + index options (SPX/XSP). Defined once, imported everywhere.
2. **Per-sleeve scanners** (each emits ranked candidates + the edge it harvests):
   - VRP put screener — `csp_401k/screener.py` *(live)*.
   - Covered-call overwrite — owned shares with rich call IV.
   - Earnings IV-crush — names with earnings in window, high IV rank, deep-OTM premium
     outside the implied move.
   - Trend/regime — 200-day MA + dual-momentum market-on/off + ballast target.
   - Factor tilt — momentum/quality/low-vol/value relative-strength ranks.
   - PEAD — recent large earnings surprises to ride the drift.
   - Portfolio exposure — `portfolio_watch` *(live)*: net delta, concentration, sector.
   - Tax-aware de-gross — `portfolio_watch/rebalance.py` *(live)*: cheapest-tax way to
     raise cash on the taxable accounts (loss-harvests first, big winners last, sheltered
     rotations are tax-free), plus a trailing-stop flag on concentrated winners. Encodes
     the tax reality below (all-in ~35% LT for a CA filer; harvest losses; never replace a
     taxable loss in the 401k). Recommendation-only; the agent folds material lines into Slack.
3. **Risk gates** (from `fund_rules.py`): drop/трim any candidate that breaches sizing,
   single-name %, sector %, correlation-bucket, or net-exposure caps **given current
   holdings**. This is where "would this make us too concentrated/too net-long?" is enforced.
4. **Rank** survivors across sleeves by expected edge ÷ risk (risk-adjusted, capital-aware).
5. **One brief**: top N actionable trades with exact orders + which edge each harvests +
   portfolio status + anything that needs defending. Concise — action + justification,
   not walls of text (see [[feedback-notification-brevity]]).

**Governance:** every recommendation cites the rule it came from (this file or a
`rules.py`); every override of a deterministic call is logged for grading; the
compounding loop (snapshot world-state → grade winner/loser over time, see
[[feedback-compounding-loop]]) records each decision so sleeves earn or lose their
allocation on **evidence**, not vibes. A sleeve needs ~100 independent trades before
its measured edge is trustworthy; judge on multi-quarter horizons; pre-commit a written
kill criterion per sleeve. **Wired (2026-06-10):** the engine appends every morning's
world-state + gated candidates + ranked recommendations to `state/brief_journal.jsonl`,
and `grade.py` marks each recommendation to outcome at its own expiration/horizon —
so the ~100-sample bar is reached on *recommended* outcomes in months, not years
(always labeled hypothetical/held-to-expiration, never conflated with realized P&L).

---

## 7. Build roadmap (phased — each phase is independently useful)

- **Phase 0 — canon & guardrails ✅ DONE:** `FUND.md` + `fund_rules.py`. Single source of
  truth; csp_401k conforms.
- **Phase 1 — risk core ✅ DONE:** `risk.py` (+ `test_risk.py`, 6/6) applies the gates —
  bucket concentration, cash + defense buffer, edge (VRP), catalyst, single-name flag —
  against live holdings, core-exempt and mandate-consistent. Reconciled the old 5% cap
  that contradicted the csp_401k concentrated mandate.
- **Phase 2 — morning engine ✅ DONE (v1):** `fund_engine.py` loads the live 401k book,
  pulls candidates from the live scanners (VRP puts, covered calls, portfolio_watch),
  auto-detects catalysts, gates, ranks, prints one brief. Runs end-to-end today.
- **Phase 2.1 — catalyst refinement ✅ DONE:** the catalyst gate is **beta-adjusted** —
  a name is only flagged if it falls more than `CATALYST_IDIO_PCT` beyond the market
  (QQQ); broad-beta selloffs (premium richest) no longer block sales.
- **Phase 3 — index-VRP sleeve ✅ DONE (v1):** `strategies/index_vrp/` scans SPY/QQQ/IWM/DIA
  for ~30/13δ defined-risk put spreads with positive VRP, wired into the engine. Surfaces
  clean candidates even when every single name is rejected (proven 2026-06-05). $XSP added
  2026-06-10 for §1256 60/40 tax + cash settlement (Phase 7).
- **Phase 4 — trend/ballast sleeve ✅ DONE:** `strategies/trend/` — Faber 40-week (~10mo)
  regime on SPY → risk-on/off + ballast (BIL/DBMF/GLD). The one uncorrelated stream.
- **Phase 5 — factor tilt ✅ DONE:** `strategies/factor/` — quality/low-vol/momentum/value
  ETFs ranked by 12-1 momentum; tilt toward the leaders vs SPY.
- **Deferred, on purpose (no slop):** **earnings IV-crush** is not a separate sleeve — the
  put screener already harvests it (cushion covers the implied move, RULES.md §5).
- **Phase 6 — grading loop ✅ DONE:** `grade.py` — realized per-sleeve scorecard (n, win%,
  P&L, expectancy) judged against `MIN_TRADES_FOR_EDGE`/`SLEEVE_KILL_EXPECTANCY`. Reports
  "insufficient sample" until a sleeve has the trades to prove an edge. Shown in the brief.
- **Phase 7 — iteration of 2026-06-10 ✅ DONE:**
  - **Vol-regime gate:** VIX/VIX3M backwardation stands down all new short premium
    (§2C) — wired in `risk.evaluate()` + `morning_decision/decide.py`.
  - **Brief journal + recommendation grading:** `fund_engine` snapshots world-state +
    every gated candidate + the ranked recommendations to `state/brief_journal.jsonl`;
    `grade.py` marks each rec to outcome at its own expiration/horizon
    (`state/rec_grades.jsonl`) and the brief shows a second, explicitly-hypothetical
    scorecard. The §6 compounding loop now accrues ~daily instead of per-closed-trade.
  - **PEAD sleeve built** (`strategies/pead/`), unblocked by the Finnhub
    earnings-surprise feed (`shared/earnings.py`) — long-only, taxable,
    recommendation-only, graded on 60-day excess return vs SPY.
  - **$XSP added to index_vrp** — §1256 60/40 + cash settlement (full SPX excluded:
    width always breaches the per-trade cap at this book size).
  - **FOMC awareness line** in the brief (§2D watch item; dates in `fund_rules.py`).

- **Phase 8 — index-VRP scaled ✅ DONE (2026-08-24):** the sleeve's first modeled
  backtest (`strategies/index_vrp/backtest.py` + `experiments.py`: SPY spreads
  2008→2026 on real daily VIX, skew-swept, all 17 start-years profitable) promoted
  four changes, wired the same day: **trend gate** (no new spreads with SPY below the
  40-wk SMA; stale signal fails closed), **flip-exit** (close open spreads on a
  risk_off flip — blocking-only rode 2022 down, −$74k → −$39k in the replay),
  **75% profit take** (spread-specific; the wing caps the tail the csp 50% rule
  guards), and the **dollar deployment cap** (`SPREAD_DEPLOYMENT_CAP_DOLLARS` of
  total open width, laddered in ~$10k rungs, replacing the CSP-era 2-slot count cap
  for spreads; per-trade defined-risk cap 6%). Judge dial gained a defined-risk
  cushion floor (2.5/3.0/5.0) — the naked-put floor was a structural ban on a ~30δ
  spread's 3–4%-by-construction cushion. The reference deployment cap is $80k;
  full-size modeled ≈$37.8k/yr, worst month
  −$42k, worst year −$39k, every 2008–2024 start year ends profitable — **MEDIUM
  confidence** (BS-modeled prices; crash fills come in worse). Sleeve trade log split out (`strategies/index_vrp/trade_log.py`);
  recommendation-only, as ever.

**Automation:** `run_daily.sh` (launchd `hedgy-agent.morning-roam`, weekday mornings, market-guarded)
now pre-runs the portfolio sweep + tax-aware `rebalance.py` + index-VRP/trend/factor/PEAD
scanners + `fund_engine.py` non-fatally and writes the unified brief to `state/morning_brief.txt`; the
morning agent reads it and folds the best cross-sleeve idea — and any material tax-aware
de-gross/harvest/trailing-stop line — into Slack. Execution stays manual + confirmed.

No phase places an order. Execution stays manual and confirmed until the account owner explicitly
wires and authorizes an account.

---

## 8. Sources

Full citations live with each desk's findings; the load-bearing ones:
- **Options/VRP:** Bondarenko 2019 (Cboe PUT/BXM/BXMD/CLL) — https://cdn.cboe.com/resources/education/research_publications/PutWriteCBOE19_v14_by_Prof_Oleg_Bondarenko_as_of_June_14.pdf ; Carr-Wu RFS 2009; Bakshi-Kapadia; Alexiou et al. *Review of Finance* 2025 (earnings).
- **Factors/trend:** AQR "Fact, Fiction & Momentum" — https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf ; Faber "Quantitative Approach to TAA" — https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf ; Daniel-Moskowitz "Momentum Crashes" (NBER w20439); Novy-Marx (JFE 2013); Baker-Bradley-Wurgler; Antonacci GEM.
- **Short/hedge/event:** Mitchell-Pulvino (risk arb); Gatev et al. (pairs decay); Acadian (short-selling cost); PEAD reviews; FINRA 26-10 (PDT rule replaced 2026-06-04); IRS §1256/§1091.
- **Construction/risk:** Harvey et al. "Impact of Volatility Targeting" (JPM) — https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf ; AQR "Death of Diversification…" ; Thorp on Kelly; Swedroe 5/25; Barber-Odean.
- **2026-06-10 evidence pass (Phase 7):** Lucca & Moench "The Pre-FOMC Announcement
  Drift" (NY Fed SR512) — https://www.newyorkfed.org/research/staff_reports/sr512.html ;
  pre-FOMC persistence through Dec 2024 — https://www.quantseeker.com/p/trading-the-fed-the-pre-fomc-drift
  and Applied Economics 2025 — https://www.tandfonline.com/doi/full/10.1080/00036846.2024.2322573 ;
  turn-of-month decay — https://www.quantpedia.com/strategies/turn-of-the-month-in-equity-indexes
  and https://www.quantseeker.com/p/turn-of-the-month-strategies-do-they ; VIX term
  structure as a short-premium filter — https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/ ;
  PEAD: Bernard & Thomas 1989/1990, Foster-Olsen-Shevlin 1984; earnings feed —
  https://finnhub.io/docs/api/earnings-calendar ; FOMC calendar —
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm ; §1256 (XSP/SPX).

**Sourcing caveat:** index/academic numbers are HIGH confidence; broker-blog backtests
(tastytrade/Spintwig for spreads/strangles) and single-author backtests (GEM) are
directionally consistent with theory but lower confidence — flagged at point of use.
The csp_401k single-name caveat applies fund-wide: index-level edges **shrink** on
single names (you trade diversified correlation premium for concentrated gap risk).
