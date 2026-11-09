# M02 — All pairs are ingested 24/7 and recover on their own

Status: Ready for implementation
Approved by: the author, 2026-10-30
Size: medium
Reliability: strict
Implementation effort: high (schema migration of a deployed database and SQLite two-writer concurrency)
Parent: none (builds on `docs/changes/2026-10-28-M01-btc-ingestion/`, accepted 2026-10-30)

## Goal
On the VM, the service ingests funding, book snapshots and prices for every paired pair that is not delisted (38 today), records each instrument's lifecycle, parameters and fee schedule with effective dates, recovers missing funding from each platform's history, and a command reports per pair the share of hours with funding and of minutes with a book snapshot.

## Evidence and Current Behavior
See `audit.md` (2026-10-30, commit `6b1e30b`). Summary:
- Entry point: `src/polyquack/cli.py:32`; scope from `POLYQUACK_ASSETS` (`src/polyquack/config.py:15`).
- Covering tests: `tests/test_service.py`, `test_storage.py`, `test_parsers.py`, `test_feed.py`, `test_book.py`, `test_ratelimit.py`.
- Consumers of altered contracts: listed in `audit.md` Evidence Facts (grep).
- Targets, books and feeds are built once at startup (`service.py:58-77`); nothing writes `instrument_status`, `instrument_parameters` or `fee_schedule`; funding gaps are never closed; Hyperliquid drops delisted rows (`platforms.py:169`).
- Platform facts measured on 2026-10-30 are in `audit.md` (Platform Facts, Documentation Findings) and `probes/`.

## Scope
Included:
- All pairs, optional asset filter, lifecycle, parameters, fees, funding history recovery, completeness report, batched gap filling, `fee_schedule` migration, ADR-002 amendment (F-010), fee source (F-011, fees only).

Excluded:
- Evaluator, dashboard, exporter (M03 to M06); any order or account endpoint (BR-011).
- Close-only detection on Hyperliquid (no public signal, `audit.md`).
- Fee tiers other than the base tier on Hyperliquid; parameter tiers other than the base tier on both platforms.
- In-process rebuild of feeds (DEC-4 picks a restart).
- Changing reconnect or resync behavior accepted in M01.

## Decisions and Assumptions
Approved by the author on 2026-10-30 (`audit.md`, Author Decisions):
- **DEC-1 (maintenance margin):** derived from each platform's published rule: `maintenance_margin = 0.5 / max_leverage` of the base tier. Polymarket: `max_leverage` of the instrument row; Hyperliquid: `maxLeverage` of the first tier of the instrument's `marginTables` entry.
- **DEC-2 (fees):** Polymarket from public `GET /v1/info/fees`, every category and tier it returns. Hyperliquid by hand: a versioned data file in the package with tier 0 (taker 0.00045, maker 0.00015) effective from 2026-10-30, the date it was read on `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`. A rate change is a new entry with its own date. The rates came from a fetch summary, so the implementer reads the page and stops if tier 0 differs.
- **DEC-3 (lifecycle signals):** Polymarket `close_only = true` → `close_only`, otherwise `active`; an instrument missing from the list is queried by `instrument_id` and becomes `delisted` only if the answer has `settlement`. Hyperliquid `isDelisted = true` → `delisted`, otherwise `active`; Hyperliquid has no `close_only`. Any other absence changes no status and is logged.
- **DEC-4 (target changes):** when an instrument refresh changes the set of targets, the process logs the change and exits with status 0; systemd restarts it (`Restart=always`).
- **DEC-5 (backfill pace):** all history requests run as one sequential task per platform through that platform's existing limiter; never concurrent requests.
- **DEC-6 (two writers, F-010):** every write transaction stays short (target under 1 s), the 5 s `busy_timeout` stays, and a write that still fails is logged and leaves no row; the elapsed interval becomes a `not_collected` gap at the next tick through the existing coverage rule.
- **DEC-7 (fee category):** `fee_schedule.category text not null`, `''` for Hyperliquid; primary key `(platform_id, effective_from, category, tier)`.
- **DEC-8 (base tier):** `instrument_parameters` keeps the base tier only.
- **DEC-9 (`POLYQUACK_ASSETS`, default proposed at shaping and not objected to):** optional filter; when unset or empty, every non-delisted pair is a target.

Spec decisions (derived from the domain, no stakeholder input needed):
- **DEC-10 (pair status):** derived, not stored: a pair is `delisted` if either instrument's latest status is `delisted`, else `close_only` if either is `close_only`, else `active` (`domain.md:47`; `schema.dbml` has no pair status column). An instrument with no status row is `active`.
- **DEC-11 (when an open funding gap becomes final):** an `open` funding gap for hour `h` becomes `final` when a history response contains a payment later than `h` but none for `h`; it becomes `closed_with_data` when a payment for `h` is stored. Otherwise it stays `open` (`domain.md:59`).

Assumptions:
- ASM-1: Polymarket history reaches 2026-09-03 or the instrument's listing for every pair (measured for BTC only); not a stop: FR-005 says "oldest available".
- ASM-2: one Polymarket connection accepts 38 `book::` channels and one Hyperliquid connection 38 `l2Book` subscriptions; stop if a platform rejects them.
- ASM-3: the 0.8 s pace holds during the first backfill (about 650 requests) without blocks; stop if blocks repeat (NFR-005).
- ASM-4: Hyperliquid minimum notional is 10 USD for every perpetual (search snippet of the error-responses page, not fetched); the implementer reads `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses` and stops if it says otherwise.
- ASM-5: Polymarket's `MMR = 0.5 / MaxLeverage` holds; the researcher reported the docs' sample responses may disagree. Not a stop for M02; recorded for M04, which first consumes the value.

## Requirements and Acceptance
| ID | Required Behavior | Acceptance |
|---|---|---|
| R-1 | Targets are every pair whose derived status (DEC-10) is not `delisted`, narrowed by `POLYQUACK_ASSETS` when set (DEC-9). Funding, prices and book snapshots run for all targets with M01's rules | AC-1 (plan AC-008): with all pairs, every target has, per hour, a funding reading or gap and, per minute, a snapshot and a price or their gaps |
| R-2 | Each instrument refresh (startup and every 24 h) parses lifecycle per DEC-3 and inserts an `instrument_status` row only when the status differs from the latest one (first sight inserts one). Hyperliquid delisted instruments are stored as instruments with status `delisted` and are never paired anew | AC-2 (plan AC-009): a simulated list change from active to close_only to absent-with-settlement produces three dated status rows and the pair's derived status follows |
| R-3 | When a refresh changes the target set, the process exits with status 0 after logging old and new sets (DEC-4) | AC-3: in a test, a refresh that adds or removes a target ends `Service.run` without an exception and logs the change |
| R-4 | A target whose funding has no coverage before the earliest stored hour gets history from `max(2026-09-03, oldest available)` up to that hour, paged (Polymarket backward, 100 rows; Hyperliquid forward, 500 rows), stored with `origin = history` (DEC-5) | AC-4 (plan AC-010): a new pair receives every hourly payment the history returns from 2026-09-03, none before |
| R-5 | A recovery pass at startup and every hour at minute 20 requests history for each target with `open` funding gaps, from the oldest open hour; stores missing payments with `origin = history`; closes gaps per DEC-11 (`status`, `closed_at`) | AC-5 (plan AC-011): after a simulated 1 h outage with recorded history, the funding gaps of that hour end `closed_with_data` with real readings and the book gaps of the outage are `final`; a gap with no payment in history but later payments present ends `final` |
| R-6 | Each refresh inserts `instrument_parameters` (DEC-1, DEC-8; Polymarket `min_notional` and `liquidation_fee` from the row; Hyperliquid `min_notional` 10 per ASM-4 and `liquidation_fee` null) only when a value differs from the latest row; and `fee_schedule` rows (DEC-2, DEC-7) only when they differ from the latest rows of that platform and category | AC-6 (plan AC-012): after startup, both tables hold one dated row set per instrument and per platform; a second refresh with unchanged data adds nothing |
| R-7 | `polyquack completeness [--days N]` (default 7) prints, per pair and platform, the percentage of expected hours with a funding reading and of expected minutes with a book snapshot in the window ending at the last full hour; an interval is expected from the instrument's first reading or gap of that kind | AC-7 (plan AC-013): after 7 days on the VM the report shows at least 99% of hours with funding and 95% of minutes with a snapshot per pair |
| R-8 | Elapsed intervals of one instrument and kind become `not_collected` gaps in one transaction (batched `_pending`) | AC-8: after a simulated 1 h outage with 76 instruments, the gaps are written in at most one transaction per instrument and kind |
| R-9 | Existing database migrates on startup: if `fee_schedule` lacks `category` and is empty it is recreated per DEC-7; if it lacks `category` and has rows, startup stops with an error | AC-9: a database created by M01's schema starts under M02 and gets the new `fee_schedule`; a non-empty old one refuses to start |
| R-10 | `polyquack status` shows every target pair (or the filter) with its derived status, and the lines of M01 per platform | AC-10: the status output lists all target pairs with status |
| R-11 | A second writer holding a write transaction shorter than `busy_timeout` does not lose the minute's snapshot; a longer one leaves no invented row and the minute becomes a `not_collected` gap at the next tick (DEC-6) | AC-11 (TST-008): both cases pass against a real database file |

## Contracts and Risk Controls
- **`POLYQUACK_ASSETS`:** from required list with default `BTC` to optional filter (DEC-9). README updated.
- **`InstrumentInfo`:** gains lifecycle and base-tier parameter fields; adapters fill them.
- **`Platform`:** adds a paged funding-history call and a fees call; Polymarket adds a single-instrument lookup for `settlement`.
- **`fee_schedule`:** new column and primary key (DEC-7); migration R-9.
- **`gap`:** funding gaps move `open` → `closed_with_data` or `final` with `closed_at`; book and price gaps unchanged.
- **`funding_reading`:** `origin` gains `history`; still insert-only (INSERT OR IGNORE on the primary key).
- **Preserved:** insert-only triggers; M01 snapshot, price, reconnect and resync behavior; per-platform limiter and 0.8 s default; no credentials (NFR-011); no order endpoints (BR-011).
- **Risk:** the first backfill delays live REST calls by at most one request at a time (DEC-5); a test pins that history requests never overlap.

## Canonical Design Impact
- Manifest: `docs/spec/manifest.yaml`
- Update:
  - `docs/design/data/schema.dbml`: `fee_schedule.category` and its key (DEC-7); notes: pair status derived (DEC-10); funding gap transitions (DEC-11); `instrument_parameters` base tier and maintenance margin rule (DEC-1, DEC-8).
  - `docs/design/domain.md`: Pair lifecycle derivation (DEC-10); Gap transitions (DEC-11); instrument lifecycle signals per platform (DEC-3).
  - `docs/design/architecture/adr/ADR-002-storage.md`: two writers and DEC-6; status `Proposed`, awaiting the author's "Accepted by".
  - `docs/design/ux/flows.mmd` (F-001): recovery runs at startup and hourly, not on channel reconnect (funding is REST and unaffected by the channel).
  - `docs/design/review.md`: F-010 resolved (pending ADR acceptance); F-011 resolved for fees.
  - `README.md`: `POLYQUACK_ASSETS`, `completeness` command.
- Preserve: ADR-001, ADR-003 to ADR-006; `architecture.dsl`; `quality-attributes.md`; `prd.md`.
- Supersede only with approved decision: M01 deviation F-6 (Hyperliquid delisted rows dropped) is superseded by R-2, as FR-003 requires.

## Quality Obligations
- Tests (`pytest`, no network; fixtures trimmed from real responses where a probe exists):
  - TST-6 lifecycle (plan TST-006): R-2, DEC-3, DEC-10, both platforms.
  - TST-7 recovery (plan TST-007): R-4, R-5, DEC-11; a gap is never closed with an invented value; paging both directions.
  - TST-8 concurrency (plan TST-008): R-11.
  - TST-9 scale (plan TST-009): 100 simulated pairs over a simulated hour; every minute closes with a snapshot or gap per instrument and the hour with funding or gap; record the time per minute close.
  - Parameters and fees (R-6), migration (R-9), batched gaps (R-8), target-change exit (R-3), completeness report (R-7), filter (DEC-9), sequential history (DEC-5).
- Static/build: `uv run mypy --strict src tests`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`, `gitleaks detect --no-git --source . --redact`.
- QA on the VM (log in `vm-qa-log.md`): deploy; first-run log of subscriptions (ASM-2) and backfill without blocks (ASM-3); 7 days unattended; `polyquack completeness`; database file size.
- Coverage/mutation: each R-* has at least one test or a named VM check.

## Done When
On the VM, 7 days after deploying M02 with no manual intervention, `polyquack completeness` shows every target pair with at least 99% of hours with funding and 95% of minutes with a book snapshot on both platforms, `polyquack status` lists every pair with its status, the database holds dated `instrument_status`, `instrument_parameters` and `fee_schedule` rows, and the size of the database file is recorded. The tests and static gates pass.

## Change Surface
- Expected edits (medium confidence): `src/polyquack/config.py`, `cli.py`, `status.py`, new completeness module or function under `src/polyquack/`; `src/polyquack/ingestion/{models,platforms,service}.py`; `src/polyquack/storage/{db.py,schema.sql}`; a Hyperliquid fees data file inside the package; `tests/**` and new fixtures; `README.md`; the documents in Canonical Design Impact.
- Do not touch: `src/polyquack/ingestion/{book,feed,ratelimit}.py` behavior (except what a target list needs); insert-only triggers; `deploy/polyquack-ingestion.service` unless a test proves the restart contract needs it; `docs/discovery/**`; Evaluation and Publishing tables.

## Triggered Artifacts
| Artifact | Fired? | Reason |
|---|---|---|
| audit.md | Yes | reliability `strict` |
| plan.md | No | one writer, no staged rollout |
| execution.md | Yes | implemented by a subagent and verified by another; the 7-day run continues in a later session |

## Stop Conditions
- Work goes on `feat/all-pairs-ingestion/josueDev` created from `dev` after M01 is merged into `dev`; never commit without the author's confirmation; never on `master` or `dev`.
- ASM-2, ASM-3 or ASM-4 turn out false.
- A platform's response differs from `audit.md` or `probes/`.
- The implementation needs another schema change, a change to an accepted ADR other than ADR-002, or M03 to M06 behavior.
- The migration finds rows in an old `fee_schedule`.
- M02 is not accepted while the amended ADR-002 lacks the author's "Accepted by" (`manifest.yaml:48`).
