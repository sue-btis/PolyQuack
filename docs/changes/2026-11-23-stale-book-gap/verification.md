# Stale book becomes a snapshot gap Verification

Verdict: Pass
Acceptance: Accepted — author, 2026-11-23, «Acepto, commitea»
Verified by: Self-verification (quick + lean)
Open limitations: None

Size: quick
Reliability: lean

## Pass History
- Pass 1 (2026-11-23): Pass — F-1 decision accepted by the author.

## Baseline
| Field | Value |
|---|---|
| Repository | sue-btis/PolyQuack, sibling worktree `Polyquack-stale-book-gap` |
| Declared base | `origin/dev` cbd6299 |
| Verified head / working tree | branch `fix/stale-book-gap/josueDev` at cbd6299, uncommitted |
| Untracked before edits | None (fresh worktree) |
| Diff range | `git diff cbd6299` + `docs/changes/2026-11-23-stale-book-gap/` |
| Verification date | 2026-11-23 |

## Deviations
- Change surface: the spec expected only `tests/test_service.py`; `tests/conftest.py` and `tests/test_concurrency.py` also changed (see F-1).

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | decision | Fixture realism: four existing tests closed later minutes with the book fixed at the service clock time, so after the fix they got `stale_book` gaps. They now refresh the book with `fill_books` before those closes; no assertion was changed or removed. Tests: `test_elapsed_minutes_missed_by_a_stopped_service_become_gaps`, `test_status_shows_latest_readings_gaps_and_unpaired_instruments`, `test_elapsed_intervals_of_an_instrument_are_written_in_one_transaction`, `test_one_simulated_hour_of_100_pairs_closes_every_minute_and_the_hour` | `git diff cbd6299 -- tests/conftest.py tests/test_concurrency.py tests/test_service.py` | Accepted |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| AC-1 | `service.py:222` age check takes the gap path with `stale_book` | `test_book_older_than_120_s_at_minute_end_is_a_stale_book_gap` failed on cbd6299 before the fix, passes after | Pass |
| AC-2 | strict `>` against `STALE_BOOK_MS = 120_000` | `test_book_exactly_120_s_old_at_minute_end_is_still_a_snapshot`; mutant `>=` killed | Pass |
| AC-3 | `None` → invalid cause, empty side → `empty_book`, fresh → snapshot | existing tests in `tests/test_service.py`, `tests/test_book.py`, `tests/test_recovery.py` pass | Pass |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | no issues in 42 source files |
| `uv run ruff check src tests` | Pass | lint | All checks passed |
| `uv run ruff format --check src tests` | Pass | format | 42 files already formatted |
| `uv run pytest` | Pass | suite | 206 passed |
| `gitleaks git` / `gitleaks dir .` | Pass | secrets | no leaks found |

## QA
1. After deploy, on a future Polymarket stall: `journalctl -u polyquack-ingestion | grep stale_book`.
Expected: `snapshot gap ... (stale_book)` lines for minutes more than 120 s after the last book message.
Actual: not run — a stall cannot be reproduced on demand.

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| single writer | `service.py`, `tests/test_service.py`, `domain.md`, `schema.dbml` | the same plus `tests/conftest.py`, `tests/test_concurrency.py` (F-1) | Partial |

## Contract / Integration Review
- Frozen contract fidelity: `gap.cause` gains `stale_book` (free text); only `status.py:66` reads it, as display. No schema change.
- Integration gate: `Reader.snapshot` selects by `source_time` within 120 s of the decision instant; dropped rows are copies of an earlier row with the same `source_time` whenever the book was captured within 120 s of its timestamp.
- Generated/migration/project/lockfile review: none changed.
- Other repositories: not applicable.

## Quality Metrics
- Changed-line coverage: no tool run
- Changed-branch coverage: no tool run
- Mutation: manual: 2 written (`>` → `>=`, check removed) / 2 killed
- Flaky/skipped tests affecting scope: none

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `docs/design/domain.md` | snapshot gap rule mentions `stale_book` | Gap lifecycle paragraph updated | Pass |
| `docs/design/data/schema.dbml` | `gap.cause` note lists `stale_book` | note updated | Pass |

## Merge Risk
Low

Reason:
One guarded branch in the minute close; the evaluator already ignores books older than 120 s, so only completeness and storage change.
