# Snapshot index and storage capacity

Status: Ready for implementation
Approved by: the author, 2026-11-19, «ok aprobado el spec»
Size: medium
Reliability: strict
Implementation effort: medium

## Goal
Choosing the usable book snapshot for a trade costs one index seek instead of a scan of the instrument's whole history, so re-evaluating variant 1 over 28 days fits the 15 minutes of M04's ASM-2. ADR-002 records the measured storage growth, which the author accepts instead of reducing it.

## Evidence and Current Behavior
- See `audit.md` (evidence facts, VM measurements, consumers found with grep `book_snapshot` and `Database(` over `src/`).
- Entry point: `src/polyquack/evaluation/readings.py:151` `Reader.snapshot`.
- Covering tests: `tests/test_readings.py:52`, `:61`; indirectly `tests/test_evaluate.py:221`, `:486`, `tests/test_reevaluation.py:499`, `:511`.
- Consumers of altered contracts: `schema.sql` is executed by every writable open (`cli.py:30`, `:55`, `:67`, `:78`); read-only opens skip it (`db.py:59-61`).

## Scope
Included:
- Index `book_snapshot_instrument_source_time` on `book_snapshot (instrument_id, source_time)` in `schema.sql`, created with `IF NOT EXISTS`.
- A regression test on the query plan of `Reader.snapshot`.
- The index in `docs/design/data/schema.dbml`.
- An ADR-002 amendment with the measured capacity.
- The deploy order on the VM and the before/after measurements in `vm-qa-log.md` of this folder.

Excluded:
- Re-encoding or compressing levels, retention, or any change to reading rows and their insert-only triggers.
- Any change to the text of `Reader.snapshot`'s query, the evaluator, or variant 1's preregistration.
- Other indexes or profiling hot spots (commits, `_measure`), unless the live re-evaluation still exceeds 15 minutes (then a new change).

## Decisions and Assumptions
- Decision DEC-1: add the index and accept the measured growth; do not compress levels. The author, 2026-11-18, «Índice y aceptar tamaño».
- Decision DEC-2 (preserved): M01 DEC-1, full-precision levels within 0.5% with reach, stays as is.
- Assumption ASM-1: the live 12 min 26 s was dominated by the snapshot scan; stop and report if the live `reevaluate 1` after deploy still takes more than 15 minutes for 28 days (or, before the horizon, more than 15 × days / 28 minutes).
- Assumption ASM-2: no two snapshots of one instrument share a `source_time`, so the index cannot change which row is chosen; stop if the VM tie count (QA step) is not 0, and add a deterministic tie-breaker in a new decision.

## Requirements and Acceptance
| ID | Required Behavior | Acceptance |
|---|---|---|
| R-1 | `Reader.snapshot`'s query is answered by the new index, without scanning or sorting the instrument's snapshots | AC-1: a test asserts that `EXPLAIN QUERY PLAN` of the query text used by `Reader.snapshot` searches `book_snapshot_instrument_source_time` on `instrument_id` and `source_time` and has no `TEMP B-TREE` step |
| R-2 | Snapshot selection is unchanged | AC-2: the existing snapshot tests (audit list) pass unmodified |
| R-3 | Opening an existing database without the index adds it once, and reopening is idempotent | AC-3: a test opens a database, drops the index through raw SQL, reopens it with `Database`, and finds the index in `sqlite_master` |
| R-4 | The design records the index | AC-4: `schema.dbml` `book_snapshot` lists `(instrument_id, source_time) [name: 'book_snapshot_instrument_source_time']` |
| R-5 | ADR-002 states the measured capacity and the author's acceptance | AC-5: an ADR-002 amendment with the measured MB/day, GB/year at 38 and 100 pairs, disk runway, the unchanged 50 GB revisit trigger, and the author's words |
| R-6 | The live database gets the index without costing ingestion minutes beyond its restart | AC-6: VM QA follows the deploy order below; `gap` rows starting during the deploy are only those of the ingestion restart |
| R-7 | Before/after numbers are measured on the VM | AC-7: `vm-qa-log.md` records the live `reevaluate 1` time and its days, the snapshot query plan, the index size, the tie count, and MB/day before (115) and after |

## Contracts and Risk Controls
- Deploy order on the VM: stop `polyquack-evaluation.timer`; `uv sync --no-dev`; restart `polyquack-ingestion` (it builds the index before its feeds start, `cli.py:30-40`); confirm the index exists; start the timer. This keeps the 15 s build from blocking the ingestion writer (ADR-002 amendment: 5 s `busy_timeout`).
- Backup with `.backup` before the deploy, as in earlier milestones.
- The index is additive: rollback is `DROP INDEX book_snapshot_instrument_source_time`; no reading row changes.

## Canonical Design Impact
- Manifest: `docs/spec/manifest.yaml` (lists `schema.dbml`).
- Update: `docs/design/data/schema.dbml`, `docs/design/architecture/adr/ADR-002-storage.md`.
- Preserve: M01 DEC-1; NFR-007 reproducibility; `quality-attributes.md`.

## Quality Obligations
- Tests: AC-1, AC-3 new; full `uv run pytest` passes.
- QA: VM steps of AC-6 and AC-7, run by the author.
- Static/build: `uv run mypy --strict src tests`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `gitleaks detect --no-git --source . --redact --no-banner`.
- Coverage/mutation: removing the index line from `schema.sql` makes AC-1 and AC-3 fail.

## Done When
On the VM, after the deploy order above, `time polyquack reevaluate 1` on the live database finishes within the ASM-1 bound with no ingestion gap other than the restart, and the author accepts the before/after numbers in `vm-qa-log.md`.

## Change Surface
- Expected edits: `src/polyquack/storage/schema.sql`, `tests/test_readings.py` (or `tests/test_migration.py` for AC-3), `docs/design/data/schema.dbml`, `docs/design/architecture/adr/ADR-002-storage.md`, this folder.
- Do not touch: `readings.py` query text, `ingestion/book.py`, triggers, `variant` rows, M04 change folder.

## Triggered Artifacts
| Artifact | Fired? | Reason |
|---|---|---|
| audit.md | Yes | strict reliability |
| plan.md | No | one writer; the deploy order is one session by the author |
| execution.md | No | implemented in this session; baseline and rounds go in `verification.md` |

## Stop Conditions
- AC-1 cannot be met with an index alone (the planner keeps a temp B-tree).
- The VM tie count is not 0 (ASM-2).
- The live re-evaluation still exceeds the ASM-1 bound.
