# M02 — All pairs are ingested 24/7 and recover on their own — Audit

Status: Ready for specification
Size: medium
Reliability: strict
Audit trigger: strict

## Evidence Facts
| Fact | Evidence |
|---|---|
| Entry point | `src/polyquack/cli.py:32` (`Service(db, platforms, config.assets).run()`); scope from `src/polyquack/config.py:15` (`POLYQUACK_ASSETS`, default `BTC`) |
| Covering tests | `tests/test_service.py`, `tests/test_storage.py`, `tests/test_parsers.py`, `tests/test_feed.py`, `tests/test_book.py`, `tests/test_ratelimit.py`, fixtures in `tests/fixtures/` |
| Consumers of each altered contract | `Config.assets` / `POLYQUACK_ASSETS`: `cli.py:32,45`, `service.py:37,43,59-60,103`, `status.py:7-10`, `db.py:73-75`, `README.md:32`, `tests/conftest.py:53-54`, `tests/test_service.py:192,211`. `Platform.instruments` / `InstrumentInfo` (`models.py:7`): `service.py:79-92`, `db.py:50-71`, `tests/test_parsers.py`. `Platform.funding`: `service.py:214-251`, `tests/test_parsers.py`, `tests/test_service.py`. `render_status` output: `cli.py:45`, `tests/test_service.py:186-211`. `gap` rows: `service.py:110-153,241-251`, `db.py:172-188`, `status.py`. Found with grep (`rg -n "assets\|instruments(\|funding(\|render_status\|insert_gap" src tests README.md`); no language server was used |

## Baseline
| Field | Value |
|---|---|
| Repository root | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `feat/btc-ingestion/josueDev` (M02 will branch from `dev` once M01 is merged) |
| Commit SHA | `6b1e30be467f9a56604e59cd78283653102dd7c0` |
| Working tree | Clean except this change folder |
| Relevant pre-existing changes | M01 implemented and accepted (`docs/changes/2026-10-28-M01-btc-ingestion/verification.md`), with AC-5 and AC-6 unverified on the VM; service running on the VM since 2026-10-30 18:39 UTC |
| Audit date | 2026-10-30 |

## Desired Outcome and Constraints
- Outcome: every paired pair (38 today) gets funding, book snapshots and prices continuously; instrument lifecycle, parameters and fees are stored with dates; missing funding is recovered from history; a completeness report shows NFR-002 and NFR-003 per pair (`docs/build/plan.md:120-166`).
- Included: FR-003, FR-005, FR-008, FR-009, FR-011, NFR-002, NFR-003, NFR-006, NFR-010, NFR-012, CON-009; F-010 (ADR-002 two writers) and F-011 (fees only).
- Excluded: evaluator (M03), dashboard (M05). Approved by the author at shaping: cost at most 20 USD a month; AC-011 tested locally with a simulated outage over recorded history; AC-013 from 7 days of unattended VM running.

## Current Behavior Trace
1. `cli.py:32` builds two platforms with one `RateLimiter` each (`cli.py:28-29`) and starts `Service.run` (`service.py:51-56`).
2. `_load_targets` (`service.py:58-62`) loads the configured assets once; `_ingest` (`service.py:64-77`) then builds one `BookFeed`, one funding loop per platform, one minute loop and one price loop. Targets, books and feeds are never rebuilt, so a pair created after startup is not ingested (inferred from the code).
3. `refresh_instruments` (`service.py:79-92`) runs at startup and daily: `upsert_instruments` (`db.py:50-60`, INSERT OR IGNORE of asset and instrument) and `pair_instruments` (`db.py:62-71`, INSERT OR IGNORE by asset). Nothing writes `instrument_status`, `instrument_parameters` or `fee_schedule` (`schema.sql:24-56`). Hyperliquid drops `isDelisted` rows (`platforms.py:169`); a vanished instrument is never marked.
4. Funding (`service.py:214-251`): one request per target for hour ±1 min (`platforms.py:107-120,172-185`), retried every 30 s until hour+15 min, then an `open` gap. Nothing re-fetches or closes it; `insert_funding` writes `origin='live'` only (`db.py:97-104`).
5. Restart and outage: `_pending` (`service.py:110-130`) turns elapsed intervals into `not_collected` gaps from `covered_until_ms` (`db.py:172-188`); funding ones are born `open`, book and price `final` (`service.py:24`). A new instrument with no coverage gets no backfill.
6. Observable result: the BTC pair only, as `polyquack status` shows (`status.py:7-22`).

## Relevant Surface
| Path / Area | Role | Evidence | Confidence |
|---|---|---|---|
| `src/polyquack/ingestion/service.py` | scheduler, targets, gaps, funding | trace above | High |
| `src/polyquack/ingestion/platforms.py`, `models.py` | instrument, funding, price, book adapters | `platforms.py:100-206`, `models.py:7` | High |
| `src/polyquack/ingestion/feed.py` | one websocket per platform, resync | `feed.py:19-92` | High |
| `src/polyquack/storage/db.py`, `schema.sql` | writes, coverage, schema and triggers | `db.py:29-188`, `schema.sql:24-119` | High |
| `src/polyquack/status.py`, `cli.py`, `config.py` | report and settings | `status.py:7-22`, `config.py:15-24` | High |
| `docs/design/architecture/adr/ADR-002-storage.md` | single-writer statement (F-010) | `ADR-002:15,18` | High |
| `tests/` | all current tests and fixtures | listed in Evidence Facts | High |

## Actual Problem / Change Location
Scope is fixed at startup from `POLYQUACK_ASSETS`, so all-pairs needs targets, books and channel subscriptions that follow the instrument refresh. Lifecycle, parameters and fees have tables but no parsing or writes. Funding has a one-hour fetch and no history call, and gaps are never closed. The completeness report does not exist.

## Platform Facts (probes in `probes/`, run 2026-10-30)
- Pairs: exact asset match gives 38 pairs (`m02_api_facts.out.json`, `paired_exact`), the number in `prd.md:263`. Polymarket 90 instruments, Hyperliquid 179 live.
- Polymarket instrument rows carry `close_only`, `max_leverage`, `min_notional`, `liquidation_fee`, `risk_tiers` (lower bound and max leverage), `fee_override` (null for BTC). No maintenance margin and no fee rates.
- Hyperliquid `meta` carries `universe` (`maxLeverage`, `marginTableId`, `onlyIsolated`, `isDelisted`) and `marginTables` (tiers of lower bound and max leverage). No close-only flag, no maintenance margin, no min notional, no liquidation fee, no fee rates (`hl_meta_keys.out.txt`).
- Polymarket funding history: 100 rows per page, newest first, `more: true` while older rows exist; paging by moving `end_timestamp` below the oldest row reached 2026-09-03T00:00Z for BTC in 14 pages, 1391 hourly rows, no missing hours (`pm_funding_paging.out.json`).
- Hyperliquid funding history: one call from 2026-09-03 returned 500 rows ascending, 2026-09-03T00:00Z to 2026-09-23T19:00Z, so it pages by moving `startTime` forward; about 3 pages per coin today.
- Backfill cost today (arithmetic): Polymarket 14 × 38 = 532 requests, about 7 min at 0.8 s; Hyperliquid about 114 requests. It grows by one page per 100 hours (Polymarket) or 500 hours (Hyperliquid) per pair.

## Contracts and Boundaries
| Contract / Boundary | Current Shape | Consumers | Change Risk |
|---|---|---|---|
| `POLYQUACK_ASSETS` / `Config.assets` | required list, default BTC | see Evidence Facts | Medium: meaning changes to "all pairs" or an optional filter |
| `InstrumentInfo` | `source_id`, `symbol`, `asset` | adapters, db, tests | Medium: needs lifecycle and parameter fields |
| `Platform.funding` | one hour ±1 min | service, tests | Medium: a history (range, paged) call is added |
| `gap` table | mutable, no triggers (`tests/test_storage.py:39`) | service, db, status | Medium: closing sets `status='closed_with_data'` and `closed_at` (`schema.dbml:117-122`) |
| `funding_reading` | insert-only, `origin` free text, always `live` | db, status | Low: `history` origin added (`schema.dbml:78`) |
| `instrument_parameters.maintenance_margin` | `NOT NULL` (`schema.sql:35`) | none yet | High: neither platform exposes it |
| SQLite writers | WAL, `busy_timeout=5000`, one transaction per write (`db.py:29-37`) | ingestion now, evaluator in M03 | Medium: ADR-002 says single writer (F-010) |
| Rate limiter | one FIFO lock per platform, no priority (`ratelimit.py:26-29`) | every REST call | Medium: a backfill delays minute price calls past the 60 s late mark (`service.py:173-174`) |

## Tests and Validation
| Test / Command | Covers | Gap | Prerequisite |
|---|---|---|---|
| `uv run pytest` (48 passed at M01) | M01 behavior | no lifecycle, history, closing, completeness, multi-pair or concurrency tests | none |
| `uv run mypy --strict src tests`, `uv run ruff check`, `uv run ruff format --check`, `gitleaks detect --no-git --source . --redact` | M01 gates | — | none |
| TST-006 to TST-009 (`plan.md:154-158`) | lifecycle, recovery, SQLite concurrency, 100-pair scale | not written | fixtures for history pages and lifecycle changes |
| 7-day VM run | AC-013, DB size (ADR-002) | not run | M02 deployed on the VM |

## Candidate Ownership
| Workstream | May Read | Candidate Write Set | Coupling / Conflict Risk |
|---|---|---|---|
| single writer, sequential | all of `src/`, `tests/`, design docs | `src/polyquack/**`, `tests/**`, `README.md`, `docs/design/architecture/adr/ADR-002-storage.md`, schema docs if a decision changes them | `service.py` and `db.py` are touched by every requirement; parallel writers would collide there |

## Integration and Generated-File Hotspots
| File / Area | Why Shared | Required Control |
|---|---|---|
| `service.py`, `db.py`, `schema.sql` | every M02 requirement lands here | one writer, sequential |
| `docs/site/polyquack-architecture.html` | generated from the design package | regenerate only if canonical docs change |
| `uv.lock` | dependencies | no new dependency expected |

## Supported Options
| Option | Evidence | Pros | Cons | Approval Status |
|---|---|---|---|---|
| Rebuild targets, books and channel subscriptions in-process after each instrument refresh that changes the set | `service.py:64-77,101` | no downtime | reconnect and resync of every book (about 30 s on Polymarket at 38 pairs, `feed.py:82-92`) | Not approved |
| Exit the process when the target set changes and let systemd restart it | `deploy/polyquack-ingestion.service` `Restart=always` | small change, reuses startup path | a few minutes become `not_collected` gaps per change | Not approved |
| Backfill through the same limiter, interleaved one request at a time with live work | `ratelimit.py` | no new mechanism | price calls can be late during the first backfill | Not approved |
| Backfill only from a low-priority path that yields to minute and hourly work | `ratelimit.py`, `service.py:155-212` | live readings unaffected | a priority mechanism in the limiter | Not approved |

## Material Decisions Needed
| ID | Decision | Why It Matters | Supported Options | Blocking? |
|---|---|---|---|---|
| DEC-Q1 | Source of `maintenance_margin` | `NOT NULL` column, FR-008 requires it, neither API exposes it | make it nullable and store what the API gives (max leverage, tiers); derive it from a documented platform rule (no rule verified here); defer FR-008's margin part | Yes |
| DEC-Q2 | Fee schedule source (F-011) | FR-009, AC-012; no fee rates in any probed public endpoint | load by hand from each platform's published schedule with an effective date; defer FR-009 | Yes |
| DEC-Q3 | Hyperliquid close-only | FR-003 and FR-008 need it; `meta` has no such flag | record only `active` and `delisted` for Hyperliquid; look for another public signal in a follow-up | Yes |
| DEC-Q4 | Picking up new or changed pairs at runtime | AC-008, AC-009 | in-process rebuild; exit and systemd restart (Supported Options) | Yes |
| DEC-Q5 | Backfill versus live REST work | NFR-003, late prices | interleave through the same limiter; low-priority backfill (Supported Options) | Yes |
| DEC-Q6 | ADR-002 amendment for two writers (F-010) | M03 adds the evaluator as a second writer; the ADR must be `Accepted by` the author | short transactions plus the existing 5 s `busy_timeout` and a rule for the evaluator's write size; another rule the author picks | Yes, for TST-008 |
| DEC-Q7 | Meaning of `POLYQUACK_ASSETS` | contract with README and tests | drop it (all pairs always); keep it as an optional filter, all pairs when unset | No |

## Assumptions
| ID | Assumption | Validation | Stop If False |
|---|---|---|---|
| ASM-1 | Polymarket funding history reaches 2026-09-03 for every pair, as for BTC | backfill test against recorded pages; first VM run | No: FR-005 says "oldest available" |
| ASM-2 | One Polymarket websocket accepts 38 `book::` channels and one Hyperliquid websocket 38 `l2Book` subscriptions | first VM run with all pairs | Yes, if a platform rejects them |
| ASM-3 | The 0.8 s pace holds during a 532-request backfill without 429 blocks | VM run log | Yes, if blocks repeat (NFR-005) |
| ASM-4 | A Polymarket instrument absent from the list is delisted; Hyperliquid `isDelisted` means delisted | probe of current lists | No: record as inferred |

## Contradictions and Risks
- `schema.sql:35` (`maintenance_margin NOT NULL`) and FR-008 versus the APIs, which expose no maintenance margin (DEC-Q1).
- M01 deviation F-6 (Hyperliquid delisted rows dropped, accepted for M01) contradicts FR-003, which needs delisted instruments recorded with a date; M02 must store them.
- ADR-002 (`ADR-002:15,18`) says one writer while the architecture has two (F-010).
- FR-009 and F-011: no public fee rates were found; Polymarket's `fee_override` exists but is null for BTC.
- Risk: every reconnect resyncs every book sequentially; at 38 pairs that is about 30 s on Polymarket, likely costing one book minute per reconnect (inferred).
- Risk: `_pending` writes one transaction per elapsed interval; after a long outage at 38 pairs this is thousands of single-row commits (inferred).

## Do Not Touch
- The insert-only triggers on reading tables (`schema.sql:106-119`).
- M01 behavior already accepted (F-4 to F-12), except where an M02 requirement overrides it (F-6).
- `docs/discovery/spikes/**`.

## Author Decisions (2026-10-30)
- DEC-Q1, DEC-Q2, DEC-Q3: research the official documentation of both platforms first; derive maintenance margin from a published rule if one exists, load fees by hand with an effective date, and record Hyperliquid as `active`/`delisted` unless its docs show a close-only state.
- DEC-Q4: the process exits when the target set changes and systemd restarts it.
- DEC-Q5: backfill runs as one sequential task through the same per-platform limiter.
- DEC-Q6: ADR-002 amendment with short transactions (under 1 s), the existing 5 s `busy_timeout`, and an ingestion write that still fails becomes a gap; the amended ADR starts `Proposed`.
- DEC-Q7: not asked; default proposed for the spec is an optional filter, all pairs when unset.

## Documentation Findings for DEC-Q1 to DEC-Q3 (2026-10-30)
Researcher subagent over official docs; wording comes from fetch summaries, so treat quotes as approximate.
- Maintenance margin, Hyperliquid: per tier, the maintenance margin rate is half the initial margin rate at that tier's max leverage, `0.5 / maxLeverage` (https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margin-tiers, `.../trading/liquidations`, `.../trading/contract-specifications`). Inputs: `meta.marginTables`.
- Maintenance margin, Polymarket: flat per market, `MMR = 0.5 / MaxLeverage`, independent of tier (https://docs.polymarket.com/perps/learn-about-trading/margin). The researcher reports the docs' sample responses may not match the formula; not checked against live data.
- No public endpoint returns a maintenance margin on either platform.
- Fees, Polymarket: public `GET /v1/info/fees` (https://docs.polymarket.com/api-reference/get-fees) answered 200 without auth (`probes/pm_fees.out.txt`): `fee_schedule[]` per `instrument_type` and `category`, with base rates and `tiers[]` by `min_volume_30d` (equity base: taker 0.0004, maker 0.000125). The output shown was cut at 2500 characters, so other categories were not inspected. `fee_override` is not documented.
- Fees, Hyperliquid: published table only (https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees; tier 0 taker 0.045%, maker 0.015%, 14-day volume tiers, staking and referral discounts). The only API is `userFees`, which needs an address, so the fees are loaded by hand.
- Hyperliquid close-only: no market-level close-only state found; `isDelisted` is the only public signal; reduce-only is a per-order flag only.
- Polymarket lifecycle: `close_only` means user orders must be reduce-only. Delisted or disabled instruments leave the list; a permanently settled one returns a `settlement` object when queried by `instrument_id` (https://docs.polymarket.com/api-reference/get-instruments).
- Hyperliquid min notional: $10 per a search snippet of the error-responses page, not fetched; liquidation fee: no clearance fee on liquidations per the liquidations page, so `liquidation_fee` stays null.

New contradictions:
- `fee_schedule` (`schema.dbml:62-71`, `schema.sql:49-56`) has no category, while Polymarket rates differ by `category`.
- `instrument_parameters` holds one `max_leverage` and one `maintenance_margin`, while Hyperliquid's rates differ per notional tier.

Author decisions on these (2026-10-30): add a nullable `category` column to `fee_schedule` (null for Hyperliquid); `instrument_parameters` keeps the base tier only (first tier).

## Recommended Next Step
Write the spec.
