# Polyquack Discovery Findings

Depth: deep

Research date: Oct 25, 2026. Sources were read with an automatic extractor that summarizes pages; numbers that go into an ADR are re-checked against the source.

## Comparison Criteria

| ID | Criterion | Must? | Agreed by |
|---|---|---:|---|
| CR-001 | Real net edge: profit is measured with executable prices, after fees and trapped capital | Yes | Author, Oct 25, 2026, «Advantage with real prices» (required) and «Real net advantage» (matters) |
| CR-002 | Runs from home: needs no servers next to the exchange and no millisecond latency | Yes | Author, Oct 25, 2026, «Runs from home» |
| CR-003 | Low cost: data, servers and APIs within 20 USD per month during discovery and MVP | No | Author, Oct 25, 2026, «Low cost», «Up to 20 USD» |

Notes from the criteria round:

- The author did not mark "Legal from Mexico" or "Within budget" as required. Legality remains a condition for trading with real money under CON-005 of the brief; for discovery and the MVP, which only read data, it does not rule out options. The 20 USD budget stays as a criterion that weighs, not as a filter.
- "Early first result" and "Portfolio value" were not marked.

## Audit (general)

- Time: 5 to 15 h per week. Source: author, Oct 25, 2026.
- Budget: up to 20 USD per month. Source: author, Oct 25, 2026.
- Own reusable pattern, not as a dependency: the watcher from Duma Emerson (periodic review of series, one incident per cause, a rule against inventing data), in `duma-sidon/references/Duma_Emerson/backend_files/core/alertas/`, with context in `duma-sidon/references/Duma_Emerson/CONTEXTO_SESION.md`.
- `Polyquack` is not yet a git repository.
- Platform change that makes everything earlier obsolete: Polymarket moved to CLOB V2 on Apr 28, 2026. The money used changed from USDC.e to pUSD and the V1 negRisk adapter was deprecated on Jul 14, 2026 [S-014]. Subgraphs stopped being used with the migration [S-031]. Code, guides and papers from 2025 describe a platform that no longer exists. **Confirmed.**

---

## DQ-001 — Can data be read and traded on Polymarket from Mexico?

Unblocks: whether the real-money stage exists (CON-005).
Kill or change criterion: if reading public data is not possible from Mexico, the project is rethought. If trading is not legal or not possible, the product is cut down to research and paper: the real-money stage disappears, but the studies continue.

### Audit
- The geographic restriction applies to placing orders, not to reading data [S-001]. **Confirmed.**
- Mexico does not appear in any block list, neither full nor "close positions only" [S-003, S-004]. **Confirmed** as of the reading date; the pages carry no date.
- There is an official query to find out whether a connection is blocked: `GET polymarket.com/api/geoblock` [S-004]. **Confirmed.**
- Identity verification: Polymarket launched a verification portal on May 27, 2026 and gives more speed to those who verify [S-005]. It is not clear whether it is mandatory. **Issue.**
- Legal stance in Mexico: there is no regulation or statement from SEGOB, CNBV or Banxico. The only analysis found is the opinion of a gambling lawyer: for him, they are bets under the Ley Federal de Juegos y Sorteos [S-008]. It is an opinion, not a regulation. **Issue.**
- Other countries did act: Argentina ordered Polymarket blocked, Spain blocked Polymarket and Kalshi, Brazil blocked prediction sites and Nevada sued Polymarket [S-009, S-010]. **Confirmed** as facts reported by the press.
- Polymarket US (the version regulated by the CFTC, the US derivatives commission) appears to be only for US residents [S-007]. **Hypothesis.**
- Kalshi from Mexico: the sources contradict each other [S-011, S-012]. **Issue.**
- Polymarket terms of use: the text could not be read. **Issue.**

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-001 | Read data from the international platform from Mexico; never trade until the legal question is resolved | Read-only public APIs | research | S-001, S-003 | Hypothesis: no real call was tested |
| OP-002 | Formal legal opinion before the real-money stage | Consult a gambling or fintech lawyer in Mexico | research | S-008 | Ask |
| OP-003 | Research and paper forever; the edge is demonstrated without trading | Remove the real-money stage | session | — | — |
| OP-004 | Trade on another platform with clear regulation, if any accepts residents of Mexico | Switch market | research | S-011, S-012 | Issue |

### Probes
| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-001 | Call to `polymarket.com/api/geoblock` and to the markets API from the author's connection, Oct 25, 2026 | Whether it responds and which country it reports | `blocked: false`, country MX. The markets API responded with data. **Confirmed** for reading. Trading is still unverified (CON-005) |

### Decision
Status: Decided
Decision: Reading data works from the author's connection and Polymarket Perps does not block Mexico. No legal opinion (DEC-05).
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-002 — What data do the public sources provide and is there order book history?

Unblocks: scope of the historical study (OUT-001) and design of the collection.
Kill or change criterion: if no order book history exists, the historical study with executable prices only covers the period since own collection begins.

### Audit
- **Polymarket does not offer order book history.** The documentation has no endpoint for it; the book is queried only at the moment [S-016]. **Strong hypothesis:** it is deduced from the endpoint not existing, not from a sentence that says so. Gebele et al. confirm it indirectly: "historical level-2 order-book data are unavailable for the transaction sample" [S-034].
- The live channel (WebSocket) sends the full book, every price change, trades and tick changes [S-017]. **Confirmed.** How many markets fit per connection: not found.
- Price history: the documentation guarantees *at least* 7 days per minute, 60 days every 5 minutes, 90 days every 30 minutes, and every 3 h or 12 h forever [S-016]. These are minimums, not exact limits. It is "observed price"; the documentation does not say whether it is the mid price or the last trade price. These are prices, not books. **Confirmed.**
- On the blockchain only executed trades remain, not the orders waiting in the book [S-021]. That is why the IMDEA paper could not measure depth. **Confirmed.**
- Rate limits per 10 s: book 1,500; batched books 500; price history 1,000; market metadata 300 [S-015]. **Confirmed.**
- Open datasets:
  - Becker, *prediction-market-analysis*: 36 GiB of trades and metadata from Polymarket and Kalshi, without books. Code under MIT license; the data declare no license [S-030]. **Confirmed.**
  - Zenodo, books of 805 crypto markets of 5 min to 4 h, from Aug 21 to 24, 2026, at 1 s, CC BY 4.0 license [S-024]. Crypto only and only 3 days. **Confirmed.**
- Order book history vendors (everything they say is **Hypothesis** until tested):

| Vendor | Since | Price |
|---|---|---|
| CryptoStruct | Jul 2025 | 1 EUR per market-day [S-029] |
| Marketlens | Mar 2026 | free for 7 days; from 39 USD per month, above the budget [S-026] |
| pmdata.dev | Feb 2026 | free plan, prices not seen [S-025] |
| polymarketdata.co | no clear date | not seen [S-028] |

- Before Jul 2025 nobody offers books. **Hypothesis:** nobody recorded them.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-005 | Record own books from now on through the live channel | Own forward collection | research | S-017 | Confirmed that the channel exists |
| OP-006 | Buy history from a vendor for specific markets and days | Selective purchase | research | S-029 | Hypothesis |
| OP-007 | Reconstruct from on-chain trades or from the Becker dataset, like IMDEA | Executed trades, no depth | research | S-021, S-030 | Confirmed; fails CR-001 for measuring edge |
| OP-008 | Price history of 3 h or 12 h plus outcomes, for calibration only | Price at a fixed horizon | research | S-016 | Confirmed that it exists. **Does not serve CR-001:** these are not executable prices. It only serves to measure information, not net edge |
| OP-009 | Zenodo dataset to test the scanner code before recording | Open sample | research | S-024 | Confirmed |

### Decision
Status: Decided
Decision: The ETL records books and funding from Polymarket Perps and from Hyperliquid from day 1: there is no perps order book history.
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: ADR input (how and where it is recorded)

## DQ-003 — What did the IMDEA paper measure and do its figures survive with executable prices?

Unblocks: baseline and differentiation of the study (OUT-001).
Kill or change criterion: if a measurement with executable prices, depth and costs already exists, the historical study stops being a contribution and is refocused.

### Audit
- **IMDEA** (Saguillo et al., arXiv 2508.03474) [S-021]. Everything **Confirmed** in the text, except where marked.
  - Data: resolved markets from Apr 1, 2024 to Apr 1, 2025, from on-chain trades.
  - Price used: the volume-weighted average of the trades in each block. It does not use the book or depth.
  - It does not count fees, because in that period Polymarket did not charge them. Today it does (see DQ-004).
  - It does not model slippage or trapped capital.
  - Headline figure: 39.6 M USD. It is the **profit estimated that accounts actually extracted** with all strategies, assuming 1 USD per trade: "The combined amount extracted from all strategies presented totals $39,587,585.02" [S-021]. It is not a theoretical ceiling.
  - It does not measure how long an opportunity lasts.
- **Gebele, Mutzel and Matthes, "Executable Arbitrage and Market Efficiency in Prediction Markets"** (arXiv 2608.00666, Aug 1, 2026) [S-034]. Full text read in HTML on Oct 25, 2026. Everything **Confirmed** in the text.
  - Three non-overlapping datasets:
    - the old Polymarket regime (FPMM): 51 option groups and 235 markets;
    - trades of 32,702 events listed through Dec 31, 2025;
    - an hourly sample of **full order books from Apr 14 to May 19, 2026**, replayed update by update.
  - It measures violations **with depth and fees**, assuming all legs pay the taker fee. That overstates the cost when one can be a maker.
  - Profit that participants extracted: 1.118 M USD, only in multi-option markets. 1.086 M come from the converter route and 32 thousand from forming complete baskets and waiting for settlement.
  - **Duration** in the 2026 book sample:
    - Of 624 episodes, 366 (58.7%) lasted more than 50 minutes. They fill the whole observed window and their exact duration is not known.
    - Of those seen opening and closing, the median was **16.15 s** on the Yes side (253 episodes) and **7.99 s** on the No side (5 episodes).
    - The Yes side cannot be converted before settlement: it is only exploited by buying the basket and waiting.
- **The figures of the two papers cannot be compared** as "with real prices, 35 times less remains". They measure different periods, markets and methods. The earlier version of this document compared them: that was an error.
- **The change criterion was triggered:** a measurement with real books, depth and fees already exists, and it includes duration. What was not found published:
  - how many violations there are after May 19, 2026, with the July sports fees;
  - whether an opportunity can be taken from a home connection;
  - the contradictions between threshold and date markets (ladders), which are not multi-option.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-010 | Reproduce Gebele with own 2026 data (V2, with fees) | Forward replication | session | S-034 | Hypothesis |
| OP-011 | Measure the life of each opportunity: how long it lasts and how much volume it has each second | Survival analysis on recorded books | session | S-034 already did it for Apr and May 2026 in multi-option markets; the contribution would be extending it over time and to ladders | Hypothesis |
| OP-012 | Drop the historical study and center the contribution on contradictions between markets | Change of focus | session | S-021 | — |
| OP-013 | Buy specific days of history to compare 2025 against 2026 | Selective purchase | research | S-029 | Hypothesis |

### Decision
Status: Decided
Decision: Not applicable: arbitrage in prediction markets was left out of scope (DEC-01, DEC-02).
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-004 — How do fees, option conversion and settlement work today?

Unblocks: calculation of net edge (CR-001).
Kill or change criterion: if the costs of buying and collecting a complete game exceed the typical margin, arbitrage within the market is ruled out as a profit method and remains as a study.

### Audit
- **Only the one who takes liquidity pays** (the taker); the one who leaves an order waiting in the book (the maker) pays 0 and receives a rebate [S-013]. **Confirmed.**
- Formula: fee = shares × rate × p × (1 − p). It weighs more near p = 0.50 [S-013]. **Confirmed.**
- Rates by category [S-013]:

| Category | Rate |
|---|---|
| Crypto | 0.07 |
| Sports | 0.05 (was 0.03 until Jul 10, 2026) |
| Finance, Politics, Technology, Mentions | 0.04 |
| Economy, Culture, Weather, Other | 0.05 |
| Geopolitics | 0 |

- Rates changed six times between Jan and Jul 2026 [S-014]. The source of truth is the fee schedule of each market, not a fixed table. **Confirmed.**
- Worked example: 100 shares at 0.50 in Politics cost 100 × 0.04 × 0.50 × 0.50 = 1.00 USD in fees.
- Splitting 1 pUSD into Yes + No, merging them back or collecting a winner pays no documented fee. With the Polymarket relayer it also pays no gas [S-018, S-019]. **Confirmed.**
- In a negRisk market (several mutually exclusive options), 1 No of one option converts into 1 Yes of each of the others [S-020]. Whether the conversion charges anything: not found. **Issue.**
- The tick and the minimum order size change per market and live [S-022]. **Confirmed.**
- The step from resolution to payout takes about 2 h if nobody disputes [S-023]. **Confirmed.**
- Cost of buying all options of a negRisk market: the sum of the ask prices plus the fee of each leg. There is an edge if that comes to less than 1.00. **Hypothesis** derived from the documentation; it still needs to be tested with real books.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-014 | Take all legs at the book price | Taker on all legs | research | S-013 | Confirmed cost |
| OP-015 | Leave orders waiting and pay no fee | Maker on all legs; risks that not all fill | research | S-013 | Hypothesis about the risk |
| OP-016 | Mixed: maker on the slow legs, taker on the last | Maker and taker combined | session | — | Hypothesis |
| OP-017 | No-to-Yes conversion route in negRisk | Converter | research | S-020, S-034 | Confirmed mechanism; cost not found |
| OP-018 | Start with Geopolitics, which pays no fee | Category filter | session | S-013 | Confirmed rate 0 |
| OP-044 | Sell side: split 1 pUSD into all options and sell them when the sum of the bid prices exceeds 1 | Create basket and sell | challenge | S-019, S-020 | Hypothesis |

### Probes
| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-014, OP-018 | Pending: `docs/discovery/spikes/DQ-004-net-edge/` | Net edge of each complete game with real books and fee by category | Pending |

### Decision
Status: Decided
Decision: The evaluator calculates as taker on both legs (Polymarket 0.04%, Hyperliquid 0.045%); trading as maker is an improvement to test later.
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-005 — How long do opportunities last and what latency is needed?

Unblocks: whether the live scanner makes sense (OUT-002) and the stage thresholds.
Kill or change criterion: if opportunities last less than an order takes from a home connection in Mexico, the scanner fails CR-002 and is ruled out for trading; it remains as a measurement.

### Audit
- **Gebele et al. did measure duration** [S-034], with full order books from Apr 14 to May 19, 2026, in multi-option markets and with fees. **Confirmed** in the text.
  - The median was 16 s on the Yes side and 8 s on the No side, although on the No side there were only 5 episodes.
  - 58.7% of the episodes lasted more than 50 minutes.
  - The authors warn that the closing of an episode does not prove anyone exploited it.
  - The earlier version of this document said nobody had measured it: that was an error.
- The blog figures ("12.3 s to 2.7 s", "73% for bots under 100 ms") could not be traced to any paper. **Issue.**
- **Reading (Hypothesis):** there are two populations.
  - The short violations, of seconds, are out of reach of a home connection.
  - The long ones, of more than 50 minutes, are within its reach. But, on the Yes side, they are only collected by waiting for settlement, with the capital trapped.
- The Polymarket engine is in AWS eu-west-2 (London) [S-036]. **Partially confirmed:** seen in the Chinese version of the documentation and in search results, not in the English version.
- Polymarket offers co-location in London with identity verification [S-004]. That is exactly what CR-002 excludes. **Confirmed.**
- Published latency of the engine or of the bots: not found.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-019 | Scanner at home with the live channel | WebSocket from Mexico | research | S-017 | Hypothesis about latency |
| OP-020 | Scanner on a small server in Dublin or London | VPS near the engine, within 20 USD | research | S-036 | **Fails CR-002** (required): it is a server next to the engine, just like co-location. Ruled out |
| OP-021 | Query every N seconds | Periodic probe, like PolyArb every 60 s | research | S-033 | Confirmed that it does not see short opportunities |
| OP-022 | Only measure, without trying to trade | Passive measurement | session | — | — |
| OP-023 | Look for opportunities that last hours: slow to correct because they require understanding the market | Edge through understanding, not speed | session | S-021 (contradictions between markets are paid for by reasoning); S-034 (58.7% of the episodes last more than 50 min) | Hypothesis |
| OP-045 | Estimate the life of opportunities now, with others' books: the Zenodo dataset (at 1 s) or a vendor's free trial | Existing data instead of recording and waiting | challenge | S-024, S-026 | Hypothesis; Zenodo only covers short-term crypto |

### Probes
| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-019, OP-022 | Pending: `docs/discovery/spikes/DQ-005-opportunity-lifetime/` | Duration of each opportunity in negRisk markets and round-trip time from home | Pending |

### Decision
Status: Decided
Decision: Closed: funding is collected hourly and speed does not matter; it runs from home. Where it runs 24/7 is decided by the design.
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: ADR input

## DQ-006 — How well does a model find related markets and their logical relationship?

Unblocks: viability of contradictions between markets (OUT-003).
Kill or change criterion: if precision is so low that manual review does not fit in 5 to 15 h per week, the method is cut down to hand-curated pairs.

### Audit
- **IMDEA method** [S-021], everything **Confirmed** except the final precision:
  - Text embeddings to group markets by topic: 92% accuracy on 100 reviewed samples.
  - A language model enumerates the possible combinations of outcomes.
  - Of 46,360 pairs from the US elections, the model flagged 1,576 as dependent.
  - Of those, an automatic reviewer let 374 through, which were reviewed by hand. Only 13 met the definition of **combinatorial arbitrage**: "11 NegRisk-NegRisk and 2 NegRisk-Single pairs, which satisfy our Combinatorial Arbitrage definition" [S-021].
  - That does not measure how well it detects dependencies, but how many pairs yield an opportunity. The paper itself is inconsistent: it reports 11 confirmed pairs between multi-option markets, when there were only 4 of that type among the 374. **Issue.**
  - An earlier version of this document called 13 / 374 = 3.5% "precision". That reading does not hold.
- Other work does not resolve this:
  - Kim et al. look for markets that move one after another, without logical dependency [S-037].
  - Paleka et al. measure whether language model forecasts are logically consistent; they do not detect market pairs [S-038].
- Methods of logical inference between texts applied to market questions: not found.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-024 | Embeddings plus language model that enumerates combinations, like IMDEA, with a current model | Free reasoning over the text | research | S-021 | Issue: there is no comparable precision figure in the paper |
| OP-025 | Template ladders: the same event with different dates ("before June", "before December") or different thresholds ("BTC > 100k", "BTC > 110k") | Ordering rules: a later date or a lower threshold can never be worth less | session | — | Hypothesis |
| OP-026 | Within the same negRisk event, where exclusion is already guaranteed | Platform structure | research | S-020 | Confirmed |
| OP-027 | Hand-curated pairs with the model's help as a filter | Human decides | session | — | — |
| OP-028 | Logical inference model between texts (entails, contradicts, neutral) | Pair classifier | adjacent field | — | Hypothesis |
| OP-046 | Ladders between events of the same asset ("BTC above X on day D" against "BTC touches X in October") | Ordering rule between different events | challenge | — | Hypothesis |

### Probes
| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-025 | `docs/discovery/spikes/DQ-006-ladders/` (`download.py`, `ladders.py`, `result.json`). Snapshot of the 21,823 active events on Oct 26, 2026 at 03:08 UTC, with the best bid and ask of each market. Depth read from the book for the 40 worst violations | Precision of the rule; how many violations remain after fees; how much volume they have | See "Probe B result" below |
| OP-024, OP-028 | Not tested | — | Remain as a pending comparison; the IMDEA figure (3.5%) is the only reference |

#### Probe B result

- **The rule needed four versions**, and each failure taught something:
  - **v1:** treated "hit" as "rise". Stock events mix "hit (LOW)" (fall to) with "hit (HIGH)" (rise to), and all their apparent violations were false.
  - **v2:** separated LOW and HIGH, but "hit 20%" in Trump's approval means *fall*. That direction depends on the current value, which the rule does not know.
  - **v3:** only accepts an explicit direction ("or higher", "above", "(HIGH)") and excludes a bare "hit". The year failed: the event closes before some of its markets.
  - **v4:** takes the year from the closing date of each market.
- **Universe size (v4):**
  - 1,003 ladders: 423 by date, 454 by upward threshold and 126 by downward threshold.
  - 13,776 pairs, from 21,823 active events; 8,847 of those events are negRisk and do not enter.
- **Precision of v4:** in a random sample of 60 pairs, all 60 are logically valid implications: the Yes of the harder one implies the Yes of the easier one. The 40 net violations are too.
  - **Hypothesis:** it was labeled by the assistant reading the questions, not by the author, and the full resolution rules of each market were not reviewed.
  - With 0 errors in 60, the 95% lower bound of the precision is around 95%.
  - It measures whether the implication is valid. It does not measure how many real ladders it leaves out (coverage).
  - There is no comparable IMDEA figure (see Audit). The rule gains precision at the cost of coverage: it only sees ladders within an event and discards a "hit" without explicit direction.
- **Violations:**
  - With the best bid and ask, 54 pairs cost less than 1. With the taker fee of each market, 40 remain.
  - **The 6 best were phantom prices.** They are exactly the 6 whose book answered 404, such as "Cambria launches token before Sep 2027 / before Jun 2027". They have filler prices, like bid 0.09 and ask 0.94, over empty books. They are not executable. The earlier version of this document presented them as the best opportunity.
  - With a real book, the net edge ranges from almost 0 to **2.6% of the 1 USD payout**: net cost 0.974, in "unemployment ≥ 6% / ≥ 7%".
  - One of the 34 with a book (Glean, 0.36 shares) is below the minimum order size, which is 5 shares. It is not executable either.
- **Executable volume:** across the 33 violations with book and volume, the total profit walking both books was **17.61 USD** on 5,254 shares.
  - It is a ceiling: several pairs share the same leg and the calculation repeats its volume.
  - Example: "US unemployment ≥ 6% in 2026 / ≥ 7%": 433 shares, 4.54 USD of profit, with the money trapped until the market closes, on Feb 1, 2027 (about 3.2 months). 2.6% in 3.2 months equals about 10% per year (2.6 × 12 / 3.2 = 9.75).
- **Reading:**
  - The ladder rule is precise and cheap: a download of about 12 min, free.
  - In a single snapshot, the exploitable edge is tens of dollars. **Issue:** a snapshot does not say how often they appear or how long they last. For that, one has to record over time (OP-011).
- **Technical notes of the probe:**
  - The Gamma listing with *offset* cuts off at 2,500 events; `/events/keyset` must be used.
  - The Data API responds 403 if the request carries no User-Agent.
  - The full download with all fields weighs 1.8 GB; with the probe's fields, 250 MB.

### Decision
Status: Decided
Decision: For E1, relating instruments means pairing the same asset on the two platforms, by direct rule, without ML.
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-007 — How frequent are disputed or ambiguous resolutions and what did they cost?

Unblocks: real risk of the "risk-free" strategies.
Kill or change criterion: if disputes are frequent in the market types where arbitrage appears, that type is excluded or assigned a risk cost.

### Audit
- How it is resolved [S-023, S-039], everything **Confirmed**:
  - Anyone proposes an outcome by posting a bond of about 750 pUSD.
  - If nobody disputes it within 2 h, it is resolved.
  - If there are two disputes, UMA token holders decide by vote, and everything takes 4 to 6 days.
  - A "50/50" outcome pays 0.50 per share.
  - Crypto up-or-down markets are resolved with an automatic Chainlink price, with no vote.
- Cases documented by the press, with figures not verified on-chain:
  - Ukraine and minerals, Mar 2025, about 7 M USD [S-040].
  - Zelenskyy's suit, Jul 2025, more than 237 M USD in volume [S-041].
  - The Strategy bitcoin sale, Jun 2026 [S-042].
- Frequency: the press figures use different definitions and cannot be compared. They range from "0.2% of the bets" to "more than 1,150 disputed markets in 2026" [S-043]. **Issue.**
- The WSJ analysis cited by several outlets: in most disputes, more than half of the vote comes from the 10 largest wallets [S-043]. **Hypothesis:** it is a secondary source.
- An Apr 2026 preprint says that language models do not predict which markets will be disputed [S-044]. **Hypothesis:** it is not peer reviewed.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-029 | Subtract a risk cost by category from the edge | Edge discount based on history | session | S-043 | Hypothesis; a reliable frequency figure is missing |
| OP-030 | Exclude markets with subjective rules; use only those with automatic resolution or an objective source | Filter | session | S-023 | Confirmed that automatic resolution exists |
| OP-031 | Measure own frequency from on-chain resolution events | Own data | session | S-031 | Hypothesis |

### Decision
Status: Decided
Decision: For perps it is replaced by basis and liquidation risk; the MVP itself measures them during its 4 weeks on paper (DEC-03).
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-008 — What Polymarket calibration studies already exist?

Unblocks: what the calibration study contributes (OUT-004).
Kill or change criterion: if a recent and complete study already exists, the own study is reduced to reproducing it with 2026 data or is omitted.

### Audit
- **Le, arXiv 2602.19520** [S-045]. Uses trades through Dec 31, 2025, with no apparent peer review. **Confirmed** in the text.
  - In politics, prices fall short: favorites are worth less than they should be and longshots (low-probability options) more.
  - The bias grows with the horizon: a contract at 70 cents one month out is equivalent to about 75% real probability.
  - It uses no scoring rules (such as the Brier score) and no fees.
- **Song** [S-046], informal analysis of 2,975 markets.
  - It does not find the classic bias.
  - Correcting calibration out of sample improved nothing: the Brier score went from 0.0423 to 0.0432.
- **Qin and Yang** [S-047] relate calibration to liquidity and to the type of order flow.
- **Mok et al.** [S-048]: calibration improves with volume. Seen only in a search snippet.
- Bürgi, Deng and Whelan, on Kalshi [S-049]: whoever takes liquidity loses on average. Seen only in search snippets.
- There are live calibration trackers, such as simplefunctions.dev [S-050].
- **No study shows the net edge**, that is, after fees, *spread* and trapped capital. **Hypothesis** about what was found.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-032 | Reproduce Le with 2026 data and measure with scoring rules | Replication | session | S-045 | Hypothesis |
| OP-033 | Take the calibration bias to net edge: fees, *spread*, trapped capital | Strategy evaluated with CR-001 | session | S-045, S-013 | Hypothesis; it is what nobody shows |
| OP-034 | Omit calibration | Cut | session | S-046, S-050 | — |

### Decision
Status: Decided
Decision: Not applicable: calibration was left out of scope (DEC-01).
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-009 — What tools already scan for arbitrage on Polymarket?

Unblocks: differentiation of the public piece (OUT-006).
Kill or change criterion: if an open tool already measures with executable prices, depth and costs, Polyquack reuses it or differentiates itself on another point.

### Audit
What each tool says is **Hypothesis** until its code is read.

| Tool | What it does | Depth and fees | Status |
|---|---|---|---|
| ebag73/polymarket-arb-scanner, on Apify [S-051] | Arbitrage within Polymarket, including negRisk | Does walk the book and applies fee by category | Paid black box, 2 users. Closest to Polyquack |
| arnavnayak42/PolyArb [S-052] | Differences between Polymarket and Kalshi | Walks the books; assumes a 5% fee when the rate is missing, which may be incorrect | One commit, Sep 27, 2026, no license: its code cannot be reused. Polls every 60 s |
| Synpath-ai [S-053] | Between platforms, paper only | Only the best price, without the rest of the book | MIT, active, Oct 2026 |
| ImMike/polymarket-arbitrage [S-054] | Several types | Depth not specified; configures 0 fee | Abandoned since Dec 2025, 301 stars, conflicting license |

**Hypothesis:** there are several low-quality clones with "bot" in their names.

No open tool measures how long an opportunity lasts or the net edge with trapped capital. **Hypothesis.**

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-035 | Build the own open scanner | Own development | session | — | — |
| OP-036 | Use Synpath (MIT) as a base and add depth and negRisk | Reuse | research | S-053 | Hypothesis |
| OP-037 | Use the Apify scanner as an external reference to compare results | Comparison | research | S-051 | Hypothesis |

### Decision
Status: Decided
Decision: No tool was found that covers Polymarket Perps; the funding strategy is in fact known. The own ETL and evaluator are built.
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

## DQ-010 — What evaluation methods apply to arbitrage and calibration?

Unblocks: design of the method evaluator (OUT-005).
Kill or change criterion: none cancels the product; it defines metrics and preregistration.

### Audit
- **For probability forecasts**, the rules that reward stating the true probability are the Brier score and the log score [S-055]. They are compared against the market price at a fixed horizon, which plays the role of the closing line in betting. **Confirmed** as a reference; the paper's content was not read.
- **Purged and embargoed cross-validation, and its combinatorial version (CPCV)**, for data that overlap in time [S-056]. It applies here because several markets depend on the same event. That is why grouping is by event: Song estimates about 770 independent events in 2,975 markets [S-046]. **Confirmed** the method; only the book's index was seen.
- **Deflated Sharpe**, which corrects for how many variants were tested [S-057]. **Confirmed.**
- **Probability of backtest overfitting (PBO)** [S-058]. **Confirmed.**
- **For arbitrage with trapped capital:** report the return on trapped capital, annualized by the days until resolution. Page and Clemen show that the cost of waiting matters [S-059]. **Hypothesis:** it is a recommendation, with no direct source.
- **Preregistration of the criterion:** no primary source found. It is kept because of CON-006.

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-038 | One evaluator per family: arbitrage (annualized return on trapped capital) and forecasting (Brier against the market) | Separate metrics | research | S-055, S-059 | Hypothesis |
| OP-039 | Everything converted to simulated paper money and compared against doing nothing | A single metric | session | — | — |
| OP-040 | Preregistration in a versioned file before each test, with the attempt count for the deflated Sharpe | Process discipline | session | S-057 | — |

### Decision
Status: Decided
Decision: Metric: annual net profit on collateral, walk-forward, and criterion written before each test (DEC-03, CON-006).
Decided by: the author, Oct 26, 2026, «I approve closing the 10 questions. Move the brief to Ready for PRD.»
Route: brief decision

---

## Advantage Angles (ideation with the author)

On Oct 25, 2026 the author asked, «before choosing, look at 2 other angles». Besides A (speed: life of opportunities, OP-011) and B (understanding: template ladders, OP-025), these were added. Both change the mechanism: the edge comes from a **model with better information than the market**, not from prices contradicting each other.

| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-041 | **C. Weather:** forecast a city's maximum temperature better than the market. Public numerical forecasts (ECMWF, GFS) are corrected with ML trained against the station the market resolves with | Information edge: physical forecast plus statistical correction | session | S-060: the markets resolve with an airport station on Weather Underground, in whole degrees. S-061: there are promotional bot guides, no study | Hypothesis. The rules were seen on mirror pages, not on Polymarket |
| OP-042 | **D. Crypto options as fair price:** compute the probability of "BTC above X on date Y" from the options market (Deribit) and compare it against Polymarket | Fair value from a more liquid derivatives market | research | S-062: simple "above" bets follow the options; "touch" or "fall to" bets deviate, especially at the open, near expiry and on weekends | Confirmed as a finding of the paper (abstract only). It is already studied: the contribution would be the executable net edge |
| OP-043 | **Alternative (did not advance to a probe): market making.** Leave orders on both sides in slow markets and collect the *spread* plus the maker rebate | Provide liquidity | research | S-013: the maker pays 0 and receives a rebate. S-049: on Kalshi the maker loses less than the taker (snippets only) | Hypothesis. Risk: you only get filled when you are wrong |

Selection for probing: the assistant recommended B + C; the author answered «sounds good to me» (Oct 25, 2026). It is a decision about what to probe, not the product decision: that one is made in step 8.

- **Why not D (crypto options):** it also passes CR-002 and CR-003. Free data, runs from home. It was left out for novelty: a paper already studies it [S-062]. That is not one of the agreed criteria, so D remains a valid option that was not probed.
- **Scope expansion:** C and D look for an information edge, not arbitrage. The focus approved in the brief is arbitrage within the market, contradictions between markets and calibration. If C or D continue, the author has to approve it as an expansion of the brief. **Ask.**

### Probes

| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-041 | `docs/discovery/spikes/DQ-C-weather/probe.py`. Already-resolved maximum temperature markets for New York (60 days evaluated) and London (61), Aug to Oct 2026. Price of each range at 16:00 UTC of the previous day, from the 3 h history (mid price, not executable). Model: ECMWF forecast from one day earlier (Open-Meteo, previous runs) plus bias and dispersion learned only from earlier days (walk-forward, 14-day warm-up) | Brier and log score of the model against the market; 80% market and 20% model blend | See below |

#### Probe C result

| City | Model Brier | Market Brier | 80/20 blend Brier | Days the model wins |
|---|---|---|---|---|
| New York | 0.755 | 0.586 | 0.601 | 16 of 60 |
| London | 0.754 | 0.637 | 0.645 | 18 of 61 |

- A lower Brier is better. **The market beats the simple model in both cities.** **Confirmed** for this model and this period.
  - Mean absolute error of the center of the market's bet against the real maximum: 1.15 °F in New York (74 days) and 0.66 °C in London (75). That of the uncorrected ECMWF forecast: 1.90 °F and 1.14 °C.
  - The market's advantage is not due to the bell shape assumed for the model's error.
- **No extra information was detected in the forecast.** **Hypothesis**, not Confirmed.
  - The blend makes the market worse in New York (+0.015, standard error 0.006). In London too, but without significance (+0.009, standard error 0.006).
  - With 60 days, the test does not rule out that the forecast contributes something small. The independent reviewer calculated this with the same data.
- **This probe does not measure CR-001.** It uses prices from the 3 h history, not executable. It measures whether there is information, not whether there is net edge.
- **Timing offset.** It reveals things, but does not change the conclusion.
  - Open-Meteo's "one day earlier" forecast is hourly. For the hours of the temperature peak, it came from runs published *after* the market snapshot.
  - The model saw a bit of the future and still lost. That reinforces that the market wins.
  - The 16:00 UTC snapshot reads the 15:00 UTC price, because the history comes in 3 h blocks.
- **The resolution rule changed within the period.** 13 New York events resolved with Weather Underground, 61 with the NOAA series and 1 with METAR (the hourly airport reports). The bias the model learned at the beginning came from a different source.
  - Today the rule is the maximum of the hourly METAR reports, in tenths of °C.
- **It does not rule out all of C**, only the naive version. Not tested:
  - the ensemble forecast;
  - several models combined;
  - high-resolution models;
  - same-day observations;
  - ML trained with years of data.
  What it does show: the market already incorporates the public forecast. An edge would have to come from something the market does not use.
- The sum of the mid prices of all ranges averaged 1.022 in New York and 1.027 in London. It is the normal margin of a book, not an opportunity.
- The 0 fee appears only in weather events from Oct 19 and 20, 2026 onward: 44 of 825 markets in New York and 55 of 825 in London. Before, the Weather category charged 0.05 [S-013]. It looks like a recent change, not an isolated case. The real fee is read from each market. **Hypothesis** about the change; **Confirmed** that those markets carry rate 0.
- Since Oct 2026, New York markets resolve with NOAA data at the LaGuardia station, not with Weather Underground. S-060 described older markets. **Confirmed** in the stored descriptions.

## Angle E: Polymarket Perps (added Oct 26, 2026)

The author asked «should we consider it as an option E?» and approved with «yes, start with it», on Oct 26, 2026. Like C and D, E is outside the focus approved in the brief: these are no longer prediction markets. If it continues, it is an expansion that the author must approve. **Ask.**

### Audit
- Polymarket launched Perps on Sep 3, 2026 [S-063]: perpetual futures on crypto, indices, commodities and stocks. It currently has 89 instruments, which were read from its public API. **Confirmed.**
- **Funding.** It is calculated and collected every hour.
  - Every 5 s the "impact price" is taken: the weighted average of filling 1,000 USD on each side of the book.
  - If a side does not reach those 1,000 USD, the index is used and that contribution is left at zero. Then the rate falls to the fixed interest of 0.0000125 per hour, about 11% per year.
  - Cap: 4% per hour.
  - It is a direct transfer between longs and shorts; the platform keeps nothing [S-064]. **Confirmed.**
- **Fees** by 30-day volume. Initial tier: taker 0.04% and maker 0.0125% of the notional. Some beta accounts temporarily have the lowest tier [S-065]. **Confirmed.**
- **Access.** Orders are not allowed from the US, Canada, Cuba, Iran, North Korea, Syria, Crimea, Donetsk and Luhansk. **Mexico is not on the list** [S-066]. **Confirmed** for the platform. The Mexican legal framework for leveraged derivatives was not reviewed. **Issue.**
- **Public data without authentication:** instruments, tickers, book, candles, mark price history and funding history, the latter paginated backward 100 at a time [S-067]. **Confirmed.**
- **Hyperliquid** also charges funding every hour, and its history is public [S-068]. Its initial fee is taker 0.045% and maker 0.015% [S-069]. **Confirmed.**

### Options
| ID | Option | Mechanism | Origin | Evidence | Label |
|---|---|---|---|---|---|
| OP-047 | **E1. Funding across platforms:** long on the platform where the rate pays and short on the other. The asset price cancels out and the rate difference is collected every hour | Funding arbitrage, price neutral | user + session | S-064, S-068 | See the probe |
| OP-048 | **E2. Perps against prediction markets on the same platform:** compare or hedge "BTC above X on day D?" with the BTC perp | Fair value and hedge within Polymarket | session | — | Hypothesis; not probed |
| OP-049 | Directional leveraged trading | Predict the price | user | — | Ruled out as an angle: it takes advantage of no finding and leverage worsens the risk |

### Probes
| Option | Setup | Measured | Result against the criterion |
|---|---|---|---|
| OP-047 | `docs/discovery/spikes/DQ-E-funding/` (`probe.py`, `out_of_sample.py`, `result.json`, `out_of_sample.json`, `depth.json`). Hour-by-hour funding from Sep 3 to Oct 26, 2026, on the 38 cryptos that are on both platforms: 1,272 h on 22 of them and about 1,087 h on those listed later | Rate difference; net profit of a daily walk-forward strategy with taker fee; out-of-sample test; depth and price difference in a snapshot | See below |

#### Probe E1 result

- **The difference is systematic.** In 36 of 38 coins, Polymarket's average funding was **lower** than Hyperliquid's. The mean difference is −12.5% per year. **Confirmed** for the period.
  - In ARB, ETHFI, KAITO and MORPHO, Polymarket's rate was negative, from −20% to −24% per year: there the shorts pay the longs. On Hyperliquid, those same coins paid +10% to +14%.
  - Polymarket was at the base rate 60% of the hours and Hyperliquid 74%. The 1,000 USD rule pushes Polymarket toward the base when one side of the book is thin.
- **Simulated strategy.** Each day the difference of the previous 24 h was checked. If it exceeded 0.00001 per hour (8.8% per year), the position that collects was held for 24 h. Taker fee was paid on both legs on opening and closing: 0.17% per round trip.
  - Across the 38 coins, the average net profit was **+2.6% per year** on the notional of each leg. It was positive in 17 of 38.
  - With the other thresholds (0, 0.000005 and 0.00002 per hour) the average ranges from +1.0% to +3.1%.
  - Note: the threshold was chosen with the same data.
- **Out of sample.**
  - The 10 coins with the largest difference in the first half (Sep 3 to 29) were chosen.
  - In the second half (Sep 29 to Oct 26), their average net profit was **+8.7% per year**, against +4.3% for all coins.
  - The dispersion is huge, from −9.9% to +34.3%. Three exceeded +30% (ETHFI, ARB and KAITO) and three were negative.
  - **Hypothesis:** the signal seems to persist from one month to the next, but with 2 months of history it is not conclusive.
- **Depth and basis.** Snapshot of Oct 26.
  - The Polymarket perp quoted between 0.03% and 0.12% below Hyperliquid's, in the same direction as the negative funding.
  - At 0.2% from the mid price, depth ranges from about 40 thousand USD (MORPHO) to more than 3 M (BTC) of bids on Polymarket, and from 5 thousand (ETHFI) to 15 M (ETH) of asks on Hyperliquid.
  - For personal sizes of thousands of USD it is enough. The thin side is usually Hyperliquid on small altcoins.
- **What the probe does not measure:**
  - **Basis risk:** that the two prices separate while the position is open.
  - **Slippage** beyond the best price.
  - **Liquidations.** Each leg needs its own margin. The return on capital is approximately the return on notional × leverage / 2; with more leverage, more risk that a leg gets liquidated.
  - **The platform maturing.** It is two months old. If more participants arrive, the difference may close. The beta fees may also change.
- **Against the criteria.**
  - CR-002: passes. It is collected hourly, not per second.
  - CR-003: passes. The data are free.
  - CR-001: it is **the first angle with positive net profit out of sample**, although with a short period, large dispersion and unmodeled risks. **Promising hypothesis**, not Confirmed.

## Decisions

### DEC-01 — Core and first strategy
Status: Decided
Decision: the core of Polyquack is an **ETL** and an **evaluator**, with **E1 (funding across platforms)** as the first strategy.
- The ETL downloads the data, relates them (which instrument corresponds to which asset on each platform) and segments them.
- The evaluator calculates the net edge of each method against a criterion set before testing it (CON-006).
- This also approves the scope expansion toward perpetual futures (see Angle E).
Decided by: the author, Oct 26, 2026, «I would go with E first» and «yes, rather it would be that, ETL + evaluator with E1. As the first decision».
Route: brief decision. How to record and where to store remains as input for an ADR in `designing-system`.

### DEC-02 — Ladders
Status: Decided
Decision: ladders (OP-025) are left out for now. They are not the second strategy. The probe code is kept in `docs/discovery/spikes/DQ-006-ladders/`.
Decided by: the author, Oct 26, 2026, «The ladders stay out for now.»
Route: brief decision.

### DEC-03 — Expectation, timeframe and threshold for E1
Status: Decided
Decision:
- **Research first.** The ETL, the evaluator and the studies are worth it even if E1 does not win; profit is a possible outcome, not the goal.
- **Timeframe:** the first verdict on E1 comes after **4 weeks** of paper trading with the ETL's own data.
- **Threshold to move to the next stage:** paper net profit of **≥ 10% per year on the capital posted as collateral**, after fees, basis risk and slippage.
- Below the threshold, E1 is discarded or reformulated, with evidence and following CON-006.

Decided by: the author, Oct 26, 2026, with the options «Research first (Recommended)», «4 weeks (Recommended)» and «≥ 10 % per year».
Route: brief decision. Closes for E1 the open decision "Thresholds to move between stages".

### DEC-04 — C, D and E2
Status: Decided
Decision: C (weather), D (crypto options) and E2 (perps against prediction markets) are left out for now. They are reconsidered after the E1 verdict.
Decided by: the author, Oct 26, 2026, «Out for now (Recommended)».
Route: brief decision.

### DEC-05 — Legal opinion
Status: Decided
Decision: no legal opinion is requested before using real money on E1. For the author it is enough that Polymarket Perps does not block Mexico in its country list [S-066]. The author assumes the legal risk. This is **not** a confirmation that it is legal: the Mexican framework for leveraged derivatives remains unreviewed. **Issue**, accepted by the author.
Decided by: the author, Oct 26, 2026, «No, the list of countries is enough for me».
Route: brief decision; changes the text of CON-005.

Closed on Oct 26, 2026 (see the Decision of each DQ):
- The DQs that remain alive with the new focus. DQ-002, DQ-004, DQ-005, DQ-009 and DQ-010 are reformulated for perps. DQ-003, DQ-006, DQ-007 and DQ-008 apply only if prediction market strategies come in.

## Challenge

A reviewer agent with no prior context reviewed this document, the probes and the sources on Oct 25, 2026. It recalculated the two probes with the cached data. Verdict: fail, with 3 serious defects. Each finding and what changed:

- **F-1, the 6 best violations of B were phantom prices** (empty books, 404) → corrected in the B result. The maximum with a real book is 2.6%.
- **F-2, IMDEA versus Gebele comparison** → the "35 times less" was removed. IMDEA reports extracted profit, not a ceiling. The full text of Gebele was read and its period and method were recorded.
- **F-3, "nobody measured duration"** → false. Gebele measures medians of 16 s and 8 s, and 58.7% of episodes over 50 min. Corrected in DQ-003 and DQ-005; S-033 withdrawn.
- **F-4, IMDEA's 3.5% is not a precision** → corrected in DQ-006 and OP-024.
- **F-5, "the forecast carries no information" was overqualified** → lowered to Hypothesis, with standard errors.
- **F-6, timing offset in C** → noted. It favors the model, so "the market wins" comes out reinforced.
- **F-7, the weather resolution rule changed within the period** → noted.
- **F-8, the criteria were not applied evenly:**
  - OP-020 was ruled out by CR-002.
  - It was noted that OP-008 and probe C do not measure CR-001.
  - It was noted why D was not probed.
  - C and D remain as a scope expansion that the author must approve.
- **F-9, labels on S-016** → lowered or made more precise.
- **F-10, arithmetic** → the capital trapped in "unemployment" is 3.2 months, not 2. The edge is expressed over the 1 USD payout.
- **F-12, the 0 fee in weather is a recent pattern** → noted.
- **Options that were missing:**
  - OP-044: sell side.
  - OP-045: duration with others' books.
  - OP-046: ladders between events.
- **What the reviewer confirmed:**
  - The direction of the pairs is correct.
  - The fee formula matches S-013.
  - The walk of the books is correct.
  - The 60/60 of the sample is also valid in its reading.
  - The counts and the Briers are correct.
- **Left uncorrected, as minor:**
  - The script ignores the exponent of the fee schedule; only 1 of about 401 thousand markets uses it.
  - "June 2027 meeting" is read as June 20, with no effect on the sample.

## Sources

- S-001 — Polymarket API, introduction, https://docs.polymarket.com/api-reference/introduction, primary
- S-003 — Polymarket, geoblocking (FAQ), https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking, primary
- S-004 — Polymarket, geoblock API, https://docs.polymarket.com/api-reference/geoblock.md, primary
- S-005 — PYMNTS, identity verification, May 27, 2026, https://www.pymnts.com/identity/2026/polymarket-debuts-new-id-verification-measures-for-customers/, secondary
- S-007 — Guide on Polymarket US, https://pm.wiki/es/learn/is-polymarket-legal-in-the-us, vendor (snippet only)
- S-008 — SoloAzar, interview on prediction markets in Mexico, Aug 28, 2026, https://soloazar.com/en/interviews/prediction-market-in-mexico-the-new-frontier-between-betting-and-finance, secondary
- S-009 — The Block, Argentina orders block, https://www.theblock.co/post/393877/argentina-orders-nationwide-block-of-polymarket-as-scrutiny-of-prediction-markets-grows-report, secondary (snippet only)
- S-010 — La República (Spain), La Nación (Brazil), Sigma (Nevada): https://www.larepublica.co/globoeconomia/espana-bloquea-los-mercados-de-prediccion-polymarket-y-kalshi-por-carecer-de-licencia-de-juego-4400562 ; https://www.lanacion.com.py/mundo/2026/04/25/brasil-bloqueo-una-veintena-de-sitios-de-apuestas-predictivas/ ; https://sigma.world/es/news/nevada-regulators-target-polymarket-in-landmark-lawsuit/, secondary
- S-011 — Sportico, international access to Kalshi, Oct 2025, https://www.sportico.com/business/sports-betting/2025/kalshi-international-countries-access-1234874388/, secondary (snippet only)
- S-012 — iGaming and Laika Labs on Kalshi countries, https://www.ingame.com/prediction-markets-world-cup/ ; https://laikalabs.ai/prediction-markets/kalshi-legal-supported-restricted-countries, vendor
- S-013 — Polymarket, fees, https://docs.polymarket.com/trading/fees, primary
- S-014 — Polymarket, changelog, https://docs.polymarket.com/changelog/predictions.md, primary
- S-015 — Polymarket, rate limits, https://docs.polymarket.com/api-reference/rate-limits, primary
- S-016 — Polymarket, prices and order books, https://docs.polymarket.com/market-data/prices-order-books.md, primary
- S-017 — Polymarket, market WebSocket, https://docs.polymarket.com/market-data/websocket/overview, primary
- S-018 — Polymarket, gasless operations, https://docs.polymarket.com/trading/gasless.md, primary
- S-019 — Polymarket, positions and CTF, https://docs.polymarket.com/trading/positions/manage.md ; https://docs.polymarket.com/developers/CTF/overview, primary
- S-020 — Polymarket, negRisk, https://docs.polymarket.com/developers/neg-risk/overview, primary
- S-021 — Saguillo et al., Unravelling the Probabilistic Forest, arXiv 2508.03474, https://arxiv.org/html/2508.03474v1, primary
- S-022 — Polymarket, create orders, https://docs.polymarket.com/trading/orders/create, primary
- S-023 — Polymarket, resolution, https://docs.polymarket.com/concepts/resolution.md, primary
- S-024 — Zenodo, Polymarket Crypto Up/Down Order Books, https://zenodo.org/records/22084115, primary, CC BY 4.0
- S-025 — pmdata.dev, https://pmdata.dev/polymarket-order-book-data, vendor
- S-026 — Marketlens, https://marketlens.trade/polymarket-historical-data, vendor
- S-028 — polymarketdata.co, https://www.polymarketdata.co/polymarket-order-book-data, vendor
- S-029 — CryptoStruct, https://cryptostruct.com/exchanges/polymarket, vendor
- S-030 — Becker, prediction-market-analysis, https://github.com/Jon-Becker/prediction-market-analysis, primary
- S-031 — Goldsky, Polymarket, https://docs.goldsky.com/chains/polymarket.md, primary
- S-033 — Withdrawn: it said "nobody measured duration" and S-034 does measure it
- S-034 — Gebele, Mutzel and Matthes, Executable Arbitrage and Market Efficiency in Prediction Markets, arXiv 2608.00666, https://arxiv.org/abs/2608.00666 ; full text at https://arxiv.org/html/2608.00666v1, primary
- S-036 — Polymarket, trading overview (Chinese version), https://docs.polymarket.com/cn/trading/overview.md, primary (verify by hand)
- S-037 — Kim et al., arXiv 2602.07048, https://arxiv.org/abs/2602.07048, primary
- S-038 — Paleka et al., arXiv 2412.18544, https://arxiv.org/pdf/2412.18544, primary (snippet only)
- S-039 — Polymarket, UMA, https://docs.polymarket.com/developers/resolution/UMA, primary
- S-040 — CryptoSlate, Ukraine market, Mar 26, 2025, https://cryptoslate.com/polymarket-faces-backlash-over-resolving-disputed-7-million-trump-ukraine-market/, secondary
- S-041 — Decrypt, Zelenskyy's suit, Jul 9, 2025, https://decrypt.co/329210/polymarket-rules-no-237m-bet-zelenskyys, secondary
- S-042 — The Block, Strategy, Jun 4, 2026, https://theblock.co/post/403600/polymarket-upholds-no-outcome-strategy-bitcoin-sale-market, secondary
- S-043 — KuCoin and Finance Magnates on disputes, https://www.kucoin.com/news/flash/polymarket-dispute-resolutions-dominated-by-nine-whale-addresses-critics-raise-concerns ; https://www.financemagnates.com/fintech/polymarkets-arbitration-model-faces-conflict-of-interest-questions/, secondary (snippets only)
- S-044 — Wen, Zhou and Huang, preprint Apr 2026, https://www.alphaxiv.org/abs/2604.15674, secondary
- S-045 — Le, arXiv 2602.19520, https://arxiv.org/html/2602.19520v1, primary
- S-046 — Song, polymarket-calibration, https://github.com/carol-747/polymarket-calibration, secondary
- S-047 — Qin and Yang, arXiv 2606.04217, https://arxiv.org/html/2606.04217v1, primary
- S-048 — Mok et al., SSRN 7574278, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7574278, primary (snippet only)
- S-049 — Bürgi, Deng and Whelan, Makers and Takers, https://www.ucd.ie/economics/t4media/WP2025_19.pdf, primary (snippets only)
- S-050 — simplefunctions.dev, live calibration, https://simplefunctions.dev/calibration, vendor
- S-051 — Apify, ebag73/polymarket-arb-scanner, https://apify.com/ebag73/polymarket-arb-scanner.md, vendor
- S-052 — PolyArb, https://github.com/arnavnayak42/PolyArb, primary
- S-053 — Synpath-ai, prediction-market-arbitrage-trading-bot, https://github.com/Synpath-ai/prediction-market-arbitrage-trading-bot, primary
- S-054 — ImMike, polymarket-arbitrage, https://github.com/ImMike/polymarket-arbitrage, primary
- S-055 — Gneiting and Raftery, scoring rules, JASA 2007, https://apps.dtic.mil/sti/tr/pdf/ADA459827.pdf, primary (snippet only)
- S-056 — López de Prado, Advances in Financial Machine Learning, chs. 7 and 12, https://www.wiley-vch.de/de/fachgebiete/finanzen-wirtschaft-recht/advances-in-financial-machine-learning-978-1-119-48208-6, primary (index)
- S-057 — Bailey and López de Prado, Deflated Sharpe Ratio, https://papers.ssrn.com/abstract=2460551, primary
- S-058 — Bailey et al., Probability of Backtest Overfitting, https://papers.ssrn.com/abstract=2326253, primary
- S-060 — Mirror pages of Polymarket temperature markets, https://polyguana.com/market/3614352 ; https://polyguana.com/market/2866904, secondary
- S-061 — Promotional guide for a weather bot, https://youmind.com/landing/x-viral-articles/polymarket-weather-trading-bot-blueprint, vendor
- S-062 — Market efficiency of prediction markets (Polymarket versus Deribit options), https://fc26.ifca.ai/defi/papers/market-efficiency-prediction-markets.pdf ; barrier contracts: https://ideas.repec.org/p/arx/papers/2606.19517.html, primary (abstracts only)
- S-063 — Decrypt, Polymarket launches Perps, https://decrypt.co/377483/polymarket-crypto-perpetual-futures ; The Defiant, https://thedefiant.io/news/defi/polymarket-opens-perps-trading-to-the-public-with-20x-leverage, secondary
- S-064 — Polymarket Perps, funding, https://docs.polymarket.com/perps/learn-about-trading/funding.md, primary
- S-065 — Polymarket Perps, fees, https://docs.polymarket.com/perps/learn-about-trading/fees.md, primary
- S-066 — Polymarket Perps, FAQ (geographic restrictions), https://docs.polymarket.com/perps/faq.md, primary
- S-067 — Polymarket Perps, market data, https://docs.polymarket.com/perps/market-data.md, primary
- S-068 — Hyperliquid, `info` API (`fundingHistory`, `l2Book`, `meta`), https://api.hyperliquid.xyz/info, primary (API responses)
- S-069 — Hyperliquid, fees, https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees, primary
- S-059 — Page and Clemen, Economic Journal 2013, https://people.duke.edu/~clemen/bio/Published%20Papers/45.PredictionMarkets-Page&Clemen-EJ-2013.pdf, primary (snippet only)
