# M04 — Basis, liquidation and E1 verdict

Status: Ready for implementation
Approved by: the author, 2026-11-11, «Apruebo» (includes DEC-7 to DEC-13)
Size: medium
Reliability: strict
Implementation effort: high (money and liquidation arithmetic that decides the verdict; byte-identical reproducibility)
Parent: none (builds on `docs/changes/2026-11-09-M03-e1-paper-evaluation/`, accepted 2026-11-11)

## Goal
Every minute with an open paper position, Polyquack measures the basis and each leg's distance to liquidation, and liquidates a leg whose mark price crosses its level. When a run reaches its horizon, Polyquack excludes the pairs over the gap limit, computes the net profit breakdown and the return on the maximum collateral, and issues the verdict. E1's verdict comes from a re-evaluation of variant 1 over stored data, and two re-evaluations with the same data are identical.

## Evidence and Current Behavior
See `audit.md` (2026-11-11, commit `cbd6299`). Summary:
- Entry point `src/polyquack/evaluation/runner.py:86-93` (`evaluate`), mode hard-coded live; CLI `src/polyquack/cli.py:64-79`.
- Covering tests: `tests/test_evaluate.py`, `test_readings.py`, `test_rule_and_walk.py`, `test_preregistration.py`, `tests/evalkit.py`.
- Consumers of altered contracts: audit Evidence Facts (grep).
- No price reader, no per-minute step, no liquidation, no verdict, no re-evaluation; funding amount is `rate × notional_per_leg` (`runner.py:413-417`); Hyperliquid `index_price` is its oracle price (`platforms.py:306`).

## Scope
Included:
- Per-minute measurement and liquidation for open positions in every run (live and re-evaluation).
- Funding amount by the documented price per platform (replaces M03 DEC-10).
- Re-evaluation runs, horizon closing, pair exclusion, breakdown, collateral, verdict; commands to re-evaluate and show a verdict.
- Schema additions and canonical design updates; the 2026-10-26 "no positions" decision recorded in the PRD.

Excluded:
- Dashboard (M05), publishing (M06), new methods or variants, ingestion changes, any order or account endpoint (BR-011).
- Recomputing amounts already stored by the live run before deploy.

## Decisions and Assumptions
Approved by the author (shaping and `audit.md`, 2026-11-11):
- **DEC-1 (reference price):** basis and liquidation use `price_reading.mark_price` on both platforms.
- **DEC-2 (funding amount):** a payment to a leg is `rate × leg quantity × price`, where price is Hyperliquid's `index_price` (its oracle) and Polymarket's `mark_price`, from the latest `price_reading` of that instrument with `minute ≤` the payment's minute and at most 60 minutes older. Sign as in M03 (a positive rate makes longs pay). A payment with no such price is not credited and is counted as uncredited in the verdict breakdown.
- **DEC-3 (liquidation loss):** a liquidated leg loses its whole isolated margin, `notional_per_leg / leverage`.
- **DEC-4 (uncovered leg):** the other leg is closed in the same minute by walking the usable snapshot (M03 DEC-4 age rule against the end of that minute) with its taker fee and slippage; if none is usable or the book is thin, it is closed at the first later minute where it can be, and stays uncovered until then.
- **DEC-5 (verdict):** `continue` if the annual return on collateral is at least the preregistered `min_annual_net_return_on_collateral`, `discard` if below; when the run opened no position, `investigate_further` with an undefined return and reason `no positions` (author, 2026-10-26, «Investigate further (Recommended)»); never a division by zero.
- **DEC-6 (verdict source):** the verdict is issued for re-evaluation runs; the live run stops at its horizon (`complete`) without a verdict.

Spec decisions (derived from the design; approved with the spec):
- **DEC-7 (liquidation level):** isolated margin per leg at the reference leverage L: long `p_liq = p0 × (1 − 1/L) / (1 − m)`, short `p_liq = p0 × (1 + 1/L) / (1 + m)`, with `p0` the leg's open `avg_price` and `m` the instrument's `maintenance_margin` effective at the minute. A long is liquidated when the minute's mark ≤ `p_liq`, a short when ≥ `p_liq`. Distance = `(mark − p_liq) / mark` for a long and `(p_liq − mark) / mark` for a short. Derived from equity = maintenance margin; neither platform publishes the formula.
- **DEC-8 (measurement):** for each minute `M` a position is open, `basis = PM mark − HL mark` of minute `M`, `basis_change = basis − basis of the position's first measured minute`, distances per DEC-7; any missing price leaves its values null. A minute is processed with cutoff `M + 1 min` (reads `price_reading.minute ≤ M`).
- **DEC-9 (horizon):** a run's horizon is `starts_at + horizon_days`; positions still open at the last decision instant inside it are closed by a simulated close at that instant (book walk, taker fee); no decision after it.
- **DEC-10 (breakdown):** per pair and total: funding (sum of payments), fees (sum of trade fees), slippage (sum), basis effect (each closed leg's `(exit best_price − entry best_price) × quantity`, signed by side; zero for a liquidated leg), liquidations (sum of losses), uncredited payments (count); net = funding − fees − slippage + basis effect − liquidations.
- **DEC-11 (collateral and return):** a position commits `2 × notional_per_leg / leverage` while open; the run's collateral is the maximum committed at once by positions of non-excluded pairs (PD-020); annual return = net ÷ collateral × 365 ÷ horizon days (BR-003).
- **DEC-12 (exclusion):** per pair, over `[max(paired_at, starts_at), min(delisting, horizon end))`: an hour counts as without funding if either platform lacks a reading for it; a minute counts as without snapshot if either platform lacks one; the pair is excluded if hours without funding exceed 5% or minutes without snapshot exceed 10% (PD-013, PD-021). If every pair is excluded, the run is `not_qualifiable` with its reason and no verdict.
- **DEC-13 (variants tested):** the number of the method's variants with `first_run_at` set when the verdict is issued.

Assumptions:
- ASM-1: `price_reading` has a row per instrument and minute most of the time; validated by ingestion completeness. Not a stop: missing prices give null measurements (AC-1).
- ASM-2: re-evaluating 28 days for 38 pairs finishes in under 15 minutes on the VM without making ingestion lose minutes; stop if not.

## Requirements and Acceptance
| ID | Required Behavior | Acceptance |
|---|---|---|
| R-1 | Every run processes, before each decision instant, every minute since its last processed minute: a `position_measurement` per open position and minute (DEC-8) | AC-1 (plan AC-019): one measurement per open position and minute; a missing price leaves its value null |
| R-2 | A leg crossing its level is liquidated in that minute (DEC-7): a `paper_trade` of kind `liquidation` at the minute with `avg_price` = `best_price` = `p_liq`, the leg's quantity, `fee` 0, `slippage` 0, `loss` per DEC-3; the position becomes `leg_liquidated`, the other leg is closed per DEC-4 and the position becomes `closed` with `closed_at` = that close | AC-2 (plan AC-020, TST-014): for a sample mark path at 2x the leg is liquidated in the crossing minute with loss = 500 USD on 1,000 USD, and the other leg is closed with its trade |
| R-3 | Funding accrual uses DEC-2 and stops per leg at that leg's closing or liquidation trade | AC-3: amounts equal `rate × quantity × price` with the documented price per platform; no payment after a leg's own end; uncredited payments counted |
| R-4 | `polyquack reevaluate VARIANT` creates a run with mode `reevaluation` and the live run's `starts_at`, and decides every decision instant up to `min(now, horizon end)` with M03 and M04 rules; a later call creates a new run | AC-4: a re-evaluation over seeded data produces decisions, trades, payments and measurements |
| R-5 | At the horizon (DEC-9) a run closes its open positions, computes exclusion (DEC-12), breakdown (DEC-10), collateral and return (DEC-11) and, for a re-evaluation, the verdict (DEC-5, DEC-13); the run becomes `complete`, or `not_qualifiable` | AC-5 (plan AC-021, AC-022, TST-015, TST-016): pairs entering and leaving mid-period are excluded or kept as the limits say; the verdict shows funding, fees, slippage, basis, liquidations, maximum collateral, annual return and variants |
| R-6 | No position opened in the horizon gives `investigate_further`, a null return and reason `no positions` | AC-6 (plan AC-023, TST-017) |
| R-7 | Two re-evaluations of the same variant over the same data give identical decisions, trades, payments, measurements, exclusions and verdict (ids and `issued_at` aside) | AC-7 (plan AC-024, TST-018): byte-for-byte equal exports of both runs |
| R-8 | `polyquack verdict RUN` prints the verdict, breakdown, excluded pairs with their counts and variants tested | AC-8: the output after a completed re-evaluation |
| R-9 | Every read of the new logic goes through the Reader with a cutoff in SQL (prices by `minute ≤` the measured minute or decision instant; parameters by `effective_from ≤`) | AC-9: seeding prices after the cutoff changes no measurement, liquidation or payment; `future_data_violations` also covers measurements and liquidation trades |
| R-10 | Writes stay in short transactions (one per processed hour of minutes and per pair decision), lock contention handled as in M03 | AC-10: a second writer under the busy timeout loses nothing |

## Contracts and Risk Controls
- **Schema:** `position_measurement` and `excluded_pair` as `schema.dbml`; `verdict` as `schema.dbml` with `annual_return_on_collateral` nullable and a nullable `reason`; `paper_trade.loss real null` (set only on `liquidation`); `run.mode` gains `reevaluation`; amounts rounded with `round_money`.
- **Live run:** keeps running with M04 rules from deploy on; amounts it stored before deploy keep M03's formula (not recomputed).
- **Preserved:** M03 decision rule, no-future-data reads, freeze triggers, variant 1's preregistration, ingestion.
- **Risk:** re-evaluation writes many rows; short transactions and the M03 deferral handling apply.

## Canonical Design Impact
- Manifest: `docs/spec/manifest.yaml`
- Update:
  - `docs/product/prd.md`: new §15 row PD-023 for the "no positions" decision (author, 2026-10-26, quote); BR-003 and FR-017 mention the undefined return and `investigate_further`; FR-015 lists liquidation losses in the split.
  - `docs/design/domain.md`: reference prices (DEC-1, DEC-2), liquidation level and loss (DEC-3, DEC-7), uncovered leg (DEC-4), horizon close (DEC-9), breakdown (DEC-10), exclusion counting (DEC-12), re-evaluation as a separate run (DEC-6) — resolves F-013.
  - `docs/design/data/schema.dbml`: the Contracts changes and notes.
  - `docs/design/ux/flows.mmd`: F-002 per-minute step; F-003 no-positions branch and outcome rule.
  - `docs/design/architecture/quality-attributes.md`: NFR-007 test compares two re-evaluations.
  - `docs/design/review.md`: F-013 resolved citing this folder.
  - `README.md`: `reevaluate`, `verdict`.
- Preserve: ADRs, `architecture.dsl`, ingestion artifacts.

## Quality Obligations
- Tests (`pytest`, no network; tests first with red evidence): TST-014 liquidation with a price path at 2x (long and short, crossing and not crossing, maintenance margin change); TST-015 exclusion with pairs entering and leaving mid-period, both limits and their edges; TST-016 maximum collateral with overlapping positions and empty hours; TST-017 no positions; TST-018 two re-evaluations byte for byte; funding amount per platform and the uncredited case; measurement nulls; horizon close; verdict outcome edges (exactly 10%); no-future-data for prices.
- Static/build: `uv run mypy --strict src tests`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest`, `gitleaks detect --no-git --source . --redact --no-banner`.
- QA on the VM (`vm-qa-log.md`): deploy; live run measurements and no ingestion loss; a re-evaluation of variant 1 over the data so far (partial, before the horizon) and its run time (ASM-2); after the horizon (about 2026-12-07), the verdict of a re-evaluation.
- Coverage/mutation: each R-* has a test or a named VM check; manual mutations on DEC-7, DEC-10, DEC-11, DEC-12 and DEC-5.

## Done When
On the VM, after E1's horizon, `polyquack reevaluate 1` completes and `polyquack verdict` shows the breakdown, excluded pairs, maximum collateral, annual return, outcome and variants tested; a second re-evaluation gives the identical verdict; the live run kept its measurements without ingestion loss; tests and static gates pass. Until the horizon, the change is verified with a partial re-evaluation and tests.

## Change Surface
- Expected edits (medium confidence): `src/polyquack/evaluation/**` (runner, readings, new measurement, liquidation and verdict modules), `src/polyquack/cli.py`, `src/polyquack/storage/schema.sql`, `README.md`, `tests/**`, the documents in Canonical Design Impact.
- Do not touch: ingestion code and tables, freeze triggers, `deploy/polyquack-ingestion.service`, `docs/discovery/**`.

## Triggered Artifacts
| Artifact | Fired? | Reason |
|---|---|---|
| audit.md | Yes | reliability `strict` |
| plan.md | No | one writer, no staged rollout |
| execution.md | Yes | implemented by a subagent and verified by another; the verdict on the VM comes in a later session |

## Stop Conditions
- Work goes on `feat/basis-liquidation-verdict/josueDev` from `dev`; no commit without the author's confirmation.
- The implementation needs to change variant 1's preregistration, an ingestion table or an ADR.
- ASM-2 is false.
- A platform document contradicts DEC-1, DEC-2 or DEC-7 when the implementer checks it.
