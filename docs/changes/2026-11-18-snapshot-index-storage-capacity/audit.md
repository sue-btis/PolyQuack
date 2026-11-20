# Snapshot index and storage capacity — Audit

Status: Ready for specification
Size: medium
Reliability: strict
Audit trigger: strict (schema of a reading table on the live database; the E1 verdict re-evaluation depends on it)

## Evidence Facts
| Fact | Evidence |
|---|---|
| Entry point | `src/polyquack/evaluation/readings.py:151` `Reader.snapshot`, called from `runner.py:367-368` (`_plan_trades`) and `runner.py:812` (`_plan_leg_closes`) |
| Covering tests | `tests/test_readings.py:52`, `:61`; `tests/test_evaluate.py:221`, `:486`; `tests/test_reevaluation.py:499`, `:511` (indirect) |
| Consumers of each altered contract | `schema.sql` (new index, no column change): writable `Database` opens in `cli.py:30` (`run`), `:55` (`preregister`), `:67` (`evaluate`), `:78` (`reevaluate`); read-only opens (`cli.py:91`, `:151`) skip `schema.sql` (`db.py:59-61`). Queries on `book_snapshot`: `db.py:329`, `db.py:417`, `completeness.py:25`, `:63`, `status.py:35`, `readings.py:137`, `:153`. Found with grep `book_snapshot` and `Database(` over `src/` |

## Baseline
| Field | Value |
|---|---|
| Repository root | `Polyquack-storage` (sibling worktree of `Polyquack`) |
| Branch | `fix/snapshot-source-time-index/josueDev`, created from `feat/basis-liquidation-verdict/josueDev` |
| Commit SHA | `24b5532` |
| Working tree | Clean |
| Relevant pre-existing changes | The main checkout has uncommitted M04 docs (`verification.md`, `vm-qa-log.md`) owned by another session; not touched here |
| Audit date | 2026-11-18 |

## Desired Outcome and Constraints
- Outcome: `Reader.snapshot` finds the latest usable snapshot with one index seek instead of scanning the instrument's whole history, so re-evaluation time stops growing with the stored days; ADR-002 records the measured storage growth, accepted by the author.
- Included: one index in `schema.sql`, its DBML entry, a regression test on the query plan, ADR-002 capacity amendment, the deploy order.
- Excluded: compressing or re-encoding levels (measured, not chosen), any change to reading rows, triggers, the preregistration of variant 1, or the evaluator's logic.

## Current Behavior Trace
1. `runner.py:367` `_plan_trades` calls `Reader.snapshot` for both legs whenever a trade is planned; `runner.py:812` does the same for closes.
2. `readings.py:153-157` runs `WHERE instrument_id = ? AND source_time <= ? AND source_time >= ? ORDER BY source_time DESC LIMIT 1`.
3. On the VM, `EXPLAIN QUERY PLAN` shows `SEARCH book_snapshot USING INDEX sqlite_autoindex_book_snapshot_1 (instrument_id=?)` plus `USE TEMP B-TREE FOR ORDER BY`: every snapshot of the instrument is read and sorted.

## Measurements (VM `duma-sidon`, 2026-11-17, read-only on the live file, timings on a `.backup` copy)
| Measure | Value |
|---|---|
| File | 1.8 GB; disk 67 GB free; 7.8 GiB RAM, 1.8 GiB swap in use |
| `book_snapshot` / its PK index | 1485.9 MB / 63.0 MB |
| `price_reading` / its PK index | 145.5 MB / 62.5 MB |
| `bid_levels` + `ask_levels` | 570.6 + 568.1 MB over 1,669,923 rows, about 19 levels per side |
| Rows per day | about 109,400 per reading table (38 pairs × 2 × 1440) |
| Growth | about 115 MB per day at 38 pairs (book about 97, price about 9.5, PK indexes about 8) |
| Level encodings, day 2026-11-16 | JSON 73.4 MB, JSON+zlib 29.0, float64 62.9, float64+zlib 47.9; 0 rows identical to the previous minute |
| `reevaluate 1` (8 days) live, 2026-11-17 | 12 min 26 s |
| Same on the copy, warm cache, under cProfile | 44 s; `Reader.snapshot` 146 calls, 17.9 s (44%) |
| Same on the copy, cold cache, no index | 2 min 13 s |
| Same on the copy, cold cache, with the index | 35 s |
| Index size / build time on the copy | 56.7 MB / 14.5 s |

## Actual Problem / Change Location
The snapshot query has no index on `source_time`, so its cost grows with each instrument's history and the number of calls grows with positions; the PK `(instrument_id, minute)` cannot bound it, because `source_time` is the book's last update (`ingestion/book.py` `Snapshot.source_time_ms`) and has no staleness bound relative to `minute`. Storage growth is dominated by the levels JSON (DEC-1 of M01 keeps full precision within 0.5%).

## Contracts and Boundaries
| Contract / Boundary | Current Shape | Consumers | Change Risk |
|---|---|---|---|
| `schema.sql` executed on every writable open | `CREATE … IF NOT EXISTS` statements; precedent `gap_instrument_kind_start` (`schema.sql:105`) | `run`, `preregister`, `evaluate`, `reevaluate` | Medium: the first writable open on the live file builds the index (about 15 s holding the write lock) |
| Two writers under WAL, `busy_timeout` 5 s (ADR-002 amendment) | ingestion write failing after 5 s leaves a `not_collected` gap | ingestion | Medium: if `evaluate` builds the index while ingestion runs, ingestion loses the minutes of the build |
| Query results of `Reader.snapshot` | latest snapshot by `source_time` within `[cutoff - max_age, cutoff]` | runner | Low: an index does not change results (ties on `source_time` excepted, see ASM-2) |
| Insert-only triggers `schema.sql:112-115` | unaffected by an index | — | None |

## Tests and Validation
| Test / Command | Covers | Gap | Prerequisite |
|---|---|---|---|
| `tests/test_readings.py:52`, `:61` | snapshot selection rules | does not check the plan | — |
| `tests/test_migration.py` (opens schema repeatedly) | idempotent schema | — | — |
| `uv run mypy --strict src tests`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest`, gitleaks | gates | — | uv, Python 3.13 |
| VM: cold-cache `reevaluate 1` and live `reevaluate 1` timing | the outcome | live run not yet repeated | author runs it |

## Candidate Ownership
| Workstream | May Read | Candidate Write Set | Coupling / Conflict Risk |
|---|---|---|---|
| single writer | `src/`, `tests/`, `docs/design` | `src/polyquack/storage/schema.sql`, `tests/test_readings.py`, `docs/design/data/schema.dbml`, `docs/design/architecture/adr/ADR-002-storage.md`, this change folder | none |

## Integration and Generated-File Hotspots
None.

## Supported Options
| Option | Evidence | Pros | Cons | Approval Status |
|---|---|---|---|---|
| Index `(instrument_id, source_time)` | 2 min 13 s → 35 s cold | exact, one line | +56.7 MB now, about 3.7 MB/day | Approved by the author 2026-11-18 («Índice y aceptar tamaño») |
| Bound the query by `minute` | — | no extra space | needs a staleness bound that does not exist | Rejected |
| zlib levels for new rows | 73.4 → 29.0 MB/day of levels | about 38% less growth | two formats, DBML change, still above ADR-002's hypothesis | Not chosen by the author |

## Material Decisions Needed
None open.

## Assumptions
| ID | Assumption | Validation | Stop If False |
|---|---|---|---|
| ASM-1 | The live 12 min 26 s was mostly the snapshot scan under memory pressure; with the index the live re-evaluation drops well below 15 minutes | live `reevaluate 1` after deploy | report the time; do not add more changes without a new profile |
| ASM-2 | `source_time` ties within one instrument are rare; with ties the scan and the index may pick a different row | two re-evaluations stay byte-identical (NFR-007 export check) | stop and add a deterministic tie-breaker (`minute DESC`) |

## Contradictions and Risks
- ADR-002's 10–20 GB/year hypothesis does not hold (F-15 of M02); the author accepts the measured growth instead of reducing it.
- Deploy risk: the index build holds the write lock for about 15 s; if the evaluation timer is the first writable open while ingestion runs, ingestion loses those minutes.

## Do Not Touch
- Reading rows, insert-only triggers, `variant` preregistration, `book.py` level encoding, evaluator logic.

## Recommended Next Step
Write the spec.
