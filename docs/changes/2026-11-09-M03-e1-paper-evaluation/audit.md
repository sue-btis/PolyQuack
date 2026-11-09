# M03 — E1 decides every hour on paper and collects funding without seeing the future — Audit

Status: Ready for specification
Size: medium
Reliability: strict
Audit trigger: strict (also: no entry point exists yet)

## Evidence Facts
| Fact | Evidence |
|---|---|
| Entry point | none yet. New commands hang off `src/polyquack/cli.py:38` (`command` with `choices=("run","status","completeness")`, no subparsers); writer and read-only `Database` opening at `cli.py:23`, `:46` |
| Covering tests | none for evaluation. Reusable: `tests/conftest.py:21` (`T0`), `:30-32` (`db` fixture), `:35-38` `seed_btc`, `:62-67` `seed_pairs`; direct `db.insert_funding`, `insert_snapshot`, `insert_price`, `sync_fees` for seeding |
| Consumers of each altered contract | `schema.sql` (gains evaluation tables): created by every writer open (`db.py:62-65`), so both `polyquack run` and the new evaluator apply it; `cli.py` `command` choices: README:35-61, `tests/test_completeness.py` CLI test; `Polymarket` fee loading (`platforms.py:163-171`) and `sync_fees` (`db.py:211-229`) if a crypto fee file is added. Found with grep (`rg -n "choices=|executescript|sync_fees|fees\(" src tests README.md`); no language server |

## Baseline
| Field | Value |
|---|---|
| Repository root | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `dev` (M03 will work on `feat/e1-paper-evaluation/josueDev`) |
| Commit SHA | `e8f585396709d82f1faa047938b6010b48cdd81c` (M02 merged, PR #3) |
| Working tree | Clean |
| Relevant pre-existing changes | M02 accepted 2026-11-09 with open limitations L-5 (Polymarket crypto fee, to M03) and L-6 (database growth, separate change). The VM runs M02 and holds 7+ days of data for 38 pairs |
| Audit date | 2026-11-09 |

## Desired Outcome and Constraints
- Outcome: the author preregisters E1 from the command line; every hour Polyquack computes the funding spread per pair, decides open, hold, reverse, close or no_action, simulates trades by walking the stored book with taker fees, and credits funding with the accrual rule; nothing ever uses data later than the decision (`docs/build/plan.md:179-237`).
- Included: FR-012, FR-013, FR-014, FR-019 to FR-022, FR-026, NFR-008, BR-004 to BR-008, BR-011, CON-006; F-007, F-012, F-014; L-5 of M02 (crypto fee).
- Excluded (plan M04): basis, liquidation distance and liquidation (FR-023 to FR-025, `position_measurement`, F-013), verdict and exclusion of pairs by gap limits (FR-018, PD-021, `excluded_pair`, `verdict`), re-evaluation runs (`run.mode = reevaluation`).
- Approved at shaping (2026-11-09): rule shape is a moving average of the spread over the last N hours with hysteresis (enter above an entry threshold, exit below a smaller exit threshold, reverse on a sign change beyond the entry threshold); all 38 non-delisted pairs; Polymarket crypto fee from a versioned file checked against the official docs; maximum book snapshot age 2 minutes, otherwise `no_action` and a gap. Parameter values are preregistered by the author before the first run (CON-006).

## Current Behavior Trace
1. Ingestion stores funding for hour H with `source_time` a few ms after H (VM status: `2026-11-02T16:00:00.051Z`); it tries from H+1 min to H+15 min, then opens a gap; recovery runs at H+20 min (`service.py:22-29`, `:296-297`, `:400`).
2. A funding reading belongs to hour H by rounding `floor_to(t + HOUR_MS//2, HOUR_MS)` (`db.py:273`, `:302`, `:421`).
3. Book snapshots: one per minute and instrument, levels `[[price, quantity], ...]` as JSON within ±0.5% of the mid, quantity in asset units, plus `*_notional_05` and reach (`book.py:40-65`, `db.py:326-343`).
4. Fees: `fee_schedule` by platform, category and tier (`schema.sql:49-57`); Polymarket's API returns only `equity` (M02 F-14); Hyperliquid from `hyperliquid_fees.json` (`platforms.py:36`, `:260-271`).
5. No evaluation tables, code or tests exist (`schema.sql:3-103`).

## Relevant Surface
| Path / Area | Role | Evidence | Confidence |
|---|---|---|---|
| `src/polyquack/cli.py` | new `preregister`, `evaluate` (and variant listing) commands | `cli.py:38-65` | High |
| `src/polyquack/storage/schema.sql`, `db.py` | evaluation tables, immutability trigger, read helpers | no readers for funding, snapshots, fees as-of a time (`db.py`) | High |
| new evaluator module under `src/polyquack/` | decision rule, book walk, accrual | none exists | High |
| `src/polyquack/ingestion/platforms.py`, a Polymarket crypto fee file | L-5 | `platforms.py:163-171`, `:260-271` | Medium |
| `deploy/` | a `oneshot` unit plus a `.timer` for the hourly run | `deploy/polyquack-ingestion.service` | Medium |
| `tests/` | TST-010 to TST-013 and the rest | `conftest.py` | High |

## Canonical Design Facts
- `schema.dbml:130-243` (Evaluation area): `method`, `variant` (`preregistration` JSON, `registered_at`, `first_run_at`; a trigger freezes the preregistration once `first_run_at` is set, `:144`), `run` (`mode` live|reevaluation, `status`), `decision` (`action` open|hold|reverse|close|no_action, `data_until` "must be <= hour", `funding_spread` null if a rate is missing; PK run, pair, hour), `paper_position` (`polymarket_side`, `notional_per_leg`, `leverage`, `opened_at`, `closed_at`, `status` open|leg_liquidated|closed), `paper_trade` (`kind`, `hour`, `side`, `avg_price`, `best_price`, `quantity`, `fee`, `slippage`, `snapshot_minute`), `paper_funding_payment` (PK position, platform, source_time; `amount` positive = collected).
- `domain.md:86`: a leg receives payments with source time strictly after its opening and at most its close.
- `flows.mmd:27-40` (F-002): after storing the funding of t → accrual → per non-excluded pair rates of t → no_action if one is missing → spread → rules with data up to t → walk the previous snapshot → record trade.
- `architecture.dsl:16`: the Evaluator runs hourly as a scheduled task and command line; ADR-002 amendment (accepted 2026-11-02): two writers, short transactions, evaluator writes in small batches, 5 s busy timeout.
- `quality-attributes.md:13-14`: rounding to cents in one place (NFR-007); NFR-008 tests `data_until <= hour` and no payment at or before the opening.
- PD-014 1,000 USD per leg, PD-015 2x (`prd.md:360-361`).

## Contracts and Boundaries
| Contract / Boundary | Current Shape | Consumers | Change Risk |
|---|---|---|---|
| `schema.sql` | ingestion tables only | every writer open | Medium: evaluation tables added; DDL idempotent (`IF NOT EXISTS`) |
| Ingestion data | read-only to Evaluation (`domain.md:123-125`) | evaluator | Low: the evaluator must never write ingestion tables |
| `variant.preregistration` | not implemented | evaluator, future verdict (M04) | High: frozen after the first run (FR-013); format fixed here |
| SQLite writers | ingestion only today | ingestion, evaluator | Medium: second writer per ADR-002 amendment |
| CLI commands | `run`, `status`, `completeness` | README, VM operator | Low |

## Contradictions and Risks
- C-1 (timing, blocking): BR-004 and `decision.data_until <= hour` say a decision at t uses data up to t, while F-002 uses the funding "of t" and that payment's `source_time` is a few ms after the hour (`…:00.051Z`). With the decision instant equal to the hour, the decision could never use the payment of its own hour. Nothing in the docs fixes the decision instant relative to ingestion (funding deadline H+15 min, recovery H+20 min).
- C-2 (F-007): `domain.md:21` and `:83`, `:114-115` keep `reversed` as a position state and omit `no_action`; `schema.dbml:177`, `:194` have `no_action` and no `reversed`. The schema reading (reverse = close, then open the opposite) needs no link column.
- C-3 (F-012): no maximum snapshot age in the domain; the author chose 2 minutes; `paper_trade` stores `snapshot_minute` only, so the snapshot's `source_time` is read by joining `book_snapshot` on (instrument, minute), which is enough for F-014.
- C-4 (depth): stored levels stop at ±0.5% of the mid (`book.py:6`, `:51-54`); a side whose `*_notional_05` is below 1,000 USD cannot be walked for the full size, and nothing may be estimated (`book.py:41-45`, DEC-1 of M01).
- C-5 (exclusion): F-002 loops over "non-excluded" pairs, but exclusion (PD-021) is computed only at the horizon (M04).
- C-6 (FR-026): `paper_trade` has no decision reference; it is reachable by (run, pair, hour).
- C-7 (determinism): `real` columns while NFR-007 asks for cent rounding in one place.
- C-8 (missed hours): nothing says what happens if the hourly run does not execute (VM down, timer missed).
- Risk: the second writer re-runs `schema.sql` and the `fee_schedule` migration check on open (`db.py:62-69`); harmless (idempotent) but takes the write lock briefly.

## Supported Options
| Option | Evidence | Pros | Cons | Approval Status |
|---|---|---|---|---|
| Decision instant H+21 min: hour H's decision uses data with `source_time` ≤ H+21 min (funding of H, snapshot of minute H+20), `decision.hour` = that instant | C-1; recovery at H+20 min | the funding of H and its recovery are visible; accrual works as the domain says (opened at the decision gets H+1 onward; closed at it gets H) | the decision lags the hour by 21 min | Not approved |
| Decision instant H exactly, using the previous hour's funding | BR-004 literally | no lag | contradicts F-002 ("rates of hour t") | Not approved |
| Insufficient depth: `no_action` with a gap cause | C-4, M01 DEC-1 | nothing invented | pairs with thin books trade less | Not approved |
| Insufficient depth: trade the depth available | C-4 | more trades | legs with different notional break BR-006 | Not approved |
| Missed hours: catch up every elapsed hour on the next run with that hour's cutoff | C-8 | complete hourly record, deterministic | a catch-up hour sees no newer data anyway, by source time | Not approved |
| Missed hours: record them as `no_action` with a cause | C-8 | simpler | loses decisions that data allowed | Not approved |

## Material Decisions Needed
| ID | Decision | Why It Matters | Supported Options | Blocking? |
|---|---|---|---|---|
| DEC-Q1 | Decision instant within the hour (C-1) | defines `data_until`, accrual and NFR-008 | H+21 min; H with previous funding | Yes |
| DEC-Q2 | What to do when the book within ±0.5% does not cover 1,000 USD (C-4) | trade simulation, BR-006 | `no_action` with cause; partial | Yes |
| DEC-Q3 | Missed hourly runs (C-8) | completeness of the decision record | catch up; mark `no_action` | Yes |
| DEC-Q4 | Exclusion in M03 (C-5) | which pairs decide hourly | all non-delisted pairs hourly, exclusion applied at the verdict (M04) | No (spec default, consistent with shaping) |
| DEC-Q5 | Reverse modelling (C-2, F-007) | positions and trades | close + open in the same decision; domain updated | No (spec default) |

## Assumptions
| ID | Assumption | Validation | Stop If False |
|---|---|---|---|
| ASM-1 | Both rates of hour H are normally stored before H+21 min | VM data: funding received a few seconds to minutes after H | No: a missing rate gives `no_action` |
| ASM-2 | Polymarket publishes a taker fee that applies to crypto perpetuals | official docs, read by the implementer | Yes |
| ASM-3 | A systemd timer running a `oneshot` evaluator coexists with the ingestion service on the same database | ADR-002 amendment; VM run | Yes, if lock waits lose minutes |

## Candidate Ownership
| Workstream | May Read | Candidate Write Set | Coupling / Conflict Risk |
|---|---|---|---|
| single writer, sequential | all of `src/`, `tests/`, design docs | new evaluator module, `cli.py`, `storage/{db.py,schema.sql}`, a Polymarket crypto fee file and `platforms.py` fee loading, `deploy/` (new unit and timer), `README.md`, tests, canonical docs | `db.py` and `schema.sql` shared with ingestion |

## Do Not Touch
- Ingestion tables' contents and the insert-only triggers; the evaluator only reads them.
- M02 ingestion behavior and `deploy/polyquack-ingestion.service`.
- `docs/discovery/**`.

## Author Decisions (2026-11-09)
- DEC-Q1: the decision for hour H is taken at H+21 min and uses data with `source_time` at or before that instant (the funding of H, the snapshot of minute H+20 or H+19).
- DEC-Q2: when the stored book of either leg does not cover the reference size, the decision is `no_action` with a recorded cause; nothing is estimated.
- DEC-Q3: missed hourly runs are caught up on the next run, each hour with its own cutoff.
- DEC-Q4 and DEC-Q5 not asked; the spec takes the defaults: all non-delisted pairs decide hourly (exclusion at the verdict, M04); reverse is close plus open in the same decision.

## Recommended Next Step
Write the spec.
