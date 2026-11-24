# M04 — Basis, liquidation and E1 verdict — Execution

Status: Round 3 correction implemented, awaiting verification pass 4

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `feat/basis-liquidation-verdict/josueDev` (no upstream) |
| Planned base | `dev` with M03 merged |
| Current start commit | `cbd6299` (the audited commit) |
| Working tree before edits | clean except the untracked change folder |
| Pre-existing relevant changes | none |
| Untracked files before edits | `docs/changes/2026-11-11-M04-basis-liquidation-verdict/` (`audit.md`, `spec.md`, `execution.md`) |

Baseline checks on 2026-11-11: `uv run pytest -q` passed (204 tests at M03).

## Preflight Verdict
Safe sequentially only

Reason: the audited commit is the start commit; no overlapping changes; `runner.py` is touched by every requirement, so one writer works in sequence (spec: no plan).

## Execution Topology
Sequential (one implementer subagent; the main session is the integration owner)

## Platform document check (DEC-1, DEC-2, DEC-7)
Read again on 2026-11-11 with a fetch tool (extractions, not verbatim pages):
- Hyperliquid liquidations: liquidation uses the mark price; isolated formula `liq_price = price - side * margin_available / position_size / (1 - l * side)` with `margin_available = isolated_margin - maintenance_margin_required`. Substituting `isolated_margin = notional / L` and `maintenance = m x notional` gives exactly DEC-7's long and short levels, so DEC-7 agrees with it.
- Polymarket liquidation mechanics: liquidation when `Equity < MM` on a new mark price; no price formula published.
- Hyperliquid funding and Polymarket margin/funding pages were not fetched again; their facts are those recorded in `audit.md`. No document contradicts DEC-1, DEC-2 or DEC-7.

## Executed Work
- Schema (`src/polyquack/storage/schema.sql`): `paper_trade.loss`, `position_measurement`, `excluded_pair`, `verdict` (nullable return and `reason`), all `IF NOT EXISTS`. The new `paper_trade.loss` column of an existing database is added by `src/polyquack/evaluation/migration.py` (`add_missing_columns`, idempotent, rows kept), called at the start of `evaluate` and `reevaluate`. `storage/db.py` (outside the write set) was not touched.
- `evaluation/liquidation.py`: level, crossing and distance (DEC-7).
- `evaluation/readings.py`: `prices`, `payment_prices`, `maintenance_margins`, `snapshot_minutes`, `delisted_since_ms`, and `payments(..., uncredited_for=)`; every one bounded by the cutoff in SQL.
- `evaluation/runner.py`: per-minute step (`_measure`, `_measure_position`, `_measure_chunk`), liquidation and uncovered-leg close, horizon close, funding by DEC-2 with per-leg end, `reevaluate`, horizon bound on `_evaluate_run`.
- `evaluation/verdict.py`: exclusion, breakdown, collateral, annual return, outcome, verdict row, `render_verdict`.
- `evaluation/preregistration.py`: the parsed rule also carries `horizon_days` and the criterion (values unchanged, still fixed).
- `cli.py`: `reevaluate VARIANT`, `verdict RUN`.
- Tests: `test_liquidation_math.py`, `test_verdict_rules.py`, `test_basis_liquidation.py`, `test_reevaluation.py`, additions to `test_migration.py`; `evalkit.py` helpers and the extended `future_data_violations` (now in `evalkit.py`, imported by `test_evaluate.py`).
- Docs: README, PRD (PD-023, FR-015, FR-017, BR-003), domain, schema.dbml, flows, quality-attributes (NFR-007), review (F-013 resolved).

## Integration Gates
| Gate | Owner | Diff Inspected? | Checks | Result |
|---|---|---:|---|---|
| Sequential implementation | main session | Yes (`git diff --stat`: 15 tracked files, +926/−80, plus 3 new evaluation modules and 4 new test files; `git diff --stat -- src/polyquack/ingestion src/polyquack/storage/db.py deploy` empty) | mypy strict, ruff check, ruff format, pytest ×2, gitleaks | Pass: `270 passed` twice (90 s, 82 s), other checks clean |

## Requirement Status
| ID | Status | Tests |
|---|---|---|
| R-1 | done | `test_ac1_*`, `test_dec8_*`, `test_dec7_*` (measurements, nulls, margin change), `test_r1_*` |
| R-2 | done | `test_ac2_*`, `test_dec7_a_mark_exactly_at_the_level_*`, `test_dec4_*` |
| R-3 | done | `test_r3_*`, M03 funding tests updated to the new amount |
| R-4 | done | `test_ac4_*`, `test_r4_the_reevaluate_command_*` |
| R-5 | done | `test_r5_*`, `test_dec10_*`, `test_tst015_*`, `test_tst016_*`, `test_dec9_*`, `test_dec6_*` |
| R-6 | done | `test_r6_*`, `test_dec12_positions_of_an_excluded_pair_*` |
| R-7 | done | `test_r7_two_reevaluations_*`, `test_ac4_reevaluate_creates_*` |
| R-8 | done | `test_r8_*` |
| R-9 | done | `test_r9_prices_seeded_after_the_cutoff_*`, `test_r9_the_verdict_run_reads_nothing_after_its_horizon`, `future_data_violations` |
| R-10 | done | `test_ac10_a_deferred_measurement_*` plus the M03 deferral tests |
| ASM-2 | measured locally only | see Local timing; the VM figure is pending |

## Deviations and interpretations
- DEC-2 changed M03 funding tests: `tests/test_evaluate.py` `_world` now seeds price readings, and the two assertions on amounts (`test_ac8_funding_accrues_*`, `test_dec11_funding_payments_are_rounded_*`) expect `rate x quantity x price`. No assertion was removed.
- `future_data_violations` moved from `test_evaluate.py` to `evalkit.py` and was extended; the snapshot check allows trades made by the minute step (they read up to the end of their minute) one minute of slack and keeps the strict bound for decision trades.
- Trade `hour` of a liquidation and of the same-minute close is the label of the minute (`iso(M)`), and `closed_at` is that value; the snapshot used by the close can have a source time up to the end of that minute (DEC-4 rule).
- A liquidation row has `snapshot_minute` = its own minute (no snapshot is used).
- DEC-8: the basis baseline is the first measured minute that has a basis; when the very first minute lacks one the change is null until a basis exists.
- DEC-9: decision instants are `starts_at + k hours` for `k < 28 x 24`; the last one is `horizon end - 1 hour` and open positions are closed at that instant, even one just opened there. Superseded in Round 1 (F-5, F-8): no open at that instant, and a close that cannot fill is retried each minute to the horizon end before `unclosed_positions` is reported. The verdict is issued when the clock reaches the horizon end, not at the last instant, because the exclusion counts read up to the horizon end.
- A position with `leg_liquidated` status is not a held position for the decision rule; a decision at an instant where the other leg is still uncovered can open a new position of the pair.
- The breakdown JSON carries `net`, `uncredited_payments`, `unclosed_positions` and a per-pair copy besides the five DEC-10 fields.
- `reevaluate VARIANT` takes the variant number and refuses an ambiguous number or a variant without a live run. A re-evaluation that stops before the horizon stays `in_progress` with no verdict.
- Exclusion hours are the hour-aligned instants in `[max(paired_at, starts_at), min(delisting, horizon end))`, so a pair paired exactly on the hour counts that hour.

## Canonical Design Synchronization
Updated: `docs/product/prd.md` (PD-023, FR-015, FR-017, BR-003), `docs/design/domain.md`, `docs/design/data/schema.dbml`, `docs/design/ux/flows.mmd`, `docs/design/architecture/quality-attributes.md`, `docs/design/review.md` (F-013 resolved), `README.md`. Not touched: ADRs, `architecture.dsl`, ingestion artifacts, `docs/spec/manifest.yaml`.

## Blockers
None.

## Independent Verification Readiness
Ready. VM items not done here: deploy, live-run measurements without ingestion loss, partial re-evaluation and its run time (ASM-2), and after about 2026-12-07 the verdict of a re-evaluation of variant 1.

## Red evidence (tests written first, run before the code)
- Pure level, crossing, distance and verdict rules: `uv run pytest tests/test_liquidation_math.py tests/test_verdict_rules.py` gave 2 collection errors, `ModuleNotFoundError: No module named 'polyquack.evaluation.verdict'` (and `.liquidation`).
- Measurement, liquidation, funding price, deferral: `tests/test_basis_liquidation.py` failed with `sqlite3.OperationalError: no such table: position_measurement` (first failure at `tests/test_basis_liquidation.py:65`; the last lines of the full run listed the deferral, duplicate-row and close-at-decision tests as FAILED).
- Re-evaluation, horizon, exclusion, verdict, CLI: `tests/test_reevaluation.py` failed at collection with `ImportError: cannot import name 'ReevaluationError' from 'polyquack.evaluation.runner'`.
- Migration: both new `test_migration.py` tests failed (`StopIteration` looking for the `loss` column).
- Extended `future_data_violations`: the existing `test_ac8_funding_accrues_*`, `test_ac9_*` and `test_ac10_a_deferred_pair_*` failed on the missing table.
- DEC-2: after the implementation, 5 M03 funding tests failed because the world had no price readings (payments are no longer rate x notional); fixed by seeding prices and the new amount, see Deviations.
- Test gaps found by the mutations below and closed with a new test each: latest price in the window, Hyperliquid-only funding gap, Hyperliquid-only snapshot gap, a variant that has not run (DEC-13), an independent basis check in the liquidation world. Their red state is the surviving mutation.

## Manual mutations (applied one at a time, restored byte for byte, source diff checked after)
All killed: DEC-7 level sign, maintenance margin term, crossing edge (`<=`), crossing direction, distance sign (`test_liquidation_math.py`); DEC-3 loss (`test_ac2_a_long_leg_*`); DEC-4 no close of the uncovered leg (`test_ac2_*`), no retry at a later minute (`test_dec4_an_uncovered_leg_stays_open_*`); DEC-2 price per platform and window 59/61 minutes and latest-not-oldest (`test_r3_*`); R-3 leg end (`test_ac2_*`); DEC-8 basis sign and change (`test_dec8_*`); DEC-9 no horizon close (`test_r5_*`); DEC-10 basis sign, fees sign, liquidations sign, liquidated leg given a basis effect (`test_dec10_*`); DEC-11 collateral not the maximum (`test_tst016_*`), annual formula 360 (`test_br003_*`), collateral amount (`test_r5_*`); DEC-12 either platform for funding and for snapshots (`test_tst015_*_only_on_hyperliquid_*`), 5% and 10% strict edges (`test_dec12_exactly_*`), window start and end (`test_tst015_*_own_period_*`, `*_until_it_is_delisted`); DEC-5 `>=` edge (`test_dec5_*`), no-positions path (`test_r6_*`); DEC-13 count (`test_dec13_*`).
The first pass left 3 survivors (latest price, Hyperliquid-only funding gap, Hyperliquid-only snapshot gap) and the DEC-13 and liquidated-leg-basis checks were too weak; a test was added for each and the mutations rerun and killed.

## Checks (final run)
- `uv run mypy --strict src tests`: Success, no issues in 49 source files.
- `uv run ruff check src tests`: All checks passed. `uv run ruff format --check src tests`: 49 files already formatted.
- `uv run pytest`: 270 tests, all passed (no failure marker; the slowest is the 100-pair concurrency test at 10 s, the re-evaluation tests take 4 s each at most).
- `gitleaks detect --no-git --source . --redact --no-banner`: no leaks found.

## Migration check
A database built from the M03 schema (`git show cbd6299:src/polyquack/storage/schema.sql`) with a run, a position, a trade and a payment was opened with the new code and `evaluate` ran twice: `paper_trade` gained `loss` once, the trade row kept its values (`loss` null), the payment and run rows stayed, and `position_measurement`, `excluded_pair` and `verdict` were created. `tests/test_migration.py` covers the same on an embedded M03 shape and on a fresh database.

## Local timing (ASM-2 is judged on the VM)
Synthetic world: 38 pairs, 28 days, a book snapshot and price reading per pair, platform and minute, funding hourly, positions opening and closing through the period (240 positions, about 1.02 million measurements, about 34,000 payments). `reevaluate` took 89 s, a second one 77 s (an earlier run of the same script: 121 s). Seeding took 43 s. Not measured: concurrent ingestion writers.

## Correction Rounds

### Round 1 — after verification pass 1 (2026-11-11)
Findings and decisions: F-1, F-2, F-3 (defects); F-4 «No, bloquear», F-5/F-8 «No abrir + reintentar», F-6 «Desde el despliegue» (author decisions); F-7 accepted unchanged; F-9 stays for the VM session.

Changes:
- F-1 (`verdict.py`): `finish_run` first drops pairs whose expected period `[max(paired_at, starts_at), min(delisting, horizon end))` is empty (paired after the horizon, delisted before the start); they are neither excluded nor kept, so `not_qualifiable` is no longer masked and pairs created after the horizon cannot change the verdict.
- F-2 (`verdict.py`): "no positions" is decided by whether the non-excluded pairs have any position, not by collateral; `max_collateral` counts a position that opens and closes at the same instant. A zero-collateral run with positions cannot occur now (each position commits `2 x notional / leverage`).
- F-4/F-8 (`runner.py`): `_decide` passes `may_open` to `_plan`; it is false at the last decision instant and while the pair has a `leg_liquidated` position, turning an open into hold and a reverse into a close.
- F-5 (`runner.py`): `_close_at_horizon` tries the close at the last instant; if it cannot fill and the clock has reached the horizon end, the minute step retries every minute from that instant (DEC-4 rule, the step now takes `close_from_ms` and tries to close all alive legs from there); funding is accrued to the horizon end for legs still open; a position still open is reported in `unclosed_positions`, whose uncredited count now runs to the horizon end.
- F-6 (`runner.py`, `schema.sql`, `migration.py`): new `run.measured_from` (added to an existing database by `add_missing_columns`). Runs created by the new code store their start; a run stored earlier gets, at its first processing, the minute after its latest decision (its start if none), and positions are measured from `max(opened_at, measured_from)`. Re-evaluations keep measuring from each opening.
- Docs: `domain.md`, `schema.dbml`, `flows.mmd` describe the rules above.

Red evidence (tests written first, run before the code):
- `test_verdict_rules.py::test_f2_a_position_that_opens_and_closes_at_the_same_instant_still_commits`: `assert 0.0 == 1000.0` for `max_collateral([(5, 5, 1000.0)])`.
- `test_reevaluation.py::test_f1_a_pair_paired_after_the_horizon_*` and `test_f1_a_pair_delisted_before_the_run_starts_*`: `assert 'complete' == 'not_qualifiable'`.
- `test_f2_a_position_that_ends_in_its_opening_minute_*`: `assert 'no positions' is None`.
- `test_f8_an_open_signal_at_the_last_decision_instant_becomes_hold`: `assert ('open',) == ('hold',)`.
- `test_f5_a_horizon_close_that_cannot_fill_is_retried_*`: position `open` instead of `closed` at the retry minute; `test_f5_f3_an_uncovered_leg_is_closed_after_the_last_instant_*`: closed at the wrong minute (the gap first left a snapshot inside the 120 s age rule; corrected to start 3 minutes before the crash).
- `test_basis_liquidation.py::test_f4_*`: decisions `['open', 'no_action', ...]` instead of hold; `test_f6_*`: `no such column: measured_from`.
- `test_f3_the_basis_change_stays_against_the_first_basis_*` and `test_f3_an_uncovered_leg_is_not_liquidated_again_*` passed on the existing code; they are the F-3 assertions and their value is shown by the mutants below.

Mutants (applied one at a time, restored byte for byte, source checked for leftovers):
- M12 baseline = latest stored basis: killed by `test_f3_the_basis_change_stays_against_the_first_basis_across_hour_chunks`.
- M14 ended leg treated as alive again: killed by `test_f3_an_uncovered_leg_is_not_liquidated_again_and_has_no_distance_in_later_chunks`.
- M32 horizon skips uncovered legs: killed by `test_f5_f3_an_uncovered_leg_is_closed_after_the_last_instant_by_the_horizon_retry`.
- Also killed: no block beside an uncovered leg (`test_f4_*`), open allowed at the last instant (`test_f8_*`), measure from opening (`test_f6_*`), no empty-period filter (`test_f1_*`), no zero-length commitment (`test_f2_a_position_that_opens_and_closes_*`).
- Equivalent after the fix: "collateral == 0 means no positions" survives because collateral is zero only when there are no positions; the F-2 world test is killed by dropping the zero-length commitment instead.

Checks (full, final): `uv run mypy --strict src tests` Success (49 files); `uv run ruff check src tests` All checks passed; `uv run ruff format --check src tests` 49 files already formatted; `uv run pytest` 281 tests, all passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found. Real M03-schema database migration rerun: `loss` and `measured_from` added, rows kept.

Diff range: `git diff cbd6299` (15 tracked files, +1034/-90 at this point) plus the untracked `src/polyquack/evaluation/{liquidation,migration,verdict}.py` and `tests/test_{basis_liquidation,liquidation_math,reevaluation,verdict_rules}.py`.

Not re-measured: the ASM-2 local timing (the per-minute retry for an uncovered leg runs one snapshot read per minute, only while a leg is uncovered).

### Round 2 — after verification pass 2 (2026-11-11)
Findings: F-10 (defect): a lock-deferred close at the horizon did not block the accrual to the horizon end, so payments after the close that the next run records could be credited. F-11 (defects): surviving mutants N6, N11, N12, N14. F-12 is the author's decision and was not touched.

Changes:
- F-10 (`runner.py`): `_close_at_horizon` keeps a `blocked` set of pairs whose close was deferred (at the last instant or in the minute retry, which now returns False on a lock) and passes it to the accrual to the horizon end, the same rule as the hourly loop.
- F-11: tests only. `test_n6_*` (a reverse signal at the last instant becomes a close and opens nothing; `_without_opening` turns open into hold and reverse into close, which also covers the uncovered-leg case where no held position can exist), `test_n11_*` (a leg still open after the last instant is credited the payment at the horizon end), `test_n12_*` (the uncredited count includes a payment between the last instant and the horizon end), and in `test_migration.py` the embedded M03 shape now has a `run` table with a row and `test_m04_an_m03_run_gains_the_measured_from_column_once_and_keeps_its_row` (two `evaluate` calls, one column, row kept).

Red evidence: `test_f10_a_deferred_horizon_close_blocks_the_accrual_past_the_close_that_comes_next` failed before the fix with `assert 2 == 0` (two payments after `closed_at`; deferred 1 then 0). The N-tests passed on the existing code; their value is the mutants.

Mutants (one at a time, restored byte for byte; source checked): N6 reverse stays a reverse, killed by `test_n6_a_reverse_signal_at_the_last_instant_*`; N11 no accrual to the horizon end, killed by `test_n11_*`; N12 uncredited count to the last instant, killed by `test_n12_*`; N14 no `measured_from` migration, killed by `test_migration.py` (the existing loss test and the new run test fail on the missing column); F-10 deferred close does not block, killed by `test_f10_*`.

Checks (full, final): `uv run mypy --strict src tests` Success (49 files); `uv run ruff check src tests` All checks passed; `uv run ruff format --check src tests` 49 files already formatted; `uv run pytest` 287 tests, all passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Diff range: `git diff cbd6299` (15 tracked files, +1064/-90) plus the untracked `src/polyquack/evaluation/{liquidation,migration,verdict}.py` and `tests/test_{basis_liquidation,liquidation_math,reevaluation,verdict_rules}.py`.

### Round 3 — after verification pass 3 (2026-11-11)
Finding: F-13 (defect): a lock interrupting the minute-by-minute horizon retry was untested; mutant F10c (`_retry_horizon_close` reporting success after a lock) survived.

Change: one test, `test_f13_a_lock_in_the_minute_retry_blocks_the_accrual_past_the_close_that_comes_next`, modelled on the F-10 test. Both books are missing from hour 669 until ten minutes after the last decision instant, so the close at the last instant cannot fill; one `database is locked` is injected into the trade insert of the retry minute; then `evaluate(NOW)` and `evaluate(NOW + 1 min)`. It asserts one deferral then none, the position closed at the retry minute, no payment with `source_time` after `closed_at`, and the run `complete`. No source change: the test passed on the existing code, so no bug was revealed.

Mutant F10c (`return False` after the deferral replaced by `return True`): the test fails with `assert 2 == 0` (two payments after `closed_at`); source restored byte for byte (checked with `cmp` against a copy).

Checks (full, final): `uv run mypy --strict src tests` Success (49 files); `uv run ruff check src tests` All checks passed; `uv run ruff format --check src tests` 49 files already formatted; `uv run pytest` 288 tests, all passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Diff range: `git diff cbd6299` (15 tracked files, +1064/-90, the source unchanged since Round 2) plus the untracked `src/polyquack/evaluation/{liquidation,migration,verdict}.py` and `tests/test_{basis_liquidation,liquidation_math,reevaluation,verdict_rules}.py`.
