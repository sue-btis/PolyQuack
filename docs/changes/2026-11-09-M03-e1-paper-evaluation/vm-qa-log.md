# M03 — VM QA log

VM `duma-sidon`. The author ran the commands on the VM and pasted their outputs into the session; excerpts below are copied from them.

## Deploy (commit `aaeb806`), 2026-11-09
- Checkout switched to `feat/e1-paper-evaluation/josueDev`, `uv sync --no-dev`, ingestion restarted. `fee_schedule` afterwards: `1|crypto|1`, `1|equity|7`, `2||1`.
- The pre-M03 backup (`.backup /var/lib/polyquack/pre-m03.db`) does not appear in the pasted output.
- Preregistration by the author: `window_hours` 24, `entry` 0.00002, `exit` 0.000005, with the fixed fields of the spec. Output: `Preregistered E1 variant 1`. These are the values shown as an example in the session; the author kept them and the variant froze at its first run.
- Units installed; `systemctl list-timers`: next run `Mon 2026-11-09 22:22:00 UTC` (R-11 / AC-11).

## First run, 2026-11-09 22:22 UTC
- Journal: `1 runs started, 38 decisions, 0 deferred`; the service ran from 22:22:01 to 22:25:49 (3 min 48 s wall time, `Consumed 2.617s CPU time`). The wait was not investigated further; the checks below show no effect on ingestion.
- `variants`: `E1: 1 registered, 1 run`, `first run 2026-11-09T22:22:01.292Z` (preregistration frozen).
- Decisions: `hold` 32, `open` 6, no `no_action`.
- ASM-3: no `gap` row since 22:15 UTC and no `write failed`, lock or error line in the ingestion journal between 22:20 and 22:27.
- Trades: 12 rows for 6 positions (SOL, DOGE, CASHCAT, XPL, XMR, MORPHO), one leg per platform with opposite sides (Polymarket short ↔ Hyperliquid buy, Polymarket long ↔ Hyperliquid sell), fee 0.4 USD on Polymarket (0.04%) and 0.45 USD on Hyperliquid (0.045%) on 1,000 USD, snapshot minute `2026-11-09T22:20:00.000Z` for all (cutoff 22:21). Slippage ranged from 0 to 0.69 USD per leg (CASHCAT 0.69 and 0.43).

## 24-hour counts, 2026-11-11
- Decisions: `43|1634|1` (43 decided hours × 38 pairs = 1634; one `no_action`: `2026-11-10T09:21:00.000Z|no_usable_snapshot`).
- NFR-008 over the real run: decisions with `data_until > hour`: `0`; funding payments at or before the opening or after the close: `0`; trades whose snapshot `source_time` is after the decision: `0`.
- Funding hours with two readings (grouped by the hour of `source_time`): none.
- Ingestion completeness, last day (`completeness --days 1`, 2026-11-10T17:00Z to 2026-11-11T17:00Z), worst rows: Hyperliquid books `1418/1440 98.5%` on every pair; funding `24/24 100.0%`.

## ASM-3 investigation (ingestion loss versus the second writer)
- The 22 missing Hyperliquid minutes fall mostly in two episodes on 2026-11-11, 12:10–12:38 and 15:09–15:24 UTC, plus three isolated minutes (2026-11-10 22:44, 2026-11-11 10:24 and 17:15). Causes: `disconnected` and mostly `not_collected`.
- One ingestion process (PID 42062) throughout: no restart, no `write failed`, no traceback. During the episodes both platforms' channels closed together with `keepalive ping timeout`, and REST calls failed with `ConnectTimeout` and `timed out during opening handshake`.
- The episodes began before the evaluator's runs (12:22 and 15:22) and the 15:09 episode does not contain any evaluator start; the evaluator was the one affected: at 12:22 systemd logged `Failed to start Polyquack evaluation` (the command exits 1 on a deferred write) and at 15:22 `37 decisions, 1 deferred`; the next run at 16:22 made `39 decisions, 0 deferred`, catching up the deferred decision (R-4, R-10 observed in production). Runs at 17:22 and 18:22: `38 decisions, 0 deferred`, 0 to 3 s.
- System journal 12:05–12:40 at warning level: only the evaluation failure line; no kernel or network message.
- Reading (inference, not confirmed): the VM stalled (network or disk) during the episodes. The evaluator did not cause the loss. A plausible amplifier: ingestion commits synchronously inside its asyncio loop, so a slow disk commit would also delay WebSocket pings and minute closes; not measured.
- Result: ASM-3 holds for M03 (no loss attributable to the second writer); ingestion completeness met the ≥ 95% target.
