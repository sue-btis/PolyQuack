# M03 — E1 decides every hour on paper — Execution

Status: Implemented, awaiting independent verification and the VM QA

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Branch | `feat/e1-paper-evaluation/josueDev` (no upstream) |
| Planned base | `dev` with M02 merged |
| Current start commit | `e8f5853` (the audited commit) |
| Working tree before edits | clean except the untracked change folder |
| Pre-existing relevant changes | none |
| Untracked files before edits | `docs/changes/2026-11-09-M03-e1-paper-evaluation/` (`audit.md`, `spec.md`, `execution.md`) |

Baseline checks on 2026-11-09: `uv run pytest -q` passed (96 tests at M02).

## Preflight Verdict
Safe sequentially only

Reason: the audited commit is the start commit; no overlapping changes; `schema.sql` and `db.py` are shared with ingestion, so one writer works in sequence (spec: no plan).

## Execution Topology
Sequential (one implementer subagent; the main session is the integration owner)

## Executed Work
Sequential, one writer. Tests were written first for every group and run before any `src/polyquack/evaluation/` code existed.

Red evidence (`uv run pytest <file>` before implementing):
- `test_preregistration.py`, `test_rule_and_walk.py`, `test_readings.py`, `test_evaluate.py`: collection errors, `ModuleNotFoundError: No module named 'polyquack.evaluation'` (e.g. `tests\test_rule_and_walk.py:3: from polyquack.evaluation.money import round_money`).
- `test_evaluation_boundaries.py`: 3 failed, 1 passed. `assert FeeRate(category='crypto', tier='0', taker=0.0004, maker=0.000125, ...) in []` (no crypto fee file); `argparse.ArgumentError: argument command: invalid choice: 'evaluate'`; the network-module test failed because the package directory had no files. The grep test for order endpoints passed (the source never had one).
- Existing `test_lifecycle.py` fee tests were not red first: they changed expectations because the data file adds a Polymarket row (see Deviations).

Green after implementing: 196 passed. After that, hand mutation of the new code, each caught by a test: entry `>` to `>=`, exit `<` to `<=`, reverse side test removed, funding cutoff filter removed, payment lower bound `>` to `>=` (caught by `test_r8_payments_are_strictly_after...`; the integration test `test_ac8_a_reading_stamped_exactly_at_the_opening_is_not_credited` was added because the lifecycle test did not catch it), payment clamp to cutoff removed, snapshot cutoff removed, snapshot age doubled, close bound ignored, close side not inverted, missing hours counted as zero, delisted filter removed.

Files: new `src/polyquack/evaluation/{__init__,money,rule,walk,readings,preregistration,runner}.py`; `src/polyquack/cli.py` (commands `preregister`, `evaluate`, `variants`); `src/polyquack/storage/schema.sql` (7 evaluation tables, `decision.cause`, two freeze triggers); `src/polyquack/ingestion/polymarket_fees.json` and its loading in `PolymarketPerps.fees()`; `deploy/polyquack-evaluation.{service,timer}`; `README.md`; tests `evalkit.py`, `test_preregistration.py`, `test_rule_and_walk.py`, `test_readings.py`, `test_evaluate.py`, `test_evaluation_boundaries.py`, and edits to `test_lifecycle.py`; canonical docs. `db.py`, `service.py`, `feed.py`, `book.py`, `ratelimit.py` and `uv.lock` are untouched.

Checks from the repo root: `uv run mypy --strict src tests` no issues (42 files); `uv run ruff check src tests` all passed; `uv run ruff format --check src tests` 42 files formatted; `uv run pytest` 196 passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.

Facts checked:
- ASM-1: the 38 pairs of `probes/m02_api_facts.out.json` (`paired_exact`) are all `crypto` in today's `GET /v1/info/instruments` (90 instruments: crypto 41, equity 38, index 6, commodity 4, pre_ipo 1; none of the 38 is outside crypto). The pair list is the M02 probe's, not recomputed against Hyperliquid today.
- ASM-2 / DEC-3: https://docs.polymarket.com/perps/learn-about-trading/fees (page last modified 2026-10-21) publishes one tier table for all perps with no category column: base tier `$0` taker 0.0400%, maker 0.0125%. Live `GET /v1/info/fees` returns the same base tier labelled `equity`. The 41 crypto instruments have `fee_override: null`; only the pre_ipo instrument has an override.

## Integration Gates
| Gate | Owner | Diff Inspected? | Checks | Result |
|---|---|---:|---|---|
| Sequential implementation | main session | Yes (`git diff --stat`: 10 tracked files, +214/−37, plus new `src/polyquack/evaluation/`, fee file, two deploy units, 6 test files; `db.py`, `service.py`, `feed.py`, `book.py`, `ratelimit.py`, ingestion unit untouched; every `sqlite3.OperationalError` in `runner.py` goes through `_defer`, which re-raises anything that is not lock contention) | mypy strict, ruff check, ruff format, pytest ×2, gitleaks | Pass: `196 passed` twice, other checks clean |

## Requirement Status
| ID | Tests | Status |
|---|---|---|
| R-1 | `test_preregistration.py`: parse and rejections, replace vs next number, CLI | Done |
| R-2 | `test_ac2_*`, `test_ac1_an_update_of_a_run_variants...` | Done |
| R-3 | `test_ac3_*`, CLI variants | Done |
| R-4 | `test_r4_*`, `test_ac4_two_missed_hours...`, `test_dec5_*` | Done |
| R-5 | `test_ac5_*`, `test_r5_*`, `test_dec1_dec8_decision_rule_table` | Done |
| R-6 | `test_ac6_*`, `test_r6_*` (7 causes), `test_tst012_*`, `test_dec4_*`, `test_dec9_*` | Done |
| R-7 | `test_r5_r7_*`, `test_ac7_reverse...` | Done |
| R-8 | `test_ac8_*` (4), `test_r8_payments_*` | Done |
| R-9 | `test_ac9_*`, `test_r9_*`, `future_data_violations` helper | Done |
| R-10 | `test_ac10_*` (3), `test_r10_the_evaluator_writes_no_ingestion_table` | Done |
| R-11 | units written; install not run | Not run: needs the VM |
| R-12 | `test_ac12_*` (2) | Done |

## Deviations
- DEC-3 / ASM-2 judgment: the docs give one schedule with no `crypto` label. I treated it as applying to crypto because the page has no category split, the crypto instruments carry no fee override, and the API shows the same numbers. The effective date `2026-10-21` is the page's last-modified date, not a published effective date (noted in `polymarket_fees.json`). The author should confirm this reading.
- `test_lifecycle.py`: `test_fees_of_both_platforms_are_stored_dated_and_not_repeated` expects 9 rows (the file's crypto row is added and listed first); `test_a_changed_polymarket_rate_is_a_new_dated_row_set` filters Polymarket rows to those from `T0` on, because the file's crypto row has the same category as that test's API row. No assertion was removed.
- Run start: `starts_at` is the first decision instant strictly after `registered_at`; no run starts while that instant is not yet due, so the variant stays replaceable until then.
- `decision.data_until` falls back to the decision instant when no reading was returned (column is not null).
- Causes: `missing_rate`, `no_usable_snapshot`, `thin_book`, `missing_fee`. `evaluate` exits 1 when a write was deferred by lock contention.
- Pair status is the current derived status, not as of each cutoff; a pair delisted after an hour still gets that hour's decision only if undecided and active now. A pair is decided only for cutoffs at or after its `paired_at`.
- `review.md` F-007, F-012, F-014 set to `RESOLVED` citing this folder, pending the independent verification; "Accepted by" left empty. M02's F-14 is closed by the data file; no M02 document was edited.
- Not touched, as no change was needed: `db.py`.

## Canonical Design Synchronization
Updated: `domain.md` (decision actions, instant, `no_action` causes, snapshot age, reverse, funding amount, state diagram); `schema.dbml` (`decision.cause`, amount note); `quality-attributes.md` (NFR-007 micro-USD, NFR-008 readings actually used); `flows.mmd` (F-002); `review.md` (F-007, F-012, F-014). `README.md` documents the commands and the timer. Not changed: ADRs, `architecture.dsl`, `prd.md`.

## Blockers
None. Not stopped: ASM-1 held; ASM-2 held under the reading above.

## Independent Verification Readiness
Ready for a reviewer on the diff of `e8f5853` plus the untracked files. Not verified here: R-11 install and `systemctl list-timers` on the VM; the 24-hour run; the NFR-008 check over the real run; ASM-3 (no lost ingestion minutes while the evaluator runs); the `variants` command on a database that no writer has yet migrated (it opens read-only and would fail on missing tables); the E1 values (N, E, X) are for the author to preregister. Test values only were used.

## Correction Rounds

### Round 1 — after verification pass 1 (2026-11-09)
Findings addressed: F-1, F-2, F-4, F-6 point (a). F-3 and F-5 untouched.

Files: `src/polyquack/evaluation/runner.py`, `src/polyquack/evaluation/readings.py`, `tests/test_evaluate.py`, `tests/test_readings.py`, `README.md`, `docs/design/domain.md`.

- F-1: `_accrue` now skips the positions of pairs in `blocked`. I chose this over stopping the catch-up at the first deferral because other pairs keep deciding and accruing hours in order, and only the deferred pair's later hours depend on the undecided one. The pair resumes from its last decided cutoff on the next run. `future_data_violations` now also counts payments with `source_time > closed_at`.
- F-2: new assertions for payment rounding, the `(H - N, H]` lower edge, a reading of the first window hour stamped 10 s before it, and a two-pair deferral.
- F-4: `Reader.pair_status` reads each instrument's latest `instrument_status` row with `since <= cutoff` (none is active; delisted over close_only over active); `_evaluate_run` decides a pair only if that status is not delisted and `paired_at <= cutoff`. `Pair.active` and the current-status load were removed. `domain.md` states the scoping.
- F-6 (a): README tells to restart ingestion on the new code before the first `evaluate`.

Red evidence (`uv run pytest -q tests/test_evaluate.py tests/test_readings.py` before the fix, 3 failed):
- `test_ac10_a_deferred_pair_is_neither_decided_nor_accrued_past_its_last_decided_hour`: `assert 2 == 0 where 2 = future_data_violations(...)`.
- `test_f4_a_pair_delisted_after_an_hour_is_still_decided_for_that_hour_on_catch_up`: `assert [] == ['2026-10-28T22:21:00.000Z']`.
- `test_f4_pair_status_is_read_as_of_the_cutoff_...`: `AttributeError: 'Reader' object has no attribute 'pair_status'`.
- The F-2 tests and the `paired_at` test passed before the fix by design (they pin existing behavior); they are proven by the mutants below.

Mutant kills (each applied, suite run on `test_evaluate.py` and `test_readings.py`, restored; sha256 of both files matched the pre-mutation copies):
- M9 unrounded payment amount: `test_dec11_funding_payments_are_rounded_to_six_decimals`.
- M11 `blocked` filter removed: `test_ac10_a_deferred_pair_is_neither_decided...` and `test_ac10_hours_after_a_deferral_wait_for_it_while_other_pairs_go_on`.
- M12 window N+1: `test_dec1_the_window_is_the_last_n_hours_and_excludes_the_hour_n_back`.
- M17 lower bound `first_hour - 30 min` to `first_hour`: `test_dec1_a_reading_stamped_just_before_the_first_window_hour_still_counts`.
- M15 `paired_at` filter removed: `test_f4_close_only_still_decides_and_a_cutoff_before_pairing_is_not_decided`.
- F-1 accrual skip removed: `test_ac10_a_deferred_pair_is_neither_decided...`.

Checks: `uv run mypy --strict src tests` no issues (42 files); `uv run ruff check src tests` all passed; `uv run ruff format --check src tests` 42 files formatted; `uv run pytest` 204 passed; `gitleaks detect --no-git --source . --redact --no-banner` no leaks found.
Diff range: `git diff e8f5853` (11 tracked files) plus untracked files listed in Executed Work.
