# M01 — One pair (BTC) is ingested end to end on the VM

Status: Ready for implementation
Size: medium
Reliability: strict
Implementation effort: high (concurrency: live channels, per-minute cutoff and rate-controlled REST in the same process)

## Goal
On the VM, a service stores the hourly funding, the mark and index price of each minute and a book snapshot of each minute for the BTC pair on Polymarket Perps and Hyperliquid. Each minute or hour without data is recorded as a gap. A command shows the pair's latest readings and gaps.

## Evidence and Current Behavior
See `audit.md` (2026-10-28). Summary:
- Entry point: none; Polyquack has no code and is not a git repository. Reference flow: `docs/design/ux/flows.mmd:2-23` (F-001).
- Covering tests: none.
- Consumers of altered contracts: `book_snapshot` and `gap` (`docs/design/data/schema.dbml`): no code consumers; documentary ones in `domain.md`, `flows.mmd`, FR-028 — grep `grep -rn "gap\|book_snapshot" docs/design docs/product`.
- Measured on 2026-10-28 (`probes/`): Hyperliquid delivers 20 levels per side covering ~0.025% on BTC; Polymarket Perps with `book::{iid}::50` covered 1.2% to 2.9% in one measurement and only 0.26% on the bid side in a second one the same day, so truncation (DEC-1) applies to both platforms.
- Both channels send the full book in every message; there are no incremental updates.

## Scope
Included:
- Initialize the git repository with `.gitignore`.
- SQLite schema of the 11 Ingestion tables from `schema.dbml`, with the changes in this spec.
- Instruments of both platforms at startup and once a day; pairing of all of them by asset.
- Continuous ingestion of funding, prices and book snapshots only for the pairs listed in the configuration (in M01: `BTC`).
- Gaps, rate control, reconnection, resync, VM service and status command.
- F-006 and F-008 from the ledger; new row in PRD §15 for DEC-1.

Excluded:
- Other pairs being ingested, funding history, instrument lifecycle, parameters and fees (M02). The tables `instrument_status`, `instrument_parameters` and `fee_schedule` are created but not populated.
- Evaluator, dashboard, exporter (M03 to M06). Any sending of orders (BR-011).
- Correcting ADR-004 or `quality-attributes.md` for Polymarket's published limits (see Contracts).

## Decisions and Assumptions
- **DEC-1 (author, 2026-10-28, «B»):** each snapshot stores the levels the platform delivers at full precision, without aggregation (Hyperliquid: `l2Book` without `nSigFigs`, 20 per side; Polymarket Perps: `book::{iid}::50`), only those within 0.5% of the mid price. The volume at 0.5% is computed with those levels, and each side records its reach: the relative distance to the mid of the farthest level delivered. If the reach is less than 0.005, the volume is truncated at that reach and is read that way; what is missing is never completed or estimated.
- **DEC-2 (from `schema.dbml`):** `*_notional_05` is notional: the sum of price × quantity in the quote currency. The `*_levels` quantities are in asset units, as the source gives them.
- **DEC-3 (spec):** the in-memory book is valid for the minute's snapshot if, since the last full snapshot received (channel message or REST resync), the connection did not drop. After each connection or reconnection the book is not valid until the REST resync or the first channel message arrives.
- **DEC-4 (spec, resolves F-008):** a gap always covers an expected, closed interval: the minute `[m, m+1)` for `book_snapshot` and `price`, the hour `[h, h+1)` for `funding`, and the failed attempt for `instruments`. An ongoing hole is represented by the rows of the intervals already elapsed; there are no rows with an unknown end, so `gap.ends_at` stays `not null`. Statuses: `book_snapshot` and `price` are born `final`; `funding` is born `open` (recoverable in M02, FR-011). This applies the second resolution that F-008 allows ("the design documents how an ongoing hole is represented"), instead of making `ends_at` null as `plan.md` suggested.
- **DEC-5 (spec, tools without an ADR):** Python ≥ 3.12; project with `pyproject.toml` and a `uv` lockfile; `mypy --strict`; `ruff check` and `ruff format --check`; `pytest`; `gitleaks` for secrets; the standard library `sqlite3`; `websockets` and `httpx` as the only runtime dependencies; systemd for the service.
- Assumption ASM-1: the funding rate of both platforms is hourly (`audit.md`); stop if a real run shows another periodicity or unit.
- Assumption ASM-2: the funding `source_time` is `time` of `fundingHistory` (Hyperliquid) and `timestamp` of `/v1/info/funding` (Polymarket), in ms UTC; stop if they do not match on-the-hour times ± 1 min.
- Assumption ASM-5: the VM has systemd and Python ≥ 3.12; stop if not.

## Requirements and Acceptance
| ID | Required Behavior | Acceptance |
|---|---|---|
| R-0 | Polyquack is a git repository; `.gitignore` excludes the database, local configuration, `docs/discovery/spikes/**/cache/` and `docs/discovery/spikes/DQ-006-ladders/events.json` | AC-0: `git status` does not list those files; `gitleaks` with no findings |
| R-1 | At startup and every 24 h the instruments of both platforms are stored (`platform`, `asset`, `instrument`) and the pairs by identical asset (`pair`). An instrument without a match is left without a `pair` and the status command lists it separately. If a platform's list fails, an `instruments` gap is recorded and retried with increasing wait. Requesting the list again does not duplicate rows | AC-1 (plan AC-001): after startup, the database has the instruments of both and the BTC pair; the status command lists the unpaired ones |
| R-2 | For each configured pair, every hour the already-paid rate of each platform is obtained and stored in `funding_reading` with the source's `source_time`, `received_at` and `origin = live`. The query starts 1 min after the top of the hour and is retried with rate control; if 15 min after the top of the hour there is no payment for that hour, an `open` `funding` gap for that hour is recorded | AC-2 (plan AC-002): after 2 h, BTC has 2 funding readings per platform with source time, or a gap for each hour that did not arrive |
| R-3 | One live connection per platform, subscribed to the book of each configured instrument (DEC-1); REST resync after each connection; heartbeat per each platform's rules; reconnection with increasing wait | AC-3a: the log shows the subscription and the resync after each connection |
| R-4 | At the close of each UTC minute `m`, per configured instrument: if the book is valid (DEC-3), a `book_snapshot` for `m` is stored with best bid and ask, volumes and levels up to 0.5%, reaches, and the `source_time` of the message used; if not, a `final` `book_snapshot` gap for `[m, m+1)` with its cause. Never both nor neither | AC-3 (plan AC-003): after 2 h, each minute has a snapshot or a gap per instrument, never both |
| R-5 | Each minute, a single request per platform (Polymarket `GET /v1/info/tickers`; Hyperliquid `POST /info metaAndAssetCtxs`); `price_reading` is stored for the configured instruments. Polymarket: `source_time` = the source's `timestamp`; Hyperliquid: `source_time` null. If it fails, a `final` `price` gap for the minute | AC-4 (plan AC-004): after 2 h, a price reading or a gap per minute and instrument; those from Hyperliquid with null `source_time` and filled `received_at` |
| R-6 | A single rate control per platform for all REST: configurable minimum interval (initial 0.8 s on both); on 429 or `ip_rate_limited`, it respects `Retry-After` if present and otherwise waits with exponential growth, without exceeding the configured pace | AC-7 (plan AC-007): in 2 h, no unhandled 429 or block; the log counts 2 price requests per minute |
| R-7 | After a network outage, ingestion reconnects and resyncs on its own; the minutes of the outage are left as gaps | AC-5 (plan AC-005): after cutting the network for 5 min, snapshot and price gaps appear for those minutes, the book resyncs over REST and ingestion continues |
| R-8 | The service starts with the VM and restarts itself if it fails (systemd unit) | AC-6 (plan AC-006): after restarting the VM, the first new reading is stored within ≤ 10 min |
| R-9 | The tables `funding_reading`, `book_snapshot` and `price_reading` reject UPDATE and DELETE in the database itself | AC-9: an UPDATE or DELETE on them fails with an error |
| R-10 | Status command: per configured pair and platform, the latest reading of each kind with its time and the gaps of the last 24 h; plus the unpaired instruments | AC-10: the command's output after 2 h shows the three classes of reading and the gaps |

## Contracts and Risk Controls
- **`book_snapshot` (changes, DEC-1):** adds `bid_reach real not null` and `ask_reach real not null` (fraction of the mid price up to the farthest level delivered). The notes of `*_notional_05` and `*_levels` say "up to 0.5% or up to the reach, whichever is smaller". Mid price = (best bid + best ask) / 2.
- **`gap` (the type is preserved, the note changes, DEC-4):** `ends_at` stays `not null`; the note on `status` documents which kinds are born `open` and which `final`.
- **Insert-only (R-9):** `BEFORE UPDATE` and `BEFORE DELETE` triggers with `RAISE(ABORT, ...)`. `gap` does allow UPDATE of `status` and `closed_at` (M02).
- **SQLite:** WAL mode; short transaction per minute; `busy_timeout` configured (F-010 is left for M02).
- **Times:** everything in UTC; source times in ms are converted without rounding to the minute, except `minute`.
- **Published limits (NFR-005):** Hyperliquid 1200 weight per minute per IP; Polymarket Perps 1000 tokens per minute per IP. M01's load is far below. ADR-004 and `quality-attributes.md` say Polymarket does not publish limits; that contradiction is recorded here and is not corrected in M01.
- **Security (NFR-011):** there are no credentials: all the APIs used are public. Configuration through environment variables or a local file outside the repository. The VM exposes no ports.
- **No orders (BR-011):** no client implements order or account endpoints.

## Canonical Design Impact
- Manifest: `docs/spec/manifest.yaml`
- Update:
  - `docs/product/prd.md`: FR-006 says the snapshot includes the volume up to 0.5% or up to the reach of the levels the platform delivers, with that reach recorded. New row **PD-022** in §15: "What does the book snapshot store if the platform does not deliver depth up to 0.5%?" — Decided — the decision in DEC-1 — Author — 2026-10-28 — «B» — FR-006, `docs/design/domain.md`, `docs/design/data/schema.dbml`.
  - `docs/product/prd.md:351` (F-006): status `Decided`; "Replaced by PD-006" moves to the Decision column.
  - `docs/design/domain.md`: definition of Book snapshot (reach and truncated volume); Gap (DEC-4: closed intervals, what is born `open`).
  - `docs/design/data/schema.dbml`: `book_snapshot` and `gap` per Contracts.
  - `docs/design/review.md`: F-006 and F-008 become resolved, citing this folder.
- Preserve: ADR-001 to ADR-006, `architecture.dsl`, `flows.mmd`, `quality-attributes.md`, Evaluation and Publishing tables.
- Supersede only with approved decision: none. `plan.md` (TST-002, F-008) is reinterpreted by this spec: TST-002 tests validity per connection (DEC-3), not sequence jumps.

## Quality Obligations
- Tests (`pytest`, no network):
  - TST-1 pairing with sample lists (trimmed real responses): pairs BTC, separates unpaired ones, does not duplicate when repeated (R-1).
  - TST-2 book: a full snapshot replaces the state; after reconnection the book is invalid until the resync; the snapshot computes the mid, volumes, levels up to 0.5% and reaches, including the truncated case (R-3, R-4, DEC-1, DEC-3).
  - TST-3 gaps: a minute without a valid book produces a `final` gap and no snapshot; an hour without funding produces an `open` gap (R-2, R-4, BR-001).
  - TST-4 rate control: on a simulated 429 with and without `Retry-After`, it waits longer and never drops below the minimum interval (R-6).
  - TST-5 insert-only on a real database in a temporary file (R-9).
  - TST-6 prices: with sample responses, it stores Polymarket with `source_time` and Hyperliquid with null `source_time`; a failure produces a gap (R-5).
- Static/build: `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`, `gitleaks detect`.
- QA on the VM (manual, with a log): 2 h run; 5 min network cut; VM restart.
- Coverage/mutation: no percentage is required; each R-* has at least one test or a named manual verification.

## Done When
On the VM, after 2 h of service, a 5 min network cut and a restart, the status command shows for BTC on both platforms: 2 funding readings or gaps per hour, and per minute a snapshot and a price or their gap; the log shows the resync after the cut, the first reading ≤ 10 min after the restart and 2 price requests per minute. The tests and the static gates pass.

## Change Surface
- Expected edits (proposed paths, medium confidence):
  - `Polyquack/pyproject.toml`, `uv.lock`, `.gitignore`, a brief `README.md` in English with commands.
  - `Polyquack/src/polyquack/ingestion/` (per-platform clients, book, rate control, service), `Polyquack/src/polyquack/storage/` (schema and writes), `Polyquack/src/polyquack/cli.py`.
  - `Polyquack/src/polyquack/storage/schema.sql` derived from the DBML.
  - `Polyquack/deploy/polyquack-ingestion.service`.
  - `Polyquack/tests/`.
  - Documents listed in Canonical Design Impact.
- Do not touch: `docs/discovery/`; Evaluation and Publishing tables; ADRs; findings F-007 and F-010 to F-015.

## Triggered Artifacts
| Artifact | Fired? | Reason |
|---|---|---|
| audit.md | Yes | reliability `strict` |
| plan.md | No | a single writer, no staged deployment |
| execution.md | Yes | implementation continues in another session (2 h run and restart on the VM) and another session verifies it |

## Stop Conditions
- Any commit requires the author's confirmation; the work goes on the branch `feat/btc-ingestion/josueDev` (branch names never carry the milestone ID), never on `main`.
- A platform changes the format of its channel or its endpoints relative to `audit.md`.
- ASM-1, ASM-2 or ASM-5 turn out to be false.
- The implementation needs to change an accepted ADR, another schema table or M02 to M06 behavior.
- The canonical documents contradict each other in a way that two different implementations would be valid.
