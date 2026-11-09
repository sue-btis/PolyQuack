# M03 — E1 decides every hour on paper and collects funding without seeing the future

Status: Ready for implementation
Approved by: the author, 2026-11-09, «Apruebo» (includes DEC-11)
Size: medium
Reliability: strict
Implementation effort: high (second SQLite writer next to ingestion; no-future-data correctness)
Parent: none (builds on `docs/changes/2026-10-30-M02-all-pairs-ingestion/`, accepted 2026-11-09)

## Goal
The author preregisters E1 from the command line. Every hour, for each non-delisted pair, Polyquack computes the funding spread, decides with E1's preregistered rule, simulates the paper trades by walking the stored order book with the taker fee, and credits funding to open legs with the accrual rule. No decision uses data with a source time later than its decision instant.

## Evidence and Current Behavior
See `audit.md` (2026-11-09, commit `e8f5853`). Summary:
- Entry point: none; new commands join `src/polyquack/cli.py:38`.
- Covering tests: none for evaluation; fixtures in `tests/conftest.py` are reusable.
- Consumers of altered contracts: `audit.md` Evidence Facts (grep).
- Funding of hour H arrives with `source_time` a few ms after H, by H+15 min at the latest, with recovery at H+20 min; book snapshots keep levels within ±0.5% of the mid; Polymarket's fee API returns only `equity`; no evaluation tables exist.

## Scope
Included:
- Evaluation tables in `schema.sql` per `schema.dbml` (`method`, `variant`, `run`, `decision`, `paper_position`, `paper_trade`, `paper_funding_payment`) with the changes in Contracts; the preregistration immutability trigger.
- Commands `preregister`, `evaluate`, `variants`; an hourly systemd timer for `evaluate`.
- E1 decision rule, book walk, fees, accrual, catch-up of missed hours.
- A Polymarket crypto fee data file (closes M02 limitation L-5); F-007, F-012, F-014.

Excluded:
- Basis, liquidation distance and liquidation (FR-023 to FR-025, `position_measurement`, F-013), pair exclusion by gap limits and the verdict (FR-018, PD-021, `excluded_pair`, `verdict`), re-evaluation runs (`run.mode = reevaluation`), the dashboard: M04 and later.
- Any order or account endpoint (BR-011).
- Any write to ingestion tables.

## Decisions and Assumptions
Approved by the author (shaping and `audit.md`, 2026-11-09):
- **DEC-1 (rule shape):** each decision computes `m`, the mean of the spreads of the hours in the window `(H − N, H]` that have a spread (missing hours are skipped, never zero); entry threshold `E` and exit threshold `X` with `0 ≤ X < E`. N, E and X are preregistered by the author.
- **DEC-2 (pairs):** every pair whose derived status is not `delisted` decides every hour.
- **DEC-3 (Polymarket crypto fee):** a versioned package data file, like `hyperliquid_fees.json`, with category `crypto`, base tier taker and maker and their effective date, read from the official Polymarket docs by the implementer; loaded into `fee_schedule` with the other Polymarket fees.
- **DEC-4 (snapshot age, F-012):** a snapshot is usable only if its `source_time` is at or before the decision instant and at most 120 s older than it.
- **DEC-5 (decision instant):** the decision for hour H is taken at `H + 21 min`; that instant is `decision.hour` and the cutoff for every reading (`source_time ≤ cutoff`).
- **DEC-6 (thin book):** if the stored levels of either leg cannot fill the trade, the decision is `no_action` with a cause; nothing is estimated.
- **DEC-7 (missed hours):** each `evaluate` decides every due hour not yet decided, oldest first, each with its own cutoff.

Spec decisions (derived from the domain and schema):
- **DEC-8 (actions):** `hold` keeps the current state, flat or in a position; `no_action` means the hour could not be decided and records why; `reverse` closes the position and opens the opposite one in the same decision (resolves F-007).
- **DEC-9 (sides):** spread `s = PM rate − HL rate` (BR-008); a positive rate means longs pay (BR-007). For `m > 0` the position that collects is short on Polymarket and long on Hyperliquid; for `m < 0` the opposite.
- **DEC-10 (funding amount):** a payment to a leg is `rate × notional_per_leg`, negative for a long when the rate is positive. The reference price for notional is F-013's open question (M04); M03 uses the fixed notional.
- **DEC-11 (money precision):** amounts are rounded in one function to 6 decimal places (micro-USD). `quality-attributes.md:13` says cents, but one hour of funding on 1,000 USD at 0.00001 is 0.01 USD, so cents would erase most payments. Approved with the spec.
- **DEC-12 (cause):** `decision` gains a nullable `cause` text, set on every `no_action` (missing rate, no usable snapshot, thin book, missing fee). F-012's "a gap is recorded" is satisfied by this cause; the evaluator never writes the ingestion `gap` table (`domain.md:123-125`).

Assumptions:
- ASM-1: every E1 pair is in Polymarket's `crypto` category; the implementer checks the 38 paired instruments and stops if one is not.
- ASM-2: Polymarket's docs publish a taker fee that applies to crypto perpetuals; stop if not.
- ASM-3: the timer-run evaluator and the ingestion service share the database without lost minutes (ADR-002 amendment); checked on the VM.

## Requirements and Acceptance
| ID | Required Behavior | Acceptance |
|---|---|---|
| R-1 | `polyquack preregister FILE` reads a JSON preregistration (method name; rules N, E, X; metric; horizon 28 days; criterion ≥ 10% a year net on collateral; size 1,000 USD per leg; leverage 2; decision minute 21; snapshot age 120 s) and validates it. If the method's latest variant has no `first_run_at`, it replaces that variant's preregistration; otherwise it inserts the next variant number. `registered_at` is stored | AC-1 (plan AC-014): preregistering E1, running once, then preregistering a change creates variant 2; an UPDATE of variant 1's `preregistration` fails |
| R-2 | A trigger rejects any UPDATE of `variant.preregistration` once `first_run_at` is set, and any DELETE of such a variant | AC-2 (TST-013): the trigger raises on both |
| R-3 | `polyquack variants` prints, per method, the variants registered and the ones run | AC-3 (FR-014): the count increases after R-1's second variant runs |
| R-4 | `polyquack evaluate` starts a live `run` for each variant without one (`starts_at` = its first due decision instant; `variant.first_run_at` set in the same transaction) and decides, for every in-progress live run, every due hour not yet decided (DEC-5, DEC-7); a decision instant is due when it is at or before now | AC-4: with a fake clock, two missed hours are decided in order on the next run, each with its own cutoff |
| R-5 | Per due hour H, first credit funding (R-8), then per pair (DEC-2): read both rates of H (the reading whose hour by rounding is H, `source_time ≤ cutoff`); if one is missing → `no_action`, null spread, cause; otherwise store the spread and apply DEC-1 with the current position: flat and `|m| > E` → `open` on DEC-9's side; in a position and `m`'s side opposite to it with `|m| > E` → `reverse`; in a position and `|m| < X` → `close`; otherwise `hold`. `data_until` = the latest `source_time` actually read, never after the cutoff | AC-5 (plan AC-015): one decision per pair per hour; a missing rate gives `no_action` with a null spread |
| R-6 | For `open`, `close`, `reverse`: per leg, the latest usable snapshot (DEC-4); walk the asks for a buy, the bids for a sell; open fills `notional_per_leg` in quote currency; close fills the position's open quantity. Record per leg a `paper_trade`: `avg_price`, `best_price` (first level), `quantity`, `fee` = taker rate of the base tier effective at the cutoff × traded notional, `slippage` = `|avg − best| × quantity`, `snapshot_minute`. If either leg lacks a usable snapshot, a fee, or depth (DEC-6), the decision becomes `no_action` with cause and no trade or position change happens | AC-6 (plan AC-016, TST-012): for a sample book and 1,000 USD the walk gives the expected average price and slippage; a thin side gives `no_action` |
| R-7 | `open` creates a `paper_position` (`polymarket_side`, `notional_per_leg`, `leverage`, `opened_at` = decision instant, status `open`); `close` sets `closed_at` and `closed`; `reverse` closes it and opens the opposite one at the same instant | AC-7: a reverse leaves one closed and one open position with two close and two open trades |
| R-8 | Funding accrual: for every position open at any time before the cutoff, insert each uncredited payment per leg with `opened_at < source_time ≤ min(closed_at, cutoff)`, amount per DEC-10 (`INSERT OR IGNORE`, so catch-up never duplicates) | AC-8 (plan AC-017, TST-010): opened at hour t's decision, no payment of t; closed at t's decision, payment of t received; no `source_time ≤ opened_at` |
| R-9 | Every reading the evaluator uses comes through one read layer whose queries filter `source_time ≤ cutoff` in SQL and record the maximum `source_time` returned per decision | AC-9 (TST-011, F-014): seeding readings after the cutoff with extreme values changes no decision; for every decision the recorded reads, the funding used and the snapshot used (`paper_trade.snapshot_minute` joined to `book_snapshot.source_time`) are all at or before `decision.hour` |
| R-10 | Writes are short transactions, one per pair decision with its trades and positions, plus one per accrual batch (ADR-002 amendment); lock contention is handled like the ingestion's (`_is_lock_contention`); the evaluator never writes ingestion tables | AC-10: a test with a second writer holding the lock under the busy timeout loses no decision |
| R-11 | Deploy: `deploy/polyquack-evaluation.service` (`Type=oneshot`, `ExecStart=… polyquack evaluate`, same user, database and hardening as the ingestion unit) and `deploy/polyquack-evaluation.timer` (`OnCalendar=*:22`, `Persistent=true`); README documents install and the three commands | AC-11: units install and the timer lists its next run on the VM |
| R-12 | No code path calls an order or account endpoint (BR-011) | AC-12 (plan AC-018): grep of the source finds no such endpoint; tests pass with no network |

## Contracts and Risk Controls
- **Evaluation tables:** as `schema.dbml:130-221` for the included tables, plus `decision.cause text null` (DEC-12). `decision.action` values `open|hold|reverse|close|no_action`. Money columns hold values rounded per DEC-11.
- **Preregistration JSON:** the R-1 fields; stored verbatim after validation; immutable after the first run (R-2).
- **Fees:** Polymarket `crypto` category from the new data file; Hyperliquid unchanged. Fee lookup uses the latest `effective_from ≤ cutoff`.
- **Preserved:** ingestion tables, triggers and behavior; the ingestion unit; M02 commands.
- **Risk:** the evaluator opens the database as a writer, which re-applies `schema.sql` (idempotent) and briefly takes the write lock; transactions stay short.

## Canonical Design Impact
- Manifest: `docs/spec/manifest.yaml`
- Update:
  - `docs/design/domain.md`: reverse = close then open the opposite (no `reversed` state); `no_action` and its causes; `hold` meaning (DEC-8); maximum snapshot age (DEC-4); decision instant H+21 min (DEC-5); funding amount (DEC-10) — resolves F-007, F-012.
  - `docs/design/data/schema.dbml`: `decision.cause`; notes for DEC-5, DEC-10, DEC-11.
  - `docs/design/architecture/quality-attributes.md:13-14`: micro-USD rounding (DEC-11, if approved); NFR-008 evidence by readings actually used (F-014).
  - `docs/design/ux/flows.mmd` (F-002): decision at H+21 min; hold vs no_action.
  - `docs/design/review.md`: F-007, F-012, F-014 resolved citing this folder; M02's F-14 limitation closed by DEC-3.
  - `README.md`: commands and the timer.
- Preserve: ADRs, `architecture.dsl`, `prd.md`, ingestion tables.

## Quality Obligations
- Tests (`pytest`, no network): TST-010 accrual edges (open and close in the same hour, catch-up); TST-011 cutoff with future readings seeded (R-9); TST-012 book walk with expected average price and slippage, thin side; TST-013 immutability trigger; decision rule table for DEC-1 and DEC-8 (open, hold flat, hold in position, close, reverse, no_action causes); preregistration validation and variants (R-1, R-3); catch-up (R-4); second writer (R-10).
- Static/build: `uv run mypy --strict src tests`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest`, `gitleaks detect --no-git --source . --redact --no-banner`.
- QA on the VM (log in `vm-qa-log.md`): install the units; the author preregisters E1 with their values; 24 hours of decisions and trades; the NFR-008 check over the real run; no lost ingestion minutes during evaluator runs.
- Coverage/mutation: each R-* has at least one test or a named VM check.

## Done When
On the VM, after the author preregisters E1 and the timer has run for 24 hours, every non-delisted pair has 24 decisions, any paper trades carry prices, fee, slippage and snapshot, funding payments respect the accrual rule, the NFR-008 check over the real run reports zero violations, `polyquack completeness` shows no ingestion loss from the second writer, and the tests and static gates pass.

## Change Surface
- Expected edits (medium confidence): new `src/polyquack/evaluation/` (rule, book walk, accrual, read layer, runner); `src/polyquack/cli.py`; `src/polyquack/storage/schema.sql`, `db.py` (only what the evaluator's writes need); a Polymarket crypto fee data file and its loading in `platforms.py`; `deploy/polyquack-evaluation.{service,timer}`; `README.md`; `tests/**`; the documents in Canonical Design Impact.
- Do not touch: ingestion behavior (`service.py`, `feed.py`, `book.py`, `ratelimit.py`), ingestion tables and triggers, `deploy/polyquack-ingestion.service`, `docs/discovery/**`.

## Triggered Artifacts
| Artifact | Fired? | Reason |
|---|---|---|
| audit.md | Yes | reliability `strict`; no entry point existed |
| plan.md | No | one writer, no staged rollout |
| execution.md | Yes | implemented by a subagent and verified by another; the 24-hour VM run continues in a later session |

## Stop Conditions
- Work goes on `feat/e1-paper-evaluation/josueDev` from `dev`; no commit without the author's confirmation.
- ASM-1 or ASM-2 is false, or the Polymarket docs give no crypto rate.
- The implementation needs to write an ingestion table, change an ADR, or implement M04 behavior.
- E1's values (N, E, X) are not preregistered by the author before the first live run (CON-006); the implementation and tests use test values only.
