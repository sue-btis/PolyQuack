# PRD — Polyquack


## 1. Product Overview

### Product

Polyquack is a personal quantitative research tool. It continuously ingests perpetual futures data from Polymarket Perps and Hyperliquid, and pairs the same asset across the two platforms. With that data it tests trading methods on paper, without real money. Each method ends with a verdict backed by evidence.

The first method is **E1**: being long on one platform and short on the other to collect the funding rate spread without betting on price.

### Problem / Purpose

Between Sep 3 and Oct 26, 2026, Polymarket Perps funding was lower than Hyperliquid's in 36 of the 38 cryptos that are on both platforms. A simulated strategy on that spread returned +8.7% a year out of sample (`docs/discovery/findings.md`, Angle E).

That probe did not measure several things:

- basis risk: the two prices drifting apart;
- slippage: paying a worse price than the best in the book;
- liquidations;
- the platform maturing.

Polyquack exists to measure those things with its own data and to decide, with a criterion set in advance, whether E1 works. It also exists so that every future method goes through the same test before risking money.

### Product Philosophy

- **Never invent data.** Missing data is shown as a gap.
- **Profit is always net.** If it doesn't subtract fees, slippage and basis, it isn't profit.
- **The criterion is written before looking at the result.**
- **Research first.** Discarding a method with evidence is a good outcome.

## 2. Target Users and Usage Context

### Primary User

The author. A developer with an engineering background, who researches quantitative methods and may trade with their own money in stages. They spend 5 to 15 hours a week on it. Today they run the analyses with loose scripts (`docs/discovery/spikes/`).

### Secondary Users

Portfolio visitors: recruiters and the technical community. They only see the public view, which is read-only.

### Usage Context

- Ingestion runs nonstop, 24/7.
- The author checks the dashboard from time to time and works in research sessions.
- E1's decisions are hourly, so there is no need to react in seconds.
- Everything runs from the author's computer or a small server, never colocated with the platforms' servers.

## 3. Goals

- G-001 — Have continuous, reliable funding, order book and price data from both platforms, with every asset paired and gaps marked.
- G-002 — Know, hour by hour, how much E1 would have earned on paper after fees, slippage and basis.
- G-003 — Measure E1's basis risk and liquidation risk with the project's own data.
- G-004 — Issue E1's verdict after 4 weeks of paper trading, against the threshold of ≥ 10% a year net on collateral.
- G-005 — Have any new method tested with the same discipline: prior criterion, no peeking at the future, net profit and verdict.
- G-006 — Publish a portfolio piece with the methodology and the studies, without revealing the winning parameters.

## 4. Non-Goals

- NG-001 — Trading with real money. The MVP only trades on paper.
- NG-002 — Placing orders on any platform, even with minimum amounts.
- NG-003 — Directional trading: betting that the price goes up or down.
- NG-004 — Other people using the system to trade or receiving alerts.
- NG-005 — Platforms other than Polymarket Perps and Hyperliquid, such as centralized exchanges or Kalshi.
- NG-006 — Polymarket prediction markets: ladders, multi-option arbitrage and calibration (DEC-01, DEC-02).
- NG-007 — Angles C (weather), D (crypto options) and E2 (perps against prediction markets) (DEC-04).
- NG-008 — Competing on speed or reacting in under a second.
- NG-009 — Investment recommendations for third parties, or showing returns that do not come from a documented test.

## 5. Core User Journeys

### J-001 — Start ingestion

1. The author starts Polyquack for the first time.
2. Polyquack discovers the instruments on both platforms and pairs those that are the same asset.
3. It retrieves the available funding history of each pair and starts continuously storing funding, order books and prices.
4. The author sees on the dashboard how many pairs there are, which ones have no counterpart, and since when there is data for each.

### J-002 — Preregister and run E1 on paper

1. The author registers E1 as a method: rules, parameters, metric, 4-week horizon and verdict criterion (≥ 10% a year net on collateral).
2. Polyquack saves the registration with its date and leaves it unchanged.
3. Every hour, Polyquack decides on paper, for each pair, whether to open, hold, reverse or close a position, and records the result.

### J-003 — Review progress

1. The author opens the dashboard.
2. They see, per pair and in total: funding spread, paper positions, net profit with breakdown, basis, distance to liquidation and gaps.
3. They see whether ingestion is healthy: last reading per source and open gaps.

### J-004 — Receive the verdict

1. When the 4 weeks are up, Polyquack compares E1's annual net profit against the preregistered criterion.
2. It issues the verdict (continue, discard or investigate further) with the breakdown that justifies it and the number of variants tested.
3. With that verdict, the author decides whether E1 moves to the next stage.

### J-005 — See the public view

1. A visitor opens the public view.
2. They see the methodology, the ingestion status and the studies the author marked as publishable.
3. They do not see private parameters or positions.

## 6. Product Capabilities

### CAP-001 — Ingestion and pairing (ETL)

Discovers the instruments on both platforms and pairs the same asset. Continuously stores funding, book snapshots, mark price, index price, instrument parameters and current fees. Retrieves funding history. Marks every gap.

Edge cases it covers:

- new instruments;
- instruments that move to close-only or disappear;
- API usage limits;
- network or machine outages.

### CAP-002 — Method evaluator

Stores each method's preregistration and counts its variants. Calculates annual net profit on collateral, with the breakdown of funding, fees, slippage and basis. Guarantees that no decision uses future data. When the horizon is reached, issues the verdict. Refuses to qualify a period with too many gaps.

### CAP-003 — E1 on paper

Every hour it calculates the funding spread per pair and applies the preregistered rules. Simulates entries and exits at the executable price of the book, for the reference size and with the taker fee. Credits funding to each leg. Measures basis and distance to liquidation, and treats as liquidated the leg that would have been.

### CAP-004 — Private dashboard

Shows the ingestion status, E1's paper positions and results, and progress toward the verdict. Warns when a source stops arriving.

### CAP-005 — Public view

A read-only view with the methodology, the ingestion status and the studies the author marks as publishable. By default, everything is private.

## 7. Functional Requirements

### FR-001
Polyquack obtains the list of instruments of Polymarket Perps and Hyperliquid at startup and obtains it again at least once a day.

### FR-002
Polyquack pairs as a pair the instruments of the two platforms that track the same asset, and lists unpaired instruments separately.

### FR-003
When an instrument appears, moves to close-only or disappears from a platform, Polyquack records the change with its date and updates the pair's status.

### FR-004
Polyquack stores each funding rate collected on each paired instrument, with the collection time reported by the platform.

### FR-005
When pairing a new pair, Polyquack retrieves the funding history of both platforms from the earliest available date, without going back before Sep 3, 2026.

### FR-006
Polyquack stores order book snapshots of each paired instrument on both platforms. Each snapshot includes the best bid, the best ask and the cumulative volume on each side up to 0.5% of the mid price.

### FR-007
Polyquack stores the mark price and the index price of each paired instrument.

### FR-008
Polyquack stores the parameters of each instrument that affect a trade: maximum leverage, maintenance margin, minimum notional and close-only status. Each parameter is kept with its effective date.

### FR-009
Polyquack stores the current fee schedule of each platform, with its effective date.

### FR-010
Polyquack records as a gap each interval in which it did not obtain an expected data point, with the source and the cause when known.

### FR-011
When the connection is restored after an outage, Polyquack requests again the missing funding from each platform's history and closes the gaps it manages to fill with real data.

### FR-012
The author can register a method. The registration includes rules, parameters, metric, horizon, verdict criterion, reference size per leg and reference leverage. Polyquack stores the registration date.

### FR-013
Once a method has run for the first time, Polyquack does not allow editing its registration. Any change is saved as a new variant of the same method.

### FR-014
Polyquack shows how many variants of each method have been registered and run.

### FR-015
Polyquack calculates, for each method and period, the net profit and splits it into funding collected, fees, slippage and basis effect.

### FR-016
Polyquack calculates, for each method and period, the annual return on collateral, according to BR-003.

### FR-017
When a method's horizon is reached, Polyquack issues a verdict (continue, discard or investigate further) by comparing the result against the preregistered criterion. The verdict carries the breakdown and the number of variants.

### FR-018
If a pair's gaps in the period exceed the maximum accepted (PD-013), Polyquack leaves that pair out of the verdict and reports it with the gaps that prevent it. Each pair is measured only between its pairing and its delisting. The run is qualified with the remaining pairs (PD-021). If none remain, the run is not qualified.

### FR-019
Every hour, Polyquack calculates each pair's funding spread as the Polymarket Perps rate minus the Hyperliquid rate, for the same hour.

### FR-020
Every hour, for each pair, Polyquack applies E1's preregistered rules and records the decision: open, hold, reverse or close.

### FR-021
When opening or closing a paper position, Polyquack calculates each leg's price by walking the most recent book snapshot prior to the decision, for the reference size, and adds the current taker fee.

### FR-022
Each time a platform collects funding, Polyquack credits or debits the corresponding paper leg the amount according to its side and size.

### FR-023
While a paper position is open, Polyquack records the basis: the difference between the asset's prices on the two platforms and its change since entry.

### FR-024
While a paper position is open, Polyquack calculates each leg's distance to liquidation with the reference leverage and the current maintenance margin.

### FR-025
If the price crosses a paper leg's liquidation level, Polyquack records that leg as liquidated, with its loss and its liquidation fee, and marks the other leg as uncovered.

### FR-026
Polyquack records each paper trade with hour, pair, side, prices, size, fees and the decision that originated it.

### FR-027
The private dashboard shows, per pair: the current funding spread, the cumulative spread, the paper position, the net profit with breakdown, the basis, the distance to liquidation and the gaps.

### FR-028
The private dashboard shows, per source, the time of the last reading received and the open gaps.

### FR-029
The private dashboard shows a warning when a source goes more than 15 minutes without delivering data.

### FR-030
The private dashboard shows progress toward E1's verdict: days elapsed out of 28 and cumulative annual net return against the 10% threshold.

### FR-031
The author can mark each study and each method as public or private. Everything new starts private.

### FR-032
The public view shows the methodology, the ingestion status and the results of the studies marked as public.

### FR-033
The public view never shows parameters of private methods, paper positions or hourly detail of private methods.

## 8. Non-Functional Requirements

### NFR-001 — Data integrity
In an audit of 200 randomly sampled funding readings and 200 book snapshots, 100% match what the source reported at that moment. Zero filled, interpolated or carried-forward values (BR-001).

### NFR-002 — Funding completeness
In any 4-week window, after the recovery of FR-011, each pair has funding from both platforms for at least 99% of the hours.

### NFR-003 — Book snapshot frequency and continuity
Each paired instrument has a book snapshot at least every 60 s (PD-012). In any 4-week window, at least 95% of the minutes have a snapshot. The rest are marked as gaps.

### NFR-004 — Recovery
After a network outage or a machine restart, ingestion resumes by itself within 10 minutes or less of the network and the machine coming back.

### NFR-005 — Respect for usage limits
Polyquack never exceeds the usage limits published by each platform. On a "too many requests" response, it slows down until the source recovers. Goal: zero access blocks in 4 weeks.

### NFR-006 — Cost
The total operating cost (servers, data and services) does not exceed 20 USD a month.

### NFR-007 — Reproducibility
Re-evaluating the same method with the same data gives exactly the same result, decision by decision and cent by cent.

### NFR-008 — No future information
An automated test walks through all the decisions of a run and verifies that none used a data point with a timestamp later than the decision. Zero violations.

### NFR-009 — Dashboard freshness
The data the dashboard shows is at most 5 minutes behind the last stored reading.

### NFR-010 — Coverage
Polyquack sustains NFR-002 and NFR-003 with at least 100 pairs at once. Today there are 38.

### NFR-011 — Credential security
The MVP operates without trading credentials. No key, secret or credential lives in the public repository. An automated review of the repository finds zero.

### NFR-012 — New sources
Adding a new data source (for example, Polymarket's prediction markets) does not force changes to the methods already registered or their results.

### NFR-013 — Runs from home
No MVP function requires reacting in under 1 minute. All of them work from a home connection in Mexico.

## 9. Business Rules and Invariants

- BR-001 — Missing data is recorded and shown as a gap. It is never filled in, interpolated or replaced by the last known value (CON-004).
- BR-002 — A method's profit is always net: funding collected, minus fees, minus slippage, plus or minus the basis effect, minus liquidation losses.
- BR-003 — Annual return on collateral = period net profit ÷ collateral × 365 ÷ days in the period. A position's collateral is the sum, across the two legs, of notional ÷ reference leverage. A run's collateral is the maximum collateral committed at the same time during the period (PD-020).
- BR-004 — A decision made at instant t only uses data with a timestamp earlier than or equal to t.
- BR-005 — A method's verdict criterion is set before its first run and does not change. Changing it creates a new variant, which counts as one more attempt (CON-006).
- BR-006 — In E1, the two legs open with the same notional and opposite sides: long on one platform and short on the other.
- BR-007 — Funding convention: if the rate is positive, longs pay and shorts collect; if it is negative, the reverse.
- BR-008 — A pair's funding spread is the Polymarket Perps rate minus the Hyperliquid rate, for the same hour.
- BR-009 — E1 advances to the next stage only if, after 4 weeks on paper with the project's own data, it yields ≥ 10% a year net on collateral (DEC-03).
- BR-010 — A paper leg that would have been liquidated is recorded as liquidated; its loss enters the method's result.
- BR-011 — No real-money trading in the MVP.

## 10. Product / UX Principles

- UX-001 — Every profit number on the dashboard or in the public view shows its breakdown or a link to it.
- UX-002 — A gap looks different from a zero, with its own visual mark and a label such as "no data".
- UX-003 — Dashboard texts use the language of the brief's glossary (funding, leg, basis), not internal system names.

## 11. Hard Constraints

- CON-001 — Real money enters in stages: data, then live paper, and real money only with a cap set by the author and if the method passed its criterion.
- CON-002 — A single operator user. The public part is read-only.
- CON-003 — Hybrid visibility: the ingestion code, the evaluator and the studies are public; the parameters and strategies that show an edge stay private.
- CON-004 — Never invent data.
- CON-005 — Before any real-money trading, it is checked that the platform allows trading from the author's jurisdiction. For E1 the list of blocked countries is enough; the legal risk is assumed by the author (DEC-05).
- CON-006 — A method's criterion is written before testing it and is not moved afterwards.
- CON-007 — Trading credentials never live in the public repository.
- CON-008 — MVP sources: Polymarket Perps and Hyperliquid (DEC-01).
- CON-009 — Operating budget: up to 20 USD a month (CR-003, `docs/discovery/findings.md`).
- CON-010 — Runs from home: no servers colocated with the platforms (CR-002, `docs/discovery/findings.md`).

## 12. MVP Scope

### In

- FR-001 to FR-011 — Ingestion and pairing of the two platforms, with gaps marked and funding recovery (CAP-001).
- FR-012 to FR-018 — Evaluator with preregistration, variants, itemized net profit, return on collateral and verdict (CAP-002).
- FR-019 to FR-026 — E1 on paper with book prices, funding per leg, basis and liquidation (CAP-003).
- FR-027 to FR-030 — Private dashboard (CAP-004).
- FR-031 to FR-033 — Read-only public view (CAP-005).

### Out

- Trading with real money or sending orders (NG-001, NG-002).
- Polymarket prediction markets, ladders and calibration (NG-006).
- C, D and E2 (NG-007).
- Additional platforms (NG-005).
- ML models to predict which funding spreads persist. They go to future scope.

## 13. Success Criteria

- SC-001 — Ingestion runs 4 weeks straight meeting NFR-002 and NFR-003.
- SC-002 — On day 28 of paper trading, Polyquack issues E1's verdict with its breakdown, with no manual intervention in the calculation.
- SC-003 — The NFR-001 audit comes out with no differences.
- SC-004 — The NFR-008 test comes out with no violations in E1's run.
- SC-005 — Re-evaluating E1 with the same data reproduces the exact verdict (NFR-007).
- SC-006 — The public view is online with the methodology and at least one published study.

## 14. Future Product Scope

- Move E1 to real money with a cap, if its verdict passes (requires PD-016, PD-017 and PD-018).
- ML to predict which funding spreads will persist.
- Trade as maker to lower fees.
- More perpetuals platforms to compare funding.
- Polymarket prediction markets: ladders, multi-option arbitrage and net calibration.
- Angles C, D and E2.

## 15. Product Decisions

| ID | Question | Status | Decision | Decided by | Date | Quote | Affects |
|---|---|---|---|---|---|---|---|
| PD-001 | What is the project called? | Decided | Polyquack | Author | 2026-10-25 | «Polyquack» | The whole package |
| PD-002 | Public or private? | Decided | Hybrid: code and studies public; parameters and strategies with an edge, private | Author | 2026-10-25 | «Híbrido (Recomendado)» | CON-003, CAP-005, FR-031 to FR-033 |
| PD-003 | Who uses it? | Decided | Only the author; the public part is read-only | Author | 2026-10-25 | «Solo yo (Recomendado)» | CON-002, NG-004 |
| PD-004 | How far does real money go? | Decided | In stages: data, paper and real money with a cap if the method passes | Author | 2026-10-25 | «Por etapas (Recomendado)» | CON-001, BR-011 |
| PD-005 | What is the first focus? | Decided (replaced by PD-006) | Arbitrage and contradictions in prediction markets, plus calibration | Author | 2026-10-25 | «si creo que podemos empezar con eso» | Historical |
| PD-006 | What is the core and the first strategy? | Decided | ETL plus evaluator, with E1 (funding between Polymarket Perps and Hyperliquid) as the first strategy; scope is expanded to perpetuals | Author | 2026-10-26 | «si mas bien seria eso ETl + evaluador con E1. Como primer decision» | §1, CAP-001 to CAP-003, CON-008 |
| PD-007 | Do ladders come in as a second strategy? | Decided | Out for now | Author | 2026-10-26 | «Las escaleras se quedan fuera por ahora.» | NG-006, §14 |
| PD-008 | Research or profit first? | Decided | Research first | Author | 2026-10-26 | «Investigación primero (Recomendado)» | §1 Product Philosophy |
| PD-009 | When does E1's verdict come out and with what threshold? | Decided | At 4 weeks on paper; passes with ≥ 10% a year net on collateral | Author | 2026-10-26 | «4 semanas (Recomendado)» and «≥ 10 % al año» | BR-009, FR-030, SC-002 |
| PD-010 | Do C, D or E2 come in? | Decided | Out for now; reconsidered after E1's verdict | Author | 2026-10-26 | «Fuera por ahora (Recomendado)» | NG-007, §14 |
| PD-011 | Legal opinion before real money? | Decided | No; the platform's list of countries is enough; the author assumes the risk | Author | 2026-10-26 | «No, me basta con la lista de países» | CON-005 |
| PD-012 | How often is a book snapshot taken? | Decided | Every 60 s | Author | 2026-10-26 | «Confirmo PD-012 a PD-015 con los valores propuestos: foto cada 60 s, límites de faltantes, 1,000 USD por pata y 2x.» | NFR-003, FR-006 |
| PD-013 | What percentage of gaps prevents qualifying a period? | Decided | More than 5% of hours without funding or more than 10% of minutes without a book snapshot in the period | Author | 2026-10-26 | «Confirmo PD-012 a PD-015 con los valores propuestos: foto cada 60 s, límites de faltantes, 1,000 USD por pata y 2x.» | FR-018 |
| PD-014 | What is the reference size per leg for calculating slippage? | Decided | 1,000 USD per leg in E1's preregistration | Author | 2026-10-26 | «Confirmo PD-012 a PD-015 con los valores propuestos: foto cada 60 s, límites de faltantes, 1,000 USD por pata y 2x.» | FR-012, FR-021 |
| PD-015 | What is the reference leverage for collateral? | Decided | 2x per leg in E1's preregistration | Author | 2026-10-26 | «Confirmo PD-012 a PD-015 con los valores propuestos: foto cada 60 s, límites de faltantes, 1,000 USD por pata y 2x.» | FR-012, FR-024, BR-003 |
| PD-016 | Capital cap for the real-money stage | Open | — | — | — | — | CON-001, §14 |
| PD-017 | Will the system place orders on its own or stay with alerts? | Open | Decided before the real-money stage | — | — | — | NG-002, §14 |
| PD-018 | Stage thresholds for strategies other than E1 | Open | Decided when each strategy comes in | — | — | — | BR-009 |
| PD-019 | Which studies and which parts of the code are published? | Open | The author decides piece by piece, following CON-003 | — | — | — | FR-031 |
| PD-020 | How is the collateral of a run with several simultaneous positions or with hours without positions calculated? | Decided | The maximum collateral committed at the same time during the run | Author | 2026-10-26 | «Máximo usado a la vez (Recomendado)» | BR-003, FR-016, `docs/design/domain.md` |
| PD-021 | At what level is the gap limit of PD-013 applied? | Decided | Per pair. A pair that exceeds the limit is left out of the verdict and reported; the run is qualified with the others. Each pair counts only from when it is paired until it is delisted | Author | 2026-10-26 | «Por par, excluyendo el par (Recomendado)» | FR-018, PD-013, `docs/design/domain.md`, `docs/design/data/schema.dbml` |

## 16. Product Traceability

| Capability / Journey | Requirements |
|---|---|
| CAP-001 / J-001 | FR-001 to FR-011, NFR-001 to NFR-006, NFR-010, NFR-013, BR-001 |
| CAP-002 / J-002, J-004 | FR-012 to FR-018, NFR-007, NFR-008, BR-002 to BR-005, BR-009 |
| CAP-003 / J-002 | FR-019 to FR-026, NFR-007, NFR-008, BR-006 to BR-008, BR-010, BR-011 |
| CAP-004 / J-003 | FR-027 to FR-030, NFR-009, UX-001 to UX-003 |
| CAP-005 / J-005 | FR-031 to FR-033, NFR-011, CON-003 |
