# Polyquack Product Brief

Design size: standard

## Problem

The project started out looking for prices that don't add up in Polymarket's prediction markets. Discovery (`docs/discovery/findings.md` and `docs/discovery/polyquack.html`) showed several things:

- Those differences exist, but the fast ones last seconds.
- The slow ones are small or require months of tied-up capital.
- The public forecast is already in the price.

The strongest signal came from another product on the same platform: Polymarket Perps perpetual futures, launched on Sep 3, 2026.

- From Sep 3 to Oct 26, 2026, their funding rate was consistently lower than Hyperliquid's for the same cryptos: in 36 of 38.
- Being long on one platform and short on the other collects that difference without betting on price.
- A simulated strategy returned +8.7% a year out of sample.

What is not known is whether that difference survives what the probe did not measure:

- basis risk, that is, the two prices drifting apart;
- slippage;
- liquidations;
- the platform maturing.

There is also no reliable way to decide whether a method works or is luck before risking money.

## Target Users and Context

- Primary user: the author, who researches quantitative methods and may trade with their own money in stages.
- Secondary users: people who view the portfolio (recruiters, technical community); they only read results and the public demo.
- Usage context: a personal tool that runs continuously to collect data and scan, plus research sessions to study methods and issue verdicts.

## Desired Outcomes

- OUT-001 — Have continuous, reliable data on funding, order books and prices from Polymarket Perps and Hyperliquid. Each instrument must be paired with its asset on the other platform, and gaps must be marked as gaps, never filled in.
- OUT-002 — Know, hour by hour, how much E1 would have collected on paper after fees, slippage and basis risk.
- OUT-003 — Measure E1's basis risk and liquidation risk with the project's own data.
- OUT-004 — Have E1's first verdict after 4 weeks on paper: it advances to the next stage only if it yields ≥ 10% a year net on collateral (DEC-03).
- OUT-005 — Have every method tested end with a verdict (continue, discard or investigate further), backed by evidence and by a criterion set before the test.
- OUT-006 — A public portfolio piece with the ETL, the methodology, the studies and a read-only demo, without revealing the winning parameters.

The results of the previous version of the brief (prediction-market arbitrage, contradictions and calibration) are out of scope per DEC-01, DEC-02 and DEC-04.

## Scope

Included (MVP, per the Oct 26, 2026 decision):

- **ETL** that continuously ingests, relates and segments:
  - funding, order books and prices of the Polymarket Perps perpetual futures;
  - the same data from Hyperliquid;
  - the correspondence between instruments on the two platforms for the same asset.
  
  It is designed so that it can later add Polymarket's prediction markets without being redone.
- **Honest evaluation of methods:** real costs, no use of future information, criteria set before the test, and a verdict per method.
- **E1, cross-platform funding,** as the first strategy, on paper: it detects when it is worthwhile to be long on one platform and short on the other, and simulates what would have been collected.
- Personal research dashboard and a read-only public view.

Candidates outside the MVP until the author decides:

- Ladders: contradictions between threshold or date prediction markets. Out for now (DEC-02).
- Arbitrage within a single multi-option market and contradictions between related markets.
- Calibration study on resolved markets.
- C (weather), D (crypto options) and E2 (perps against prediction markets).

Excluded:

- Trading with real money in the MVP.
- Other people using the system to trade or receiving alerts.
- Platforms other than Polymarket (prediction markets and Perps) and Hyperliquid, in the MVP. For example Kalshi, bookmakers or centralized exchanges.
- Directional trading: betting that the price goes up or down.
- Investment recommendations for third parties.
- Promising or showing returns that do not come from a documented test.

## Constraints

- CON-001 — Real money enters in stages: first historical data, then live paper, and real money only with a cap set by the author and if the method passed its criteria.
- CON-002 — A single operator user. The public part is read-only.
- CON-003 — Hybrid visibility: the collection code, the scanner, the method evaluator and the studies are public. The parameters and strategies that show an edge stay private.
- CON-004 — Never invent data. If a reading is missing it is reported as a gap. An opportunity only counts if it was calculated with executable prices and real depth, not with the price the page shows.
- CON-005 — No real-money trading without first checking that the platform allows trading from the author's jurisdiction. For E1 the list of blocked countries of each platform is enough; no legal opinion is requested and the legal risk is assumed by the author (DEC-05, 2026-10-26).
- CON-006 — The criterion for discarding or approving a method is written before testing it and is not moved after seeing the result.
- CON-007 — Wallet keys or trading credentials never live in the public repository.

## Core Domain Language

| Term | Meaning |
|---|---|
| Market | A Polymarket question with options that resolve on a date. It can be a two-option market (Yes/No) or a multi-option market whose options are mutually exclusive. |
| Option | One of the possible outcomes of a market. When it resolves, the winning option pays $1 and the others $0. |
| Displayed price | The price the page shows (mid or last trade). It is not suitable for deciding on a trade. |
| Executable price | The best price at which one can actually buy (ask) or sell (bid) in the order book at that moment. |
| Depth | How much volume is available at each price. It limits the size of an opportunity. |
| Market sum | The sum of the executable prices of all the options of a multi-option market. |
| Within-market opportunity | A moment when the market sum allows buying or selling all the options with a guaranteed profit before costs. |
| Cross-market contradiction | Prices of related markets that cannot all be true at once according to their logic (for example, the part being worth more than the whole). |
| Net edge | Profit of an opportunity after fees, slippage and depth. |
| Tied-up capital | Money committed from the moment an opportunity is taken until the market resolves. It reduces the return per unit of time. |
| Resolution risk | The possibility that a market resolves ambiguously, is disputed or has an option that was not contemplated. |
| Calibration | How closely the probabilities implied in prices match the actual frequency with which they come true. |
| Method | A concrete way of finding or exploiting an edge, tested in isolation. |
| Verdict | The result of testing a method against its criterion: continue, discard or investigate further. |
| Paper trading | Simulating the trade with real prices of the moment, without money. |
| Perpetual future (perp) | A contract that tracks an asset's price and never expires. One can be long (bought) or short (sold), with leverage. |
| Funding | A payment that one side of the perpetual makes to the other every hour to keep its price pegged to the asset's real price. |
| Funding spread | One platform's funding rate minus the other's, for the same asset and the same hour. |
| Leg | Each of the positions that make up a combined trade. E1 has two: one on each platform. |
| Basis risk | The prices of the same asset on the two platforms drifting apart while the position is open. |
| Liquidation | Forced closing of a leg when its collateral (margin) is no longer enough. It leaves the other leg uncovered. |

## Approved Product Decisions

- ~~First focus: arbitrage within a single market and contradictions between Polymarket markets, plus calibration. Source of the decision: the author, 2026-10-25.~~ Replaced on 2026-10-26 by the following decision.
- Core: ETL plus evaluator, with E1 (funding between Polymarket Perps and Hyperliquid) as the first strategy. Scope is expanded to perpetual futures. Source: the author, 2026-10-26, «si mas bien seria eso ETl + evaluador con E1. Como primer decision». Evidence: `docs/discovery/findings.md`, section Angle E and DEC-01.
- Ladders are out for now. Source: the author, 2026-10-26, «Las escaleras se quedan fuera por ahora.» (DEC-02).
- C, D and E2 are out for now; they are reconsidered after E1's verdict. Source: the author, 2026-10-26 (DEC-04).
- No legal opinion is requested before real money; the platform's list of countries is enough (DEC-05, CON-005). Source: the author, 2026-10-26.
- Research first. E1 gets its first verdict after 4 weeks on paper with the project's own data. It advances to the next stage only if it yields ≥ 10% a year net on collateral, after fees, basis and slippage. Source: the author, 2026-10-26 (DEC-03).
- Hybrid visibility (CON-003). Source: the author, 2026-10-25.
- A single operator user (CON-002). Source: the author, 2026-10-25.
- Real money in stages with a cap (CON-001). Source: the author, 2026-10-25.
- Project name: Polyquack. Source: the author, 2026-10-25.

## Open Product Decisions

- Capital cap for the real-money stage. The author decides, after discovery and before that stage. It defines how much risk is acceptable.
- Thresholds for advancing stages in strategies other than E1 (E1's is decided in DEC-03). The author decides when each strategy comes in.
- Whether the system ends up placing orders on its own or stays with alerts and manual execution. The author decides before the real-money stage; it changes the security and latency requirements.
- Which studies and which parts of the code are published exactly. The author decides for each piece, following CON-003.

## Discovery

Depth: deep
Findings: `docs/discovery/findings.md`. Explanation for deciding: `docs/discovery/polyquack.html`.
Closed on Oct 26, 2026: every question has its decision in findings.md (the Decision section of each DQ, plus DEC-01 to DEC-05). With the focus on E1, DQ-003 and DQ-008 do not apply, and DQ-007 is replaced by basis and liquidation risk, which the MVP itself measures.

| ID | Evidence question | Unblocks |
|---|---|---|
| DQ-001 | Can Polymarket data be read and can one trade on Polymarket from Mexico? Under what conditions and with what restrictions? | Whether the real-money stage exists (CON-005) |
| DQ-002 | What data do Polymarket's APIs and public sources provide: markets, order books, trades, history? With what historical depth, frequency and usage limits? Is there order book history or must it be collected from now on? | Scope of the historical study (OUT-001) and collection design |
| DQ-003 | What exactly did the IMDEA paper measure (method, period, prices used, costs)? Do its figures survive with executable prices and depth? | Baseline and differentiation of the study (OUT-001) |
| DQ-004 | How do fees, conversion between options in multi-option markets and settlement work on Polymarket today? What does trading cost? | Net edge calculation |
| DQ-005 | How long do within-market opportunities last today and what latency is needed to take them from a normal connection in Mexico? | Whether the live scanner makes sense (OUT-002) and the stage thresholds |
| DQ-006 | How well can a model (embeddings, rules or LLM) find related markets and the logical relationship between them? With what precision, measured on a labeled set? | Viability of cross-market contradictions (OUT-003) |
| DQ-007 | How often are there disputed or ambiguous resolutions and how much did they cost someone holding an arbitrage? | Real risk of "riskless" strategies |
| DQ-008 | What Polymarket calibration studies already exist and what did they find? | What the calibration study contributes (OUT-004) |
| DQ-009 | What open or commercial tools already scan Polymarket arbitrage and what do they do well or badly? | Differentiation of the public piece (OUT-006) |
| DQ-010 | Which evaluation methods (walk-forward, deflated Sharpe, criterion preregistration) apply to arbitrage and calibration strategies, which are not classic price series? | Design of the method evaluator (OUT-005) |

## Artifact Applicability

| Artifact | Required? | Reason |
|---|---:|---|
| PRD | Yes | Product authority |
| Domain model | Yes | Shared vocabulary and invariants: funding spread, leg, basis risk, net edge, verdict |
| Structurizr DSL | Yes | Pieces that run differently: continuous two-platform ETL, evaluator, E1 paper trading and dashboard |
| ADR | Yes | Decisions with real alternatives: how and where data is stored, whether it runs on the author's computer or a small server, the boundary between public and private |
| DBML | Yes | Persistent data: instruments and their correspondence, hourly funding, book snapshots, mark prices, paper trades, verdicts |
| OpenAPI | No | There is no own API exposed to third parties in the MVP; the public dashboard is read-only |
| AsyncAPI | No | The platforms' streams are consumed, but no event contract of its own is published |
| Mermaid flows | Yes | Ingestion, pairing, paper trading and verdict flow |
| HTML prototype | No | The interface is secondary to the data and the evaluation |
| Quality attributes | Yes | Data integrity (CON-004), 24/7 ETL continuity, API usage limits, key security (CON-007), cost within 20 USD a month |
