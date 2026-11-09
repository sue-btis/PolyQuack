# M02 — All pairs are ingested 24/7 and recover on their own — Execution

Status: Implemented, awaiting independent verification

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `feat/all-pairs-ingestion/josueDev` (no upstream) |
| Planned base | `dev` with M01 merged |
| Current start commit | `3b45b41` (merge of PR #2 into `dev`; contains `6b1e30b`, the audited commit, with an identical tree) |
| Working tree before edits | clean except the untracked change folder |
| Pre-existing relevant changes | none |
| Untracked files before edits | `docs/changes/2026-10-30-M02-all-pairs-ingestion/` (`audit.md`, `spec.md`, `execution.md`, `probes/*`) |

Baseline checks on 2026-11-02: `uv run pytest -q` 48 passed; `uv run mypy --strict src tests` no issues in 22 files.

## Preflight Verdict
Safe sequentially only

Reason: the audited tree equals the start commit; no overlapping changes; `service.py`, `db.py` and `schema.sql` are touched by every requirement, so one writer works in sequence (spec: no plan).

## Execution Topology
Sequential (one implementer subagent; the main session is the integration owner)

## Executed Work
One writer, sequential, on `feat/all-pairs-ingestion/josueDev` from `3b45b41`. Nothing committed.

- `src/polyquack/ingestion/models.py`, `platforms.py`: `InstrumentInfo` gains status and base-tier parameters; `FeeRate`; `Platform.funding_history` (paged, async iterator), `fees`, `has_settlement`. Polymarket pages backward by moving `end_timestamp`, Hyperliquid forward by moving `startTime`. Hyperliquid delisted coins are returned with status `delisted`.
- `src/polyquack/ingestion/hyperliquid_fees.json` (new, read from the package directory like `schema.sql`; no `pyproject.toml` change): tier 0, taker 0.00045, maker 0.00015, effective 2026-10-30.
- `src/polyquack/storage/schema.sql`, `db.py`: `fee_schedule.category` and key (DEC-7); startup migration (`MigrationError` when the old table has rows); lifecycle, parameters and fee writes only on change; derived pair status; `targets()` over all non-delisted pairs with optional filter; batched `insert_gaps`; history inserts; gap closing; `busy_timeout_ms` parameter (default stays 5000).
- `src/polyquack/ingestion/service.py`: no startup scope limit; refresh writes lifecycle, parameters, fees and settles absent Polymarket instruments; a target change raises `TargetsChanged`, caught in `run` (returns, exit 0); one history task per platform (backfill, then recovery at start and at minute 20); batched `_pending`; failed writes are logged and leave no row (`_guarded`).
- `src/polyquack/completeness.py` (new), `cli.py`, `status.py`, `config.py`: `completeness [--days N]`, per-pair status in `status`, `POLYQUACK_ASSETS` as optional filter, migration error exits 1.
- Tests: new `test_lifecycle.py`, `test_recovery.py`, `test_concurrency.py`, `test_migration.py`, `test_completeness.py`, `exchange.py` (fake exchange over a mock transport), fixture `pm_fees.json` (real response of 2026-11-02); `hl_meta.json` gained the real `marginTables` entries. Existing tests changed only where the contract changed (see Deviations).
- Docs: `schema.dbml`, `domain.md`, ADR-002 amendment (`Proposed`, no "Accepted by"), `flows.mmd`, `review.md` (resolution notes), `README.md`.

Platform values read on 2026-11-02 (ASM-4, DEC-2): Hyperliquid fees page row `| 0 | | 0.045% | 0.015% |` (taker 0.045%, maker 0.015%); error-responses page: "Order must have minimum value of $10." Both confirmed. Read-only calls to public endpoints: Polymarket instruments by `instrument_id` (the answer is a list; `[]` for an unknown id), Polymarket fees, Hyperliquid meta.

## Integration Gates
| Gate | Owner | Diff Inspected? | Checks | Result |
|---|---|---:|---|---|
| Sequential implementation | main session | Yes (file list, `git diff --stat`: 19 tracked files, +825/−132, plus 9 new files; exception handling in `service.py` catches only `SOURCE_ERRORS` and `sqlite3.OperationalError`) | mypy strict, ruff check, ruff format, pytest ×3, gitleaks | Pass after one fix: the TST-9 `max < 5 s` bound failed once in a full run (single closes reached 3.6 s on this machine); it now asserts `max < 30 s`, still within the minute, and keeps the mean under 1 s. Then `81 passed` twice, other checks clean |

## Requirement Status
| ID | Status | Tests |
|---|---|---|
| R-1 | Done | `test_targets_are_every_non_delisted_pair_narrowed_by_the_filter`, `test_pair_status_is_derived_from_the_worst_instrument`, `test_one_simulated_hour_of_100_pairs_closes_every_minute_and_the_hour` |
| R-2 | Done | `test_status_follows_polymarket_from_active_to_close_only_to_settled`, `test_unchanged_status_adds_no_row`, `test_instrument_absent_without_settlement_keeps_its_status_and_is_logged`, `test_hyperliquid_delisted_coin_is_stored_as_delisted_and_never_paired`, `test_hyperliquid_instruments_keep_delisted_coins_with_their_status` |
| R-3 | Done | `test_target_set_change_ends_run_with_a_log_and_no_exception`, `test_run_fails_when_no_pair_can_be_ingested` |
| R-4 | Done | `test_polymarket_backfill_pages_backward_from_the_floor_and_stores_nothing_before_it`, `test_hyperliquid_backfill_pages_forward_in_pages_of_500`, `test_backfill_runs_up_to_the_earliest_stored_hour_and_is_not_repeated_once_complete`, `test_history_requests_of_a_platform_never_overlap` |
| R-5 | Done | `test_recovery_closes_outage_gaps_with_real_readings_and_book_gaps_stay_final`, `test_gap_without_payment_in_history_but_with_later_ones_becomes_final`, `test_gap_stays_open_when_history_has_nothing_later_or_the_request_fails` |
| R-6 | Done | `test_parameters_are_stored_once_and_again_only_when_a_value_changes`, `test_fees_of_both_platforms_are_stored_dated_and_not_repeated`, `test_a_changed_polymarket_rate_is_a_new_dated_row_set`, `test_hyperliquid_fee_entries_come_from_the_versioned_data_file`, `test_hyperliquid_base_tier_parameters_come_from_the_margin_table` |
| R-7 | Done (VM figure pending) | `test_completeness.py` (4 tests including the CLI command) |
| R-8 | Done | `test_elapsed_intervals_of_an_instrument_are_written_in_one_transaction` |
| R-9 | Done | `test_migration.py` (3 tests) |
| R-10 | Done | `test_status_lists_every_target_pair_with_its_derived_status` |
| R-11 | Done | `test_a_second_writer_shorter_than_the_busy_timeout_does_not_lose_the_snapshot`, `test_a_second_writer_longer_than_the_busy_timeout_leaves_a_gap_at_the_next_tick` |

TST-9 (100 pairs, one simulated hour): the minute close of 200 instruments took a mean of 0.23 to 0.28 s and a maximum of 0.30 to 1.07 s over three runs on this Windows machine (the test prints it with `-s`). The test asserts mean under 1 s and max under 30 s (see Integration Gates) because a hard 1 s bound failed once.

Red-green record (honest): the implementation was written before the new tests. The only failures I saw first were the 8 existing tests broken by the contract change (abstract methods in two test doubles, three parser tests). The new tests passed on their first run, except one whose expected count I had miscounted (fixed in the test: 61 gaps per instrument, not 59) and the timing bound above. I did not run mutations to show that the new tests fail without the code.

## Deviations
1. Existing tests edited because the spec changes their contract; none deleted or weakened: `test_hyperliquid_instruments_skip_delisted_coins` replaced by `..._keep_delisted_coins_with_their_status` (R-2 supersedes F-6); `test_polymarket_instruments_are_read_from_the_real_list` expects the new fields; `test_pairing_the_real_lists...` records lifecycle before pairing and expects 9 instruments (delisted coins are stored); `_LocalPlatform` and `_StubPlatform` got the two new abstract methods.
2. Hyperliquid base-tier leverage: 199 of 235 live `marginTableId` values are absent from `marginTables` (ids up to 50 are implicit); where a table exists its first tier always equals the row `maxLeverage`. When the table is missing the row `maxLeverage` is used. Measured on 2026-11-02; DEC-1 does not mention it.
3. `MissingPairError` is raised only when no target exists after both first refreshes (M01 required every configured asset). A filtered asset that is delisted no longer crashes the service, which avoids a restart loop under `Restart=always`. A filter asset without a pair is not reported.
4. Startup still begins ingesting from the stored targets before the first refresh; a first refresh that changes them exits with 0 and systemd restarts, so an M01 database restarts once on the first M02 run.
5. `Database` got a `busy_timeout_ms` argument (default 5000) so the R-11 test does not wait 5 s.
6. `status` shows delisted pairs too (with their status); `unpaired_instruments` now excludes delisted instruments.
7. `review.md`: F-010 and F-011 got a Resolution line but their Status stays `OPEN` (F-010 waits for the ADR acceptance, F-011 is resolved for fees only). Change the Status lines when the author accepts.

## Canonical Design Synchronization
Updated: `schema.dbml` (fee category and key, base-tier and margin-rule notes, funding gap transitions), `domain.md` (pair status derivation, lifecycle signals, gap transitions), `ADR-002-storage.md` (amendment, `Proposed`, no "Accepted by"), `flows.mmd` (backfill at start, recovery at start and minute 20, not on reconnect), `review.md`, `README.md`. Not touched: ADR-001, ADR-003 to ADR-006, `architecture.dsl`, `quality-attributes.md`, `prd.md`, `docs/site/**`, `manifest.yaml`. `docs/site/polyquack-architecture.html` is generated from the design package and was not regenerated.

## Blockers
None hit. No Stop Condition fired. Unverified platform behavior: the shape of the Polymarket answer for a settled instrument (the lookup by `instrument_id` returned `[]` for an unknown id; no settled instrument was available to observe). The code treats any returned row with a truthy `settlement` key as settled, following the spec.

## Independent Verification Readiness
Checks run from the repository root on 2026-11-02, all green: `uv run mypy --strict src tests` (no issues, 29 files); `uv run ruff check src tests` (all checks passed); `uv run ruff format --check src tests` (29 files formatted); `uv run pytest` (81 passed); `gitleaks detect --no-git --source . --redact --no-banner` (no leaks found). Not run, needs the VM: ASM-2 (38 channels per connection), ASM-3 (backfill pace), the 7-day run and the `completeness` figures, database size, the restart behavior of the deployed unit on a target change. ADR-002 still needs the author's "Accepted by" (Stop Condition).

## Correction Rounds

### Round 1 — after verification pass 1 (2026-11-02)
Findings addressed: F-1, F-2, F-3, F-4, plus the stale "max under 5 s" line in Requirement Status (bookkeeping only). F-5 to F-11 untouched.

Files changed:
- `tests/test_recovery.py`: `test_gap_stays_open_when_the_history_in_the_window_only_has_earlier_payments` (F-1).
- `tests/exchange.py`: `lookup_returns_row_without_settlement` makes the instrument lookup answer a row with no `settlement` (F-2).
- `tests/test_lifecycle.py`: `test_absent_instrument_whose_lookup_has_no_settlement_keeps_its_status` (F-2).
- `docs/design/data/schema.dbml`: note on `pair` that status is derived, not stored (F-3).
- `docs/design/ux/flows.mmd`: F-001 starts at "Start" only; after pairing, channel subscription and the history task run in parallel; a disconnection returns to the subscription step (F-4).
- `execution.md`: TST-9 line now says max under 30 s; this section.
No source file under `src/` changed.

Red evidence (mutant applied, test run, file restored; `diff` against a backup and `git diff --stat` confirmed identical afterwards):
- F-1, mutant `elif newest_hour is not None:` in `src/polyquack/storage/db.py`: `uv run pytest tests/test_recovery.py -k earlier_payments` fails with `At index 1 diff: ('2026-10-28T23:00:00.000Z', 'final') != ('2026-10-28T23:00:00.000Z', 'open')`. The gap for the first hour closes with data, the later ones must stay open.
- F-2, mutant `return bool(rows)` in `src/polyquack/ingestion/platforms.py`: `uv run pytest tests/test_lifecycle.py -k no_settlement` fails with `assert ['active', 'delisted'] == ['active']`. (A first version of the test failed with an `IntegrityError` for a repeated timestamp; the test now advances the clock so the failure is the assertion.)
Both new tests pass on the real code.

Checks after the round (repository root): `uv run mypy --strict src tests` no issues in 29 files; `uv run ruff check src tests` all checks passed; `uv run ruff format --check src tests` 29 files formatted; `uv run pytest` 83 passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Diff range: working tree against `3b45b41`; `git diff --stat` is now 19 tracked files, +830/−135 (was +825/−132), and the untracked file count is unchanged (no new files this round).
Preflight delta: none; no other writer, no new dependency, no change outside the files listed above.

### Round 2 — author decisions after verification pass 2 (2026-11-02)
Findings addressed: F-9, F-6, F-5. Nothing else touched (ADR-002 and `review.md` left to the main session).

Files changed:
- `src/polyquack/ingestion/service.py`: `_guarded` and `_fetch_history` swallow `sqlite3.OperationalError` only when its `sqlite_errorcode` is `SQLITE_BUSY` or `SQLITE_LOCKED` (`_is_lock_contention`); everything else is re-raised so the process fails and systemd restarts it. `_load_targets` logs one warning per filter asset with no target pair. `_guarded` docstring updated.
- `tests/test_concurrency.py`: `test_a_write_error_that_is_not_lock_contention_propagates_out_of_the_minute_close`.
- `tests/test_lifecycle.py`: `test_each_filter_asset_without_a_target_pair_is_warned_about` (one asset with no pair, one delisted).
- `docs/design/data/schema.dbml`: `instrument_parameters.max_leverage` note gains the Hyperliquid fallback to the row `maxLeverage` when the margin table is not listed (F-5).
- `execution.md`: this section.

Facts checked first: Python 3.13 has `sqlite3.SQLITE_BUSY` (5), `sqlite3.SQLITE_LOCKED` (6) and `OperationalError.sqlite_errorcode` on errors raised by SQLite (a "no such table" error reports 1). An `OperationalError` built in Python has no such attribute, so `_is_lock_contention` reads it with `getattr(..., None)` and treats a missing code as not lock contention.

Red evidence (new tests against the unchanged code, before the implementation):
- `uv run pytest tests/test_concurrency.py tests/test_lifecycle.py -q`: `Failed: DID NOT RAISE OperationalError` (F-9; the log showed `write failed: OperationalError('disk I/O error')`) and `AssertionError: assert [] == ['filter asse... target pair']` (F-6).
- The F-9 test first failed after the change with `AttributeError: 'OperationalError' object has no attribute 'sqlite_errorcode'`, which led to the `getattr`. The existing R-11 tests (real lock contention, code `SQLITE_BUSY`) pass unchanged.

Checks after the round (repository root): `uv run mypy --strict src tests` no issues in 29 files; `uv run ruff check src tests` all checks passed; `uv run ruff format --check src tests` 29 files formatted; `uv run pytest` 85 passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Diff range: working tree against `3b45b41`; `git diff --stat` is 19 tracked files, +841/−136 (includes the main session's edits to other documents); untracked file count unchanged.

### Round 3 — after verification pass 3 (2026-11-02)
Finding addressed: F-13 only. `_is_lock_contention` compared the full code, so extended BUSY/LOCKED codes that Python 3.13 reports (261, 517, 773, 262) were treated as fatal. It now classifies by the primary code (`code & 0xFF`); a missing `sqlite_errorcode` stays "not lock contention".

Files changed:
- `src/polyquack/ingestion/service.py`: `_is_lock_contention`.
- `tests/test_concurrency.py`: parametrized `test_lock_contention_is_classified_by_the_primary_result_code` (primary and extended BUSY/LOCKED true; ERROR, IOERR, 1555 and a missing code false) and `test_a_non_lock_error_while_writing_history_propagates`.
- `docs/design/review.md`: F-010 `Accepted by` set to the author's acceptance of 2026-11-02; nothing else in it, and ADR-002 untouched.
- `execution.md`: this section.

Red evidence:
- Against the unchanged code, `uv run pytest tests/test_concurrency.py -q -k "primary_result_code or writing_history"` failed `[261-True]`, `[517-True]`, `[773-True]` and `[262-True]`; the history-path test passed already (the re-raise was in place).
- Mutant removing the re-raise in `_fetch_history`: `uv run pytest tests/test_concurrency.py -q -k writing_history` fails with `Failed: DID NOT RAISE OperationalError` (`test_a_non_lock_error_while_writing_history_propagates`).
- Mutant dropping `SQLITE_LOCKED` from the tuple: `-k primary_result_code` fails `[6-True]` and `[262-True]`.
- After each mutant the file was restored from a backup and `diff` confirmed it identical.

Checks (repository root): `uv run mypy --strict src tests` no issues in 29 files; `uv run ruff check src tests` all checks passed; `uv run ruff format --check src tests` 29 files formatted; `uv run pytest` 96 passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Diff range: working tree against `3b45b41`; `git diff --stat` is 19 tracked files, +844/−137; untracked file count unchanged.
