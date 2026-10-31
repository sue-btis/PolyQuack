# ADR-002 — Where the data is stored

Status: Accepted
Date: 2026-10-26
Decision owners: the author
Accepted by: the author, 2026-10-26, «I have some VMs I could use, they are local, and sqlite»
Related: FR-004 to FR-011, FR-026, NFR-001, NFR-006, NFR-007, NFR-010, BR-001

## Context
Polyquack stores time series and paper trade records. Estimated volume with 100 pairs on 2 platforms:

- book snapshots: 100 × 2 × 1,440 per day = 288,000 records per day, about 105 M per year;
- funding: 100 × 2 × 24 = 4,800 per day.

Each snapshot stores a summary (best bid, best ask and depth at 0.5%), not the full book (FR-006). A single process writes and a single user queries (CON-002). Evaluation has to be reproducible (NFR-007).

## Decision Drivers
- A single writer and a single user.
- Analytical queries over long series: differences, sums per period, book walks.
- Zero extra administration and no extra cost on the local VM (ADR-001).
- Simple backups.

## Options Considered
### Option A — SQLite in a single file, in WAL mode
- Benefits: no database server, one file that is backed up by copying it, SQL constraints and integrity. It handles hundreds of millions of rows with suitable indexes. DuckDB can read it directly for heavy analysis.
- Costs/risks: one writer at a time, which is not a problem here. Large file in a year (**Hypothesis**: about 10 to 20 GB with 100 pairs; to be measured).

### Option B — PostgreSQL (with or without TimescaleDB)
- Benefits: concurrency, time-series extensions and mature tooling.
- Costs/risks: one more service to administer, more memory on the VM and more complex backups. The concurrency it offers is not needed.

### Option C — Daily Parquet files, queried with DuckDB
- Benefits: excellent compression and very fast analysis.
- Costs/risks: it is not a transactional database. Recording gaps, method preregistration and paper trades requires another piece or rewriting files. There are two formats to maintain.

## Decision
**Option A**, SQLite in WAL mode as the single source of truth. Heavy analyses can read it with DuckDB without copying it.

## Consequences
### Positive
- A single piece of data and backup by copying the file.
- Reproducibility (NFR-007) rests on data that does not change: readings are only appended, never edited.

### Negative / Trade-offs
- If one day there are several writers or several users, a migration is needed.

## Verification / Revisit Trigger
- If the file exceeds 50 GB, or if a dashboard query takes longer than NFR-009 allows, review Option C for the history.
