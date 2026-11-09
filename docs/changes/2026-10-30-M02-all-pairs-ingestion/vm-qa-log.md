# M02 — VM QA log

VM `duma-sidon`, 2026-11-02. The author ran the commands on the VM and pasted their outputs into the session; excerpts below are copied from them.

## Deploy (commit `79d065e`)
- Database backed up to `/var/lib/polyquack/pre-m02.db` with `sqlite3 .backup`, then the checkout switched to `feat/all-pairs-ingestion/josueDev`, `uv sync --no-dev`, `systemctl restart`.
- Restart at 16:05:55 UTC: `Deactivated successfully` then `Started`; one process (PID 20706) from then on. No migration error, no `Traceback`, no `WARNING`, no `429` in the journal since 15:50 (`grep -iE "...|429|rate|error|traceback|warning|migrat"` returned none of them).
- No target-change restart (F-7) happened: the M01 database already held the 38 pairs (M01 paired every instrument and ingested only BTC), so the stored targets equalled the refreshed ones. The restart path on a real target change was therefore not observed on the VM.

## ASM-2 — subscriptions
- Hyperliquid: `connected`, then `subscribed to AAVE, ADA, … ZRO` (38 coins).
- Polymarket: `connected`, then `subscribed to 54, 66, … 67` (38 instrument ids).
- `grep -c "resync of"` since 15:50: 76 (38 × 2), from 16:05:58 to 16:07:24. Holds.

## ASM-3 — backfill pace
- Backfill finished at 16:13:04 for the last pair (Polymarket VVV), about 7 min after start, about 11–12 s per Polymarket pair (14 pages) and 2–2.5 s per Hyperliquid pair.
- 1456 payments for most pairs, exactly the hours from 2026-09-03T00:00Z to 2026-11-02T16:00Z (60 × 24 + 16). Several Polymarket pairs read 1266–1271 (CASHCAT, ETHFI, JUP, KAITO, LDO, LINK, LTC, MORPHO, PENDLE, PONS, USELESS, VIRTUAL): their history starts about 8 days after the floor (ASM-1, "oldest available"; F-8 applies to them).
- No `429` or block. Holds.

## Instruments and status
- `hyperliquid: 235 instruments stored` (delisted coins now kept, R-2); `polymarket_perps: 90 instruments stored`.
- `polyquack status` at 16:13:57 lists the pairs with `[active]`; for AAVE and ADA both platforms show funding of 16:00, book of 16:12, price of 16:13 and 0 gaps in 24 h.
- Polymarket book reach for AAVE is `0.46279/0.53533` and for ADA `0.39593/0.42315`: the delivered levels reach far from the mid on these thinner books. Recorded as observed, not checked further.

## Dated rows (2026-11-02, read-only query)
- `instrument_status`: `active` 269, `delisted` 56 (325 instruments, one row each).
- `instrument_parameters`: 325 rows, all effective `2026-11-02T16:05:55.560Z`.
- `fee_schedule`: Polymarket (`platform_id` 1) 7 rows, category `equity`; Hyperliquid (`platform_id` 2) 1 row, category `''`, effective `2026-10-30`.
- Polymarket's `GET /v1/info/fees` itself returns a single entry, `perpetual`/`equity` (taker 0.0004, maker 0.000125, 7 tiers), while its instruments are `crypto` 41, `equity` 38, `index` 6, `commodity` 4, `pre_ipo` 1 (checked from the development machine on 2026-11-02). The code stored what the API returns, but no fee row covers the `crypto` category of the 38 pairs (verification F-14).

## 7-day run (AC-7), 2026-11-09
`polyquack completeness`, window `2026-11-02T18:00:00.000Z` to `2026-11-09T18:00:00.000Z`, 38 pairs × 2 platforms:
- Funding: `168/168 100.0%` on every pair and platform.
- Book snapshots, Polymarket: `10076/10080 100.0%` on every pair (4 minutes missing, the same for all pairs).
- Book snapshots, Hyperliquid: `10070/10080` to `10072/10080`, `99.9%` on every pair.
- Target ≥ 99% of hours with funding and ≥ 95% of minutes with a snapshot: met on all 76 rows.

## Database size (ADR-002 hypothesis), 2026-11-09 18:22 UTC
`ls -lh`: `polyquack.db` 849M, `-wal` 4.0M, `-shm` 32K.

Projection (arithmetic, assuming almost all of it is the 7 days of 38 pairs; M01's BTC-only days and the funding history are small by row count): about 120 MB per day at 38 pairs, about 44 GB per year at 38 pairs, about 115 GB per year at 100 pairs. ADR-002 hypothesized 10–20 GB per year at 100 pairs and sets a revisit trigger at a 50 GB file, which this rate reaches in about 14 months at 38 pairs. The hypothesis does not hold (verification F-15). Which columns dominate was not measured.
