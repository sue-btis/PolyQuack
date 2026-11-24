# Snapshot index and storage capacity Verification

Verdict: Pass
Acceptance: Accepted by the author, 2026-11-23, «Acepto» (before/after numbers in `vm-qa-log.md`)
Verified by: reviewer agent, independent session (medium); Round 1 follow-up by the main session
Open limitations: None

Size: medium
Reliability: strict

## Pass History
- Pass 1 (2026-11-19, reviewer agent): Fail — F-1 open.
- Round 1 (2026-11-19, main session): F-1 fixed (`ADR-002-storage.md:65`, `audit.md` options table: 3.4 → 3.7 MB/day). Doc-only; no code or test changed since Pass 1.
- Pass 2 (2026-11-19, main session follow-up): Pass for the repository; AC-6 and AC-7 pending on the VM.
- VM QA (2026-11-20, main session from the author's outputs): AC-6 Pass; AC-7 Pass (size per day measured 2026-11-23: ingestion 119.4 MB/day, of which the index 4.1; ADR-002 updated from 3.7 to the measured 4.1); ASM-2 stop condition fired and was resolved by the author's decision F-2.

## Baseline
| Field | Value |
|---|---|
| Repository | `Polyquack-storage` (worktree), branch `fix/snapshot-source-time-index/josueDev` |
| Declared base | `24b5532` |
| Verified head / working tree | HEAD `24b5532` + uncommitted working tree |
| Untracked before edits | None (working tree clean at `24b5532`) |
| Diff range | `git diff 24b5532` (`ADR-002-storage.md`, `schema.dbml`, `schema.sql`, `tests/test_migration.py`, `tests/test_readings.py`) + untracked change folder |
| Verification date | 2026-11-19 |

## Deviations
- None. AC-3's test lives in `tests/test_migration.py`, which the spec's Change Surface allows.

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | defect | The ADR-002 amendment said the index adds about 3.4 MB/day; the audit's measurements give about 3.7 (56.7 MB over 1,669,923 rows / 109,440 rows per day = 15.26 days) | `ADR-002-storage.md:65`; derived totals (about 43 GB/yr at 38 pairs, about 113–114 at 100, about 565–570 days, about 13 months to 50 GB) still hold within "about" | Fixed (Round 1) |
| F-2 | decision | ASM-2 did not hold: 153 `(instrument_id, source_time)` groups have more than one snapshot. With ties the old scan returned the earliest minute and the indexed query returns the latest (insertion order) | `vm-qa-log.md` "Ties on `source_time`": every tied group has identical levels; no stored trade used a tied snapshot; local SQLite 3.50.4 check of both orders | Accepted by the author, 2026-11-20, «Aceptar la del índice»: on a tie the latest minute wins; same price, only `snapshot_minute` can differ; deterministic for NFR-007 as long as snapshots are inserted in minute order, which no code path breaks today |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| R-1 / AC-1 | `schema.sql` `CREATE INDEX IF NOT EXISTS book_snapshot_instrument_source_time ON book_snapshot (instrument_id, source_time)`; `tests/test_readings.py` `test_the_snapshot_lookup_seeks_the_source_time_index_without_sorting` captures `Reader.snapshot`'s real query with `set_trace_callback` and checks its plan | Passes; fails with the index line reversed, showing the VM's old plan (`sqlite_autoindex_book_snapshot_1 (instrument_id=?)` + `USE TEMP B-TREE FOR ORDER BY`) | Pass |
| R-2 / AC-2 | `readings.py` untouched; existing snapshot tests unmodified | Full `uv run pytest` passes | Pass |
| R-3 / AC-3 | `tests/test_migration.py` `test_reopening_a_database_without_the_snapshot_source_time_index_creates_it` | Passes; fails with the index line reversed | Pass |
| R-4 / AC-4 | `schema.dbml` `book_snapshot` indexes list the named index | Read | Pass |
| R-5 / AC-5 | ADR-002 "Amendment: measured capacity" with measured MB/day, GB/year, runway, 50 GB trigger kept, author's words | Arithmetic rechecked against `audit.md` | Pass (after F-1) |
| R-6 / AC-6 | Deploy order in the spec | `vm-qa-log.md` "Deploy": only the restart's gaps (2 minutes per instrument); backup not taken (deviation) | Pass |
| R-7 / AC-7 | `vm-qa-log.md` | Live `reevaluate 1` 4m40s for 10070 decisions (was 12m26s for 7258); plan uses the index; index 68.3 MB; tie count 153 (F-2); ingestion 115.3 → 119.4 MB/day by `dbstat` | Pass |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | "Success: no issues found in 49 source files" |
| `uv run ruff check src tests` | Pass | lint | "All checks passed!" |
| `uv run ruff format --check src tests` | Pass | format | "49 files already formatted" |
| `uv run pytest` | Pass | full suite, AC-1/2/3 | 290 passed |
| `gitleaks detect --no-git --source . --redact --no-banner` | Pass | secrets | "no leaks found" |
| Mutation: reverse only the `schema.sql` hunk, run the two new tests | Both fail | AC-1, AC-3 sensitivity | restored byte-identical afterwards |

## QA
1. VM deploy order (backup, stop timer, `uv sync --no-dev`, restart ingestion, confirm index, start timer) and gap check
Expected: only the restart's `gap` rows
Actual: book 20:32–20:34 and price 20:33–20:35, 152 rows each, `not_collected`; the index build took about 2 min 43 s inside the ingestion start-up; backup not taken
2. Live `time polyquack reevaluate 1`, plan, index size, tie count, MB/day after, in `vm-qa-log.md`
Expected: within the ASM-1 bound; tie count 0
Actual: 4m40s for 10070 decisions (bound about 5.9 min); no gap during it; index plan; 68.3 MB; tie count 153 (F-2, accepted); ingestion 119.4 MB/day (index 4.1)

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| single writer | schema.sql, test_readings.py / test_migration.py, schema.dbml, ADR-002-storage.md, change folder | exactly those | Yes |

Do-not-touch respected: `readings.py`, `ingestion/book.py`, triggers, `variant` rows, M04 folder unchanged.

## Contract / Integration Review
- The index is additive with `IF NOT EXISTS`, the same pattern as `gap_instrument_kind_start`; no column, trigger or query-text change; rollback is `DROP INDEX`.
- `schema.sql` runs on every writable `Database` open (`db.py:62-63`); read-only opens skip it.
- No lockfile or project changes.

## Quality Metrics
- Coverage: no tool configured; the only production change is one DDL statement run by every test that opens a `Database`.
- Mutation: manual, 1 written / 1 killed.
- Flaky/skipped tests affecting scope: none observed.

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `docs/design/data/schema.dbml` | index on `book_snapshot` | present, named | Pass |
| `docs/design/architecture/adr/ADR-002-storage.md` | capacity amendment | present | Pass (after F-1) |
| M01 DEC-1, NFR-007, `quality-attributes.md` | preserved | untouched | Pass |

## Merge Risk
Low. One additive index with two tests that fail without it; the live-database risk (about 15 s build under the write lock) is handled by the deploy order, which VM QA still has to exercise.
