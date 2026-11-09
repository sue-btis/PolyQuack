# M01 — One pair (BTC) is ingested end to end on the VM — Audit

Status: Ready for specification
Size: medium
Reliability: strict
Audit trigger: strict

## Evidence Facts
| Fact | Evidence |
|---|---|
| Entry point | None: Polyquack has no code. The tree only contains `docs/` (`ls Polyquack/`, 2026-10-28). The behavior is born in this change; its canonical flow is `docs/design/ux/flows.mmd:2-23` (F-001). |
| Covering tests | none |
| Consumers of each altered contract | `schema.dbml` Ingestion tables (they are created; `gap.ends_at` becomes nullable per F-008): no code consumers. Documentary consumers: `docs/design/domain.md:57` (Gap states), `docs/design/ux/flows.mmd:11,17`, FR-028 in `docs/product/prd.md`. Evaluation tables that reference `pair` and `platform` (`schema.dbml:126-249`) have no code yet. — grep `grep -rn "gap\|ends_at" docs/design docs/product` |

## Baseline
| Field | Value |
|---|---|
| Repository root | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | n/a — not a git repository (`git status` → "not a git repository") |
| Commit SHA | n/a |
| Working tree | n/a; only `docs/` |
| Relevant pre-existing changes | None. `docs/discovery/spikes/` has heavy files (`DQ-006-ladders/events.json`, `cache/` folders) that the plan asks to exclude from the repository. |
| Audit date | 2026-10-28 |

## Desired Outcome and Constraints
- Outcome: on the VM, a service stores hourly funding, the mark and index price per minute and one book snapshot per minute for BTC on Polymarket Perps and Hyperliquid; the holes are recorded as gaps; a command shows the latest readings and the gaps (`docs/build/plan.md`, M01).
- Included: FR-001, FR-002, FR-004, FR-006, FR-007, FR-010; NFR-001, NFR-004, NFR-005, NFR-013; BR-001, BR-007; CON-004, CON-008, CON-010; AC-001 to AC-007; TST-001 to TST-005; F-006 and F-008 from the ledger.
- Excluded: the other pairs, history recovery, instrument lifecycle, parameters and fees (M02); evaluator, dashboard and exporter (M03 to M06).

## Current Behavior Trace
1. There is no code. The reference flow is `flows.mmd` F-001: startup → instruments over REST → pair → (history: M02) → subscribe to books → resync over REST → each minute snapshot or gap; each minute batched prices or gap; each hour funding or gap; a disconnection opens a gap and reconnects.
2. The only code precedents: the probes `docs/discovery/spikes/DQ-E-funding/probe.py:59,71,108-109` (REST endpoints for funding and instruments of both platforms, with no live channel or book).

## Relevant Surface
| Path / Area | Role | Evidence | Confidence |
|---|---|---|---|
| `docs/design/data/schema.dbml:8-124` | Schema of the 11 Ingestion tables | direct reading | High |
| `docs/design/domain.md` (Reading, Gap, Book snapshot) | Invariants: insert-only, never fill in, book gap final at the end of the minute | direct reading | High |
| ADR-001, 002, 003, 004, 006 | Local Linux VM; SQLite WAL; strictly typed Python; live channel + REST; batched prices | all `Accepted` with "Accepted by" | High |
| `docs/design/architecture/quality-attributes.md` | NFR-004 (supervision by the VM's system), NFR-005 (one rate control per platform, initial 0.8 s on Polymarket) | direct reading | High |
| `docs/product/prd.md:351` | PD-005 to correct (F-006) | `docs/design/review.md:195-208` | High |
| Hyperliquid and Polymarket Perps APIs | External sources | probes from this audit and research of the official documentation (below) | High for what was measured; Medium for what is documented |

## Actual Problem / Change Location
All the code is new. The existing design change is limited to `schema.dbml` (`gap.ends_at` nullable, F-008) and `prd.md:351` (F-006). The real problem is external: **the Hyperliquid book channel does not deliver depth up to 0.5%** (see Contradictions), which clashes with FR-006, with the `*_levels` column "up to 0.5%" (`schema.dbml`, `book_snapshot`) and with the stop condition of M01 in `plan.md`.

### Measured evidence (2026-10-28, probes in `probes/`)
- **Hyperliquid, BTC, `POST /info {"type":"l2Book"}`:** 20 levels per side at full precision.
  - Full precision (`nSigFigs` null or 5): the 20 levels cover 0.024% to 0.028% of the mid price; best bid/ask 81008/81009.
  - `nSigFigs=4`: covers 0.24%, with steps of 10 USD (best bid 81000, the exact price is lost).
  - `nSigFigs=3`: covers 2.4%, with steps of 100 USD.
  - Documentation: "Returns at most 20 levels per side"; the `l2Book` WS channel gives 20 levels (5 with `fast`) — https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint and .../websocket/subscriptions.
- **Polymarket Perps, BTC (`instrument_id` 6, `BTC-USD`, `funding_interval` "1h"), `GET /v1/info/book`:**
  - 20 levels cover 0.05% to 0.08%; 50 levels cover 1.2% / 2.9%; 100 levels cover ~6%.
  - The WS channel `book::{iid}` gives 20 levels by default and `book::{iid}::50` gives 50 — https://docs.polymarket.com/api-reference/wss/perps-book.md. With `::50` 0.5% is reached in this measurement; it is not guaranteed at all times.

## Contracts and Boundaries
| Contract / Boundary | Current Shape | Consumers | Change Risk |
|---|---|---|---|
| `book_snapshot` (`schema.dbml:84-97`) | best bid/ask, notional volume up to 0.5% per side, JSON levels "up to 0.5%" | M03 (order book walk FR-021), M04 | High: the content depends on DEC-Q1 |
| `gap` (`schema.dbml:111-124`) | `ends_at` `not null` with status `open` | M02, M04, M05 | Medium: F-008 resolves it |
| `funding_reading` (`schema.dbml:73-82`) | `rate` per hour, `source_time`, `origin` live/history | M03 | Medium: see ASM-3 |
| `price_reading` (`schema.dbml:99-109`) | mark, index, nullable `source_time` (Hyperliquid) | M04 | Low |
| Insert-only reading tables | rule in `schema.dbml:1-6` and `domain.md`; TST-005 asks that they reject UPDATE/DELETE | all | Medium: requires SQLite triggers |
| Platform limits (NFR-005) | Hyperliquid: 1200 weight/min per IP; `l2Book` 2, other info 20; WS 10 connections, 1000 subscriptions. Polymarket Perps: 1000 tokens/min per IP; `tickers` 2, `book` 2-20, `funding` 10; WS 50 connections, 100 subscriptions per connection. Sources: .../rate-limits-and-user-limits and https://docs.polymarket.com/api-reference/perps/rate-limits.md | Ingestion | Low for one pair |
| WS heartbeat | Both platforms close after 60 s without messages; ping documented on each | Ingestion | Low |
| Startup and restart (NFR-004) | "Services supervised by the VM's system" (`quality-attributes.md`) | VM | Low; see ASM-5 |

## Tests and Validation
| Test / Command | Covers | Gap | Prerequisite |
|---|---|---|---|
| TST-001 pairing | AC-001 | — | instrument fixtures (can come from real responses) |
| TST-002 in-memory book | AC-003, AC-005 | **Assumes incremental updates with a sequence.** Both channels send full snapshots (HL: "snapshot feed"; PM: each push "replaces the prior state"). The validity of the book has to be reformulated (DEC-Q3). | DEC-Q3 |
| TST-003 gaps | BR-001 | — | — |
| TST-004 rate control on 429 | NFR-005 | — | — |
| TST-005 insert-only | NFR-001 | — | triggers in the schema |
| Type checker, linter, secrets scan | M01 gates (ADR-003, NFR-011) | No tool is chosen in the documents | the spec fixes them |
| 2 h run on the VM, network cut, restart | AC-002 to AC-007 | manual; requires the VM | VM access |

## Candidate Ownership
| Workstream | May Read | Candidate Write Set | Coupling / Conflict Risk |
|---|---|---|---|
| Single (one writer in sequence) | `docs/` | new Python code, SQLite schema, service unit, tests, `pyproject` and lockfile, `.gitignore`; `docs/design/data/schema.dbml`; `docs/product/prd.md:351`; documents changed by DEC-Q1 | Low: there is no prior code. Splitting clients by platform would require freezing the snapshot contract first, which depends on DEC-Q1. |

## Integration and Generated-File Hotspots
| File / Area | Why Shared | Required Control |
|---|---|---|
| `schema.dbml` and the schema SQL script | Contract from M02 to M06 | The SQL is derived from the approved DBML; a single owner |
| `pyproject.toml` and lockfile | dependencies | a single writer |
| `.gitignore` | exclude the database, local configuration and heavy data from `spikes/` | create before the first commit |

## Supported Options
DEC-Q1 — depth up to 0.5% on Hyperliquid:

| Option | Evidence | Pros | Cons | Approval Status |
|---|---|---|---|---|
| A. Two `l2Book` subscriptions per instrument on Hyperliquid: full precision (best bid/ask and 20 exact levels) and `nSigFigs=3` (aggregated, covers ~2.4%) for the volume at 0.5% and the far levels | measurement above; 2 of 1000 subscriptions per instrument | Meets FR-006 with data from the source; follows ADR-004 (live channel) | The volume at 0.5% comes from steps of 100 USD (~0.12%): the step at the edge cannot be split without inventing data. Two level resolutions have to be stored and declared which is which: changes `book_snapshot` and the definition of Book snapshot. Snapshots from two different messages. | Not approved |
| B. Store only the 20 exact levels and the volume within what they cover, marking how much the snapshot covers (e.g., a coverage column) | measurement above | Simple; no approximated data; E1's 1,000 USD walk on BTC fits comfortably within 20 levels | Does not meet FR-006 on Hyperliquid: changes product behavior and requires a new row in PRD §15 and a change to FR-006 and the schema | Not approved |
| C. Order book over REST with variable `nSigFigs` | documentation | — | Same cap of 20 levels; contradicts ADR-004 (which rejected per-minute REST) | Not approved |

On Polymarket Perps, using `book::{iid}::50` covers 0.5% in the measurement without changing any contract.

## Material Decisions Needed
| ID | Decision | Why It Matters | Supported Options | Blocking? |
|---|---|---|---|---|
| DEC-Q1 | How to meet (or change) the volume and levels at 0.5% on Hyperliquid | Defines the content of `book_snapshot`, M03's order book walk and M01's stop condition | A, B (C is not recommended) | Decided: **B**. Decided by: the author, 2026-10-28, «B». Requires a new row in PRD §15 and a change to FR-006 and `book_snapshot`. |
| DEC-Q2 | Unit of `*_notional_05` and of the level quantities | Correction: `schema.dbml` (`book_snapshot.bid_notional_05`) does declare it: "accumulated notional". The `*_levels` quantities come in asset units, as the source gives them | Volume = sum of price × quantity in quote currency; levels as the source gives them | No: resolved by the schema |
| DEC-Q3 | When the in-memory book is "valid" for taking the minute's snapshot | With full snapshots there is no sequence jump; TST-002 must be reformulated | Valid if the connection stayed alive since the last snapshot or REST resync; or valid only if a snapshot arrived within the minute | No: the spec can fix the first |

## Assumptions
| ID | Assumption | Validation | Stop If False |
|---|---|---|---|
| ASM-1 | The funding rate of both platforms is hourly | PM: the documentation says hourly fraction with a cap of 4%/h (https://docs.polymarket.com/perps/learn-about-trading/funding.md). HL: hourly payment documented; unit of `fundingRate` not found. Measured hint: HL BTC `funding` = 0.0000125, equal to PM's hourly base rate | Yes, if HL turns out to use another unit (the column says "per hour") |
| ASM-2 | Funding `source_time` = `time` of `fundingHistory` (HL) and `timestamp` of `/v1/info/funding` (PM), in ms | Compare with the payment hours during the 2 h run | No; it is documented |
| ASM-3 | M01's hourly funding is read from the history of the hour already paid (not from the estimated rate in tickers) and stored with `origin = live` | The documentation does not say whether the tickers' `funding_rate` is the estimated or the paid one | No |
| ASM-4 | The REST resync after reconnection (ADR-004) is kept even though the channels send full snapshots | ADR-004 requires it; low cost | No |
| ASM-5 | The VM has systemd and a compatible Python version (local: Python 3.14.3) | Check on the VM before implementing | Yes, if there is no service supervisor |
| ASM-6 | Snapshots are cut at the UTC minute with the source time of the last message (`time` HL, `ts` PM) as `source_time` | Schema `book_snapshot.minute` and `source_time` | No |

## Contradictions and Risks
- **Hyperliquid does not deliver 0.5% depth at full precision** (measured). It clashes with FR-006 and with `book_snapshot.*_levels`. It is M01's stop condition: "the live channel of some platform does not allow rebuilding the book". Option A avoids changing ADR-004; B changes the product.
- **`plan.md`'s TST-002 assumes incremental updates with a sequence**; both channels send full snapshots. Polymarket's `sq` and its `resync` events are not documented.
- **Polymarket Perps does publish limits** (1000 tokens/min per IP), against ADR-004 ("does not publish limits") and `quality-attributes.md` (initial pace of 0.8 s because the limit was not published). It does not block: the 0.8 s pace stays within the limit. Correcting those texts changes an accepted ADR, so it goes as `Proposed` or as a note in the Canonical Design Impact.
- F-008 open: `gap.ends_at` `not null` with status `open` (`schema.dbml:117,119`).
- F-006 open: `prd.md:351` makes `check-package.mjs` fail, which lives in a skill's directory and not in the repository (`review.md:25,36`).
- Risk: Polymarket Perps is two months old; its channels may change (ADR-004, Revisit Trigger).
- Risk: Polyquack is not a git repository; the plan requires `git init` and `.gitignore` before starting, and the author's rule requires a `feat/...` branch and their confirmation before each commit.

## Do Not Touch
- `docs/discovery/` (discovery evidence; only the heavy files are excluded from the repository).
- Evaluation and Publishing tables and concepts of `schema.dbml`.
- Accepted ADRs, except for a `Proposed` version that the author accepts.
- The other MINOR findings in the ledger (F-007, F-010 to F-015): they belong to other milestones.

## Recommended Next Step
DEC-Q1 decided (B). Write `spec.md` with `writing-change-spec`, fixing DEC-Q2 and DEC-Q3 with their recommended option unless the author says otherwise. It remains for M02 to measure whether Hyperliquid's 20 levels are enough to walk 1,000 USD on the small coins.
