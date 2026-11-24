# M04 — Basis, liquidation and E1 verdict — Audit

Status: Ready for specification
Size: medium
Reliability: strict
Audit trigger: strict

## Evidence Facts
| Fact | Evidence |
|---|---|
| Entry point | `src/polyquack/evaluation/runner.py:86-93` (`evaluate`), called by `src/polyquack/cli.py:64-71`; run mode hard-coded `'live'` in `_start_runs` (`runner.py:104-123`) and `_live_runs` (`runner.py:130-136`) |
| Covering tests | `tests/test_evaluate.py` (`future_data_violations` at `:71-87`), `tests/test_readings.py`, `tests/test_rule_and_walk.py`, `tests/test_preregistration.py`, helpers `tests/evalkit.py` (`run_hours` drives the clock through `now_ms`, `:91-94`) |
| Consumers of each altered contract | funding amount (`runner.py:413-417`): tests asserting `rate*notional` in `tests/test_evaluate.py`; `run.mode` (`schema.sql:143`): `runner.py:104-136`, `preregistration.py` (`render_variants` counts runs); new tables `position_measurement`, `excluded_pair`, `verdict`: none yet; `instrument_parameters`: written by `db.py:177-200`, read by no evaluation code. Found with grep (`rg -n "mode|notional_per_leg|instrument_parameters|price_reading" src tests`); no language server |

## Baseline
| Field | Value |
|---|---|
| Repository root | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `dev` (M04 will work on `feat/basis-liquidation-verdict/josueDev`) |
| Commit SHA | `cbd6299856cfdcff4c5e306a6642d8e51715cb7c` (M03 merged, PR #5) |
| Working tree | Clean |
| Relevant pre-existing changes | E1 variant 1 live on the VM since 2026-11-09 22:22 UTC (window 24, entry 0.00002, exit 0.000005); its 28-day horizon ends about 2026-12-07. `master` received M03 directly through PR #4 (outside the dev → master rule); `dev` has it through PR #5 |
| Audit date | 2026-11-11 |

## Desired Outcome and Constraints
- Outcome: every minute with an open position, basis and per-leg distance to liquidation are measured; a leg that crosses its level is liquidated; at the horizon, pairs over the gap limit are excluded, the net profit breakdown and the return on the maximum collateral are computed and the verdict is issued; a re-evaluation with the same data reproduces the result (`docs/build/plan.md:239-294`).
- Included: FR-015 to FR-018, FR-023 to FR-025, NFR-007, BR-002, BR-003, BR-009, BR-010, PD-013, PD-020, PD-021; F-013; the "no positions" decision of 2026-10-26.
- Excluded: dashboard (M05), publishing (M06), new methods.

## Current Behavior Trace
1. `evaluate` starts a live run per variant and decides every due hour (`runner.py:86-180`); accrual credits `rate × notional_per_leg` per leg (`runner.py:413-417`).
2. Positions close only at a decision instant (`_record`, `runner.py:301-349`); there is no per-minute step, no liquidation, no verdict, no re-evaluation command (`cli.py:76-79`).
3. `price_reading` has `mark_price` and `index_price` per `(instrument_id, minute)` (`schema.sql:83-91`); Hyperliquid's `index_price` is its `oraclePx` (`platforms.py:306`), Polymarket's comes from its tickers (`platforms.py:208`). No Reader method reads prices (`readings.py`).
4. `instrument_parameters.maintenance_margin = 0.5 / max_leverage` and nullable `liquidation_fee` (`platforms.py:341`, `:357`; `schema.sql:31-39`).
5. `completeness.py:22-66` counts expected hours and minutes per instrument over a rolling window; PD-013 needs per pair between pairing and delisting within the run.

## Canonical Design Facts
- PRD: FR-015 (`prd.md:176-177`), FR-016 (`:179-180`), FR-017 (`:182-183`), FR-018 (`:185-186`), FR-023 (`:200`), FR-024 (`:203`), FR-025 (`:206-207`), NFR-007 (`:253-254`), BR-002 (`:277`), BR-003 (`:278`), BR-009 (`:284`), BR-010 (`:285`), PD-013 (`:359`), PD-020 (`:366`), PD-021 (`:367`). The 2026-10-26 "no positions → investigate further" decision is only in `plan.md:287`; not yet a PRD §15 row (§15 ends at PD-022, `prd.md:368`).
- Domain: Run (`domain.md:70-78`), Collateral (`:26`), Excluded pair (`:28`), Basis (`:30`), Liquidation (`:31`), Net profit (`:32`), Verdict (`:33`), Paper position lifecycle with `leg liquidated` and uncovered leg (`:80-87`, `:115-116`), funding amount open to F-013 (`:86`).
- Schema: `position_measurement` (`schema.dbml:224-234`), `excluded_pair` (`:160-171`), `verdict` (`:236-244`, `annual_return_on_collateral` not null), `run` (`:150-158`), `paper_trade.kind` includes `liquidation` (`:202`), `paper_position.status` `open|leg_liquidated|closed` (`:195`).
- Flows F-002 per-minute step and F-003 verdict (`flows.mmd:37-53`).
- `review.md:319-338` F-013 open: name the reference price for basis, liquidation and funding; handle an unknown liquidation fee without inventing it.

## Platform Facts (official docs, read by a researcher subagent on 2026-11-11; fetch-tool extractions)
- Hyperliquid (`https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations`, `.../margining`, `.../funding`): liquidation uses the mark price; liquidatable when equity falls below maintenance margin; maintenance margin is half the initial margin at max leverage; "there is no clearance fee on liquidations"; an isolated backstop liquidation transfers the position and its margin to the liquidator vault; funding payment = `position_size * oracle_price * funding_rate`, "not the mark price".
- Polymarket Perps (`https://docs.polymarket.com/perps/learn-about-trading/margin`, `.../liquidation-mechanics`, `.../faq`, `.../funding`): mark price is used "for margin, PnL, liquidation, and funding"; liquidation when `Equity < MM`, `MM = Notional × MMR`, `MMR = 0.5 / MaxLeverage`; fills while liquidated pay `Notional × (taker rate + LiquidationFeeRate)`; no liquidation-price formula and no funding payment formula published.

## Contradictions and Risks
- C-1: the author first chose mark for funding; Hyperliquid's docs say oracle. Resolved by DEC-Q1 below.
- C-2: no liquidation-price formula in the design; derivable from equity = maintenance margin for isolated 2x per leg (inference): long `p_liq = p0 × (1 − 1/L) / (1 − m)`, short `p_liq = p0 × (1 + 1/L) / (1 + m)`, with `p0` the leg's entry price, `L = 2`, `m` the maintenance margin rate as of the minute.
- C-3: `verdict.annual_return_on_collateral` is not null while the "no positions" case needs an undefined return (schema change).
- C-4: `paper_trade` has no liquidation-loss column and `fee`/`slippage` are not null; a liquidation row needs a defined content.
- C-5: re-evaluation needs its own `run` row (decision key includes `run_id`, `schema.sql:158`) and nothing links it to the live run.
- C-6: a re-evaluation reads by `source_time ≤ cutoff`, so readings that arrived after the live decision (recovered funding, late books) can change decisions relative to the live run; AC-024 must compare two re-evaluations, not re-evaluation versus live.
- C-7: the funding formula changes mid-run for the live run (M03 amounts are `rate × notional`); the verdict comes from a re-evaluation, so the live mix does not enter it.
- C-8: FR-015's split omits liquidation losses while BR-002 and `verdict.breakdown` include them.
- C-9: PRD says "cent by cent" (NFR-007) while money is rounded to micro-USD (M03 DEC-11, approved).

## Author Decisions (2026-11-11)
- Shaping: reference price for basis and liquidation distance = mark; verdict from a re-evaluation of variant 1 over stored data.
- DEC-Q1 (adjusts the shaping answer on funding): funding payment = rate × quantity × the price each platform documents: Hyperliquid oracle (`index_price`), Polymarket mark. Liquidation uses mark on both.
- DEC-Q2: a liquidated leg loses its whole isolated margin (`notional / leverage`), the worst case; no execution is invented.
- DEC-Q3: the uncovered leg is closed in the same minute by walking that minute's book with its taker fee and slippage.
- DEC-Q4: verdict `continue` if the annual return on collateral is at least the preregistered 10%, `discard` if below; `investigate_further` only when no position was opened (undefined return, reason "no positions").

Defaults proposed for the spec (not asked): positions open at the horizon are closed by a simulated close at the horizon's decision instant; the basis effect is the legs' price result at best prices, with slippage reported separately; measurements and liquidation checks run inside the hourly evaluation for the minutes since the last processed one, each with its own cutoff.

## Candidate Ownership
| Workstream | May Read | Candidate Write Set | Coupling / Conflict Risk |
|---|---|---|---|
| single writer, sequential | all of `src/`, `tests/`, design docs | `src/polyquack/evaluation/**`, `cli.py`, `storage/schema.sql`, `README.md`, `tests/**`, canonical docs | `runner.py` is touched by every requirement |

## Do Not Touch
- Ingestion code, tables and triggers; the preregistration freeze; variant 1's preregistration.

## Recommended Next Step
Write the spec.
