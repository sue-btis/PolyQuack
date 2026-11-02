# M02 — All pairs are ingested 24/7 and recover on their own — Verification

Verdict: Pass
Acceptance: Pending — F-12: the VM QA in `vm-qa-log.md` (ASM-2, ASM-3, AC-7's 7-day figures, database size, real systemd restart on a target change)
Verified by: Independent reviewer agent, separate from the implementer and the integration owner (medium)
Open limitations: None

Size: medium
Reliability: strict

## Pass History
- Pass 1 (2026-11-02): Fail — defects F-1 to F-4 open; decisions F-5 to F-11 pending.
- Pass 2 (2026-11-02): Pass — F-1 to F-4 fixed in Round 1; F-12 recorded; decisions F-5 to F-12 pending.
- Pass 3 (2026-11-02): Fail — F-5 and F-6 fixed in Round 2; F-7, F-8, F-10, F-11 accepted; F-9 decided; F-13 (extended SQLite codes misclassified, same class as F-9) open.
- Pass 4 (2026-11-02): Pass — F-13 fixed in Round 3; only F-12 pending.

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack`, branch `feat/all-pairs-ingestion/josueDev` |
| Declared base | `3b45b41` (HEAD; nothing committed on top) |
| Verified head / working tree | `3b45b41` plus uncommitted changes: 19 tracked files modified (+844/−137), 9 new files outside the change folder |
| Untracked before edits | `docs/changes/2026-10-30-M02-all-pairs-ingestion/`; `groma/` is locally excluded and not part of the change |
| Diff range | `git diff 3b45b41` + `git ls-files --others --exclude-standard` minus the change folder |
| Pass 4 delta | `src/polyquack/ingestion/service.py` (`_is_lock_contention`), `tests/test_concurrency.py`, `docs/design/review.md` (F-010 `Accepted by`), `execution.md` |
| Verification date | 2026-11-02 |

## Deviations
- The implementer's Deviations 1–7 are in `execution.md`. Deviation 1 (existing tests edited) is a contract change the spec records. Deviations 2 and 3 were changed by the author's decisions (F-5, F-6). Deviations 4 and 6 were accepted (F-7, F-11). Deviations 5 and 7 change no behaviour; F-010 is `RESOLVED` with its `Accepted by`.

## Correction Rounds
- Round 1 (`execution.md`): F-1 to F-4, plus the stale TST-9 line.
- Round 2 (`execution.md`): the author's decisions on F-9, F-6 and F-5; the main session recorded the ADR-002 "Accepted by" and set F-010 `RESOLVED`.
- Round 3 (`execution.md`, the last allowed): F-13 fixed with two new tests in `tests/test_concurrency.py`; F-010's `Accepted by` field filled in `review.md`. No defect remains.

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | defect | Missing behavior assertion: DEC-11 boundary (the history response holds only earlier payments) | `tests/test_recovery.py:185-202`; mutant M1 killed | Fixed (Round 1) |
| F-2 | defect | Missing behavior assertion: DEC-3 settlement guard (lookup row without `settlement`) | `tests/test_lifecycle.py:95-109`; mutant M27 killed | Fixed (Round 1) |
| F-3 | defect | Canonical design not synchronized: the DEC-10 note was missing from `schema.dbml` | `docs/design/data/schema.dbml:60` | Fixed (Round 1) |
| F-4 | defect | Canonical design not synchronized: the F-001 flow implied a backfill on every reconnection | `docs/design/ux/flows.mmd:4-8` | Fixed (Round 1) |
| F-5 | decision | Hyperliquid max leverage falls back to the row's `maxLeverage` when no margin table is listed; now documented | `schema.dbml:45`; `platforms.py:336-337` | Fixed (Round 2) |
| F-6 | decision | Filter assets without a target pair were not reported; now warned per asset | `service.py` `_load_targets`; `tests/test_lifecycle.py:149-165`; mutants N5, N6 killed | Fixed (Round 2) |
| F-7 | decision | One restart on the first M02 start over an M01 database | `service.py` `_load_targets` / `_check_targets` | Accepted — the author, 2026-11-02, «Sí, las acepto» |
| F-8 | decision | Repeated backfill load for instruments whose history starts after the floor | `service.py` `backfill_funding` | Accepted — the author, 2026-11-02, «Sí, las acepto» |
| F-9 | decision | Exception scope: only lock contention (BUSY/LOCKED) is tolerated; other `sqlite3.OperationalError`s propagate | `service.py` `_guarded`, `_fetch_history`; `tests/test_concurrency.py:74-85`, `:116-129`; mutants N1, N4, N9 killed | Fixed (Round 2; completed by the F-13 fix in Round 3) |
| F-10 | decision | TST-9 timing bound is `max < 30 s`; the mean stays under 1 s | `tests/test_concurrency.py` TST-9 test | Accepted — the author, 2026-11-02, «Sí, las acepto» |
| F-11 | decision | `status` and `completeness` also list delisted pairs | `status.py`, `completeness.py` | Accepted — the author, 2026-11-02, «Sí, las acepto» |
| F-12 | decision | Evidence assigned elsewhere: the VM QA (ASM-2, ASM-3, AC-7's 7-day figures, database size, real systemd restart on a target change) belongs to `vm-qa-log.md` in a later session | spec "Quality Obligations", "Done When", "Triggered Artifacts" | Pending |
| F-13 | defect | Wrong error classification: extended BUSY/LOCKED result codes were treated as fatal | `service.py:36-39` uses `code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)` (`&` binds tighter than `in`); parametrized `test_lock_contention_is_classified_by_the_primary_result_code` (`tests/test_concurrency.py:95-113`): 5, 6, 261, 517, 773, 262 → True; 1, 10, 1555, missing → False; `test_a_non_lock_error_while_writing_history_propagates` (`:116-129`); N4, N7, N8 killed | Fixed (Round 3) |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| R-1 / AC-1 | `db.targets()`; per-asset filter warning | TST-9 passes; N5, N6 killed. VM part: F-12 | Pass (code) |
| R-2 / AC-2 | lifecycle and settlement | M11, M12, M13, M21, M23, M27 killed | Pass |
| R-3 / AC-3 | `TargetsChanged` | M10 killed | Pass |
| R-4 / AC-4 | backfill paging | M4, M5, M6, M7, M9 killed; M8 equivalent | Pass |
| R-5 / AC-5 | recovery, DEC-11 | M1, M2, M3, M24 killed | Pass |
| R-6 / AC-6 | parameters and fees | M14, M15, M16, M28 killed | Pass |
| R-7 / AC-7 | `completeness` | M22 killed; 7-day figures: F-12 | Pass (code) |
| R-8 / AC-8 | batched `_pending` | M19 killed | Pass |
| R-9 / AC-9 | migration | M17, M18 killed; full-M01-schema migration check (pass 1) | Pass |
| R-10 / AC-10 | `render_status` | test passes (F-11 accepted) | Pass |
| R-11 / AC-11 | `_guarded`; lock contention by primary code | R-11 tests on a real file; N1, N3, N7, N8, N9 killed | Pass |
| DEC-6 | lock-contended write logged, no row; other errors propagate | as R-11, plus N4 killed on the history path | Pass |
| Other DEC-* and TST-6 to TST-9 | as in passes 1–2 | unchanged code | Pass |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | `Success: no issues found in 29 source files` |
| `uv run ruff check src tests` | Pass | lint | `All checks passed!` |
| `uv run ruff format --check src tests` | Pass | format | `29 files already formatted` |
| `uv run pytest` (run 1) | Pass | all | `96 passed in 36.90s` |
| `uv run pytest` (run 2) | Pass | all | `96 passed in 24.92s` |
| `gitleaks detect --no-git --source . --redact --no-banner` | Pass | secrets | `no leaks found` |
| Mutants N1, N4, N7, N8, N9 (full suite each) | 5 killed | F-13 / F-9 class | N4 by `test_a_non_lock_error_while_writing_history_propagates`; N7 by `[6-True]`; N8 (no `& 0xFF`) by `[261-True]`; N9 and N1 by `test_a_write_error_that_is_not_lock_contention_propagates_out_of_the_minute_close` |
| Tree integrity after mutations | Pass | no edits left | `sha256sum -c` over 29 src/tests `.py` files OK; `git diff 3b45b41 --stat`: 19 files, +844/−137, unchanged |

## QA
1. Deploy M02 on the VM over the M01 database; read the first-run log. Expected: one restart (F-7); filter warnings if a filter is set; 38 `book::` and 38 `l2Book` subscriptions accepted (ASM-2); backfill with no blocks (ASM-3). Actual: not run here (F-12).
2. `polyquack completeness` after 7 days. Expected: at least 99% of hours with funding and 95% of minutes with a snapshot, per pair. Actual: not run here (F-12).
3. `polyquack status`, database size, dated lifecycle, parameter and fee rows. Actual: not run here (F-12).

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| Implementer, Rounds 1–3, plus the main session's document edits | Change Surface of the spec; each round limited to its findings | Round 3: `service.py` (`_is_lock_contention` only), `tests/test_concurrency.py`, `review.md` (F-010 `Accepted by`), `execution.md` | Yes |

## Contract / Integration Review
- Round 3 changes only which errors count as lock contention; interfaces, schema and triggers unchanged.
- Process contract: lock contention (any BUSY or LOCKED variant) is logged and leaves no row, and the next tick records a `not_collected` gap; any other database error ends the process with a non-zero exit and systemd restarts it (`Restart=always`). Matches the author's F-9 decision and the ADR-002 amendment.
- ADR-002: amendment `Status: Accepted`, `Accepted by: the author, 2026-11-02, «Sí, Accepted by»`; the Stop Condition is satisfied.
- `review.md`: F-010 `RESOLVED` with `Accepted by: the author, 2026-11-02, «Sí, Accepted by» (ADR-002 amendment)`; F-011 stays open for its non-fee parts.
- Generated files, migrations, project files, lockfile unchanged since pass 1. Other repositories: not applicable.

## Quality Metrics
- Changed-line and branch coverage: no tool installed.
- Mutation (manual, cumulative): 39 written, 38 killed, 1 equivalent (M8), 0 survivors.
- Flaky or skipped tests: none in 9 full runs across 4 passes; TST-9 bound accepted (F-10).

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|
| L-1 | F-7 | the author, «Sí, las acepto» (option selected in the main session) | 2026-11-02 | none |
| L-2 | F-8 | the author, «Sí, las acepto» (option selected in the main session) | 2026-11-02 | none |
| L-3 | F-10 | the author, «Sí, las acepto» (option selected in the main session) | 2026-11-02 | none |
| L-4 | F-11 | the author, «Sí, las acepto» (option selected in the main session) | 2026-11-02 | none |

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `docs/design/data/schema.dbml` | `fee_schedule.category` and its key; DEC-10, DEC-11, DEC-1, DEC-8 notes; Hyperliquid fallback | all present | Pass |
| `docs/design/domain.md` | pair status derivation, gap transitions, lifecycle signals | present | Pass |
| `ADR-002-storage.md` | two-writer amendment accepted | `Accepted`, with its `Accepted by` line | Pass |
| `docs/design/ux/flows.mmd` | recovery at start and hourly, not on reconnect | as in pass 2 | Pass |
| `docs/design/review.md` | F-010 resolved and accepted; F-011 resolved for fees | as expected | Pass |
| `README.md` | `POLYQUACK_ASSETS`, `completeness` | documented | Pass |
| ADR-001, ADR-003–006, `architecture.dsl`, `quality-attributes.md`, `prd.md`, `manifest.yaml` | preserved | untouched | Pass |

## Merge Risk
Medium

Reason: no defect is open, every non-equivalent mutant of the decision logic is killed, the migration is safe on an M01 database, and all gates pass. It stays medium because the deployed behaviour is unverified (F-12: channel capacity, backfill pace, 7-day completeness, restart on a target change) and the Polymarket response shape for a settled instrument has never been observed.
