# Snapshot index and storage capacity — VM QA log

VM `duma-sidon`. The author ran the commands on the VM and pasted their outputs into the session; excerpts below are copied from them.

## Before (2026-11-17, read-only on the live file; timings on a `.backup` copy)
- File 1.8 GB, 67 GB free; 7.8 GiB RAM, 1.8 GiB swap in use.
- Growth about 115 MB per day at 38 pairs (measurements in `audit.md`).
- Plan of `Reader.snapshot`'s query: `SEARCH book_snapshot USING INDEX sqlite_autoindex_book_snapshot_1 (instrument_id=?)`, `USE TEMP B-TREE FOR ORDER BY`.
- Live `reevaluate 1` (M04 QA): 7258 decisions, `real 12m26.333s` (103 ms per decision).

## Deploy (commit `3355b4d`), 2026-11-20
- The `.backup` to `pre-index.db` was not taken (deviation from the spec's risk controls; the index changes no row and is reverted with `DROP INDEX`).
- `polyquack-evaluation.timer` stopped; checkout switched to `fix/snapshot-source-time-index/josueDev`; `uv sync --no-dev`.
- `systemctl restart polyquack-ingestion` at 20:32:03 UTC. The service started at 20:32:04 and logged its first request at 20:34:47: the index build took about 2 min 43 s inside the ingestion start-up (inferred from the log gap; the build itself is not logged), against 14.5 s on the warm copy.
- An index check seconds after the restart returned nothing, because the build had not committed yet; at 21:37 it returned `book_snapshot_instrument_source_time`. The timer was restarted at about 20:32, before the build finished; its next run was 21:22, after it.
- Gaps since 20:30: `book_snapshot` 20:32–20:34, 152 rows; `price` 20:33–20:35, 152 rows; all `not_collected` (38 pairs × 2 platforms × 2 minutes). These are the restart's minutes; no other gap.

## After (2026-11-20)
- Plan: `SEARCH book_snapshot USING INDEX book_snapshot_instrument_source_time (instrument_id=? AND source_time>? AND source_time<?)`, no temp B-tree.
- Index size: 68.3 MB. File 2,323,615,744 bytes at 22:21 UTC; 65 GB free.
- Live `reevaluate 1` from 22:22:36 with ingestion running: `Re-evaluation run 3: in_progress, 10070 decisions, 0 deferred`, `real 4m40.143s` (28 ms per decision). ASM-1 bound for these 11 days (15 × 11 / 28 min ≈ 5.9 min): met. Linear extrapolation to 28 days (not measured): about 12 minutes.
- No `gap` row starting at or after 22:22.

## Ties on `source_time` (ASM-2)
- `count(*)` of `(instrument_id, source_time)` groups with more than one snapshot: 153.
- Per day: 2026-11-10 38 groups / 190 rows; 2026-11-11 39 / 78; 2026-11-15 38 / 76; 2026-11-17 38 / 76; groups whose rows differ in levels: 0 on every day.
- Trades (any run) whose `snapshot_minute` is a tied snapshot: none.
- Local check on SQLite 3.50.4: with ties the old scan returns the earliest minute and the indexed query the latest. With identical levels only `snapshot_minute` can differ, never the price; no stored trade is affected. The author accepted the index's order (decision F-2 in `verification.md`).

## Size per day after (2026-11-23)
- File 2,734,501,888 bytes at 21:37 UTC: 391.9 MiB more than on 2026-11-20 22:21, about 132 MiB per day over 71.3 h. That figure includes the 22:22 re-evaluation's rows, so it is split by `dbstat` below.
- `dbstat` at 21:39 UTC against 2026-11-17 21:18 (6.01 days); `book_snapshot` rows 2,327,126 (+657,203, about 109,300 per day):

| Object | 11-17 MB | 11-23 MB | MB per day |
|---|---|---|---|
| `book_snapshot` | 1485.9 | 2072.4 | 97.5 |
| `price_reading` | 145.5 | 203.2 | 9.6 |
| PK indexes of both | 125.5 | 174.8 | 8.2 |
| `book_snapshot_instrument_source_time` | 68.3 (11-20 22:21) | 80.4 | 4.1 (over 2.97 days) |
| Ingestion total | | | **119.4** (before: 115.3) |
| `position_measurement` + its index | 14.1 | 52.7 | not per day: rows 134,630 → 502,490, mostly re-evaluation run 3 |

- Projection after: about 44 GB per year at 38 pairs, about 115 GB per year at 100 pairs; 65 GB free on 2026-11-20 lasts about 545 days; the 50 GB trigger is about 13 months away from the 2.7 GB file. ADR-002 updated with the measured 4.1 MB per day of the index.
