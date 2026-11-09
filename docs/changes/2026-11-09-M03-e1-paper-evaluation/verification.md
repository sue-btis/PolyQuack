# M03 — E1 decides every hour on paper and collects funding without seeing the future — Verification

Verdict: Pass
Acceptance: Pending — the author's acceptance of M03 after the VM QA (F-6: install the units, preregister E1 with the author's N, E, X, 24 h of decisions, NFR-008 over the real run, no ingestion loss, logged in `vm-qa-log.md`)
Verified by: independent reviewer subagent, pass 2 (medium)
Open limitations: None

Size: medium
Reliability: strict

## Pass History
- Pass 1 (2026-11-09): Fail — F-1, F-2 open (defects); F-3, F-4, F-5, F-6 open (decisions).
- Pass 2 (2026-11-09): Pass — F-1, F-2 fixed and F-4 implemented in Round 1; F-3 accepted (L-1); F-5 done; F-6 assigned to the VM session.

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack`, branch `feat/e1-paper-evaluation/josueDev` |
| Declared base | `e8f5853` (HEAD; the audited commit) |
| Verified head / working tree | HEAD `e8f5853` plus uncommitted work: 11 modified tracked files (+218/−39; includes `docs/changes/2026-10-30-M02-all-pairs-ingestion/verification.md` for F-5) and untracked `deploy/polyquack-evaluation.{service,timer}`, `src/polyquack/evaluation/` (7 files), `src/polyquack/ingestion/polymarket_fees.json`, `tests/{evalkit,test_evaluate,test_evaluation_boundaries,test_preregistration,test_readings,test_rule_and_walk}.py` |
| Untracked before edits | `docs/changes/2026-11-09-M03-e1-paper-evaluation/`; excluded. `groma/` is locally excluded |
| Diff range | `git diff e8f5853` + `git ls-files --others --exclude-standard` minus the change folder; pass 2 inspected the Round 1 files: `runner.py` (`_load_pairs`, `_evaluate_run`, `_accrue`), `readings.py` (`pair_status`), `tests/test_evaluate.py`, `tests/test_readings.py`, `README.md`, `docs/design/domain.md`, `execution.md` |
| Verification date | 2026-11-09 |

## Deviations
Judged from `execution.md` against the code:
- Lifecycle test edits (`tests/test_lifecycle.py:213-215`, `:230`): not weakened; every original assertion still applies.
- `data_until` falls back to the decision instant when nothing was read (`runner.py` `_record`): consistent with `data_until <= hour`, documented in `schema.dbml`.
- Run start rule (`_start_runs`): first decision instant strictly after `registered_at`, started only once due; never decides before registration (M10 killed).
- Freeze: `first_run_at` set in the same transaction as the run insert; triggers fire on `OLD.first_run_at IS NOT NULL`.
- Round 1, F-1: `_accrue` skips the positions of pairs in `blocked` (`runner.py:404-405`) instead of stopping the whole catch-up; other pairs keep deciding and accruing in order; a blocked pair's positions are credited from the next run's first undecided cutoff, and `INSERT OR IGNORE` with the `min(closed_at, cutoff)` bound keeps that complete and free of duplicates. Judged correct.
- Round 1, F-4: `Reader.pair_status` (`readings.py:83-93`) derives the status from each instrument's latest `instrument_status` row with `since <= cutoff`; `_evaluate_run` decides a pair only if that status is not delisted and `paired_at <= cutoff` (`runner.py:157-167`). Matches the author's decision.
- `variants` on a database no writer has migrated fails (read-only open): covered by the VM procedure (F-6).

## Correction Rounds
Recorded in `execution.md` (Round 1, 2026-11-09: F-1, F-2, F-4, F-6 point (a)).

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | defect | Accrual upper bound broken by a deferred decision during catch-up (bug class: catch-up state inconsistency) | Pass 1 repro gave payments after close. Pass 2, same script (`scratchpad\repro_blocked_accrual.py`): `payments after close: []`, position closed at `2026-10-28T23:21:00.000Z`, all 6 decisions in order. `future_data_violations` now counts `source_time > closed_at` (`tests/test_evaluate.py:85`). Mutants R1 (skip removed) and N8 (skip only for closed positions) killed by `test_ac10_a_deferred_pair_is_neither_decided_nor_accrued_past_its_last_decided_hour` | Fixed (Round 1) |
| F-2 | defect | Surviving mutants showed missing behavior assertions (bug class: missing boundary or behavior assertion): M9 payment rounding, M11 `blocked` filter, M12 window N+1, M17 first-hour lower bound | M9 killed by `test_dec11_funding_payments_are_rounded_to_six_decimals`; M11 by `test_ac10_a_deferred_pair_is_neither_decided...` and `test_ac10_hours_after_a_deferral_wait_for_it_while_other_pairs_go_on`; M12 by `test_dec1_the_window_is_the_last_n_hours_and_excludes_the_hour_n_back`; M17 by `test_dec1_a_reading_stamped_just_before_the_first_window_hour_still_counts` | Fixed (Round 1) |
| F-3 | decision | Polymarket crypto fee source and effective date: `polymarket_fees.json:3-5` applies the docs' single, unlabelled schedule (taker 0.0004, maker 0.000125) to `crypto` with `effective_from` 2026-10-21 = the page's last-modified date | `src/polyquack/ingestion/polymarket_fees.json:1-7`; `execution.md` | Accepted — the author, 2026-11-09, «Sí, la acepto (Recomendado)» (L-1) |
| F-4 | decision | Which pairs decide an hour in catch-up (bug class: scoping by current state instead of as-of-cutoff state) | Decided by the author, 2026-11-09, «Estado en cada hora (Recomendado)»; implemented in Round 1 (`readings.py:83-93`, `runner.py:157-167`; `domain.md` Decision row). Mutants killed: M15 (`paired_at` removed), N1 (`since < cutoff`), N2 (`since` ignored), N3 (delisted filter removed), N4 (HL status ignored), N7 (status read at now); tests `test_f4_*` | Done (Round 1) |
| F-5 | decision | M02 limitation L-5 not closed in its own record | `docs/changes/2026-10-30-M02-all-pairs-ingestion/verification.md:6` (only L-6 open) and `:114` (L-5 done in this folder) | Done — the author, 2026-11-09, «Sí, ciérrala (Recomendado)» |
| F-6 | decision | VM-only evidence assigned to the VM session: R-11/AC-11 install and `systemctl list-timers`, the 24 h run, NFR-008 over the real run, ASM-3, the Done When, logged in `vm-qa-log.md`. (a) restarting ingestion before the first `evaluate` is in `README.md:79`; (b) `variants` needs a migrated database; (c) the author preregisters N, E, X (CON-006). Also to check there: that no funding hour has two readings with different `source_time` (live versus history), which would make accrual credit an hour twice; not verified in either pass | spec Quality Obligations and Done When; `README.md:79` | Open — VM session |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| R-1 / AC-1 | `preregistration.py`; `cli.py` `_preregister` | `test_ac1_*`, 14 rejection cases; M7 killed | Pass |
| R-2 / AC-2 (TST-013) | triggers `variant_preregistration_frozen`, `variant_delete_frozen` | `test_ac2_*`; M7 killed | Pass |
| R-3 / AC-3 | `render_variants` | `test_ac3_*` | Pass |
| R-4 / AC-4 | `_start_runs`, `_evaluate_run` | `test_ac4_*`, `test_r4_*`, two-pair deferral tests; M5, M8, M10, M11, N6 killed | Pass |
| R-5 / AC-5 | `_plan`, `rule.py` | `test_ac5_*`, `test_r5_*`, rule table, `test_dec1_*`; M12, M13, M17, M18, M19, M20 killed | Pass |
| R-6 / AC-6 (TST-012) | `_plan_trades`/`_trade`, `walk.py` | `test_ac6_*`, `test_r6_*`, `test_tst012_*`; M2, M3, M4, M16 killed | Pass |
| R-7 / AC-7 | `_record` | `test_ac7_reverse_*`, `test_r5_r7_*`; M19 killed | Pass |
| R-8 / AC-8 (TST-010) | `_accrue`, `Reader.payments` | `test_ac8_*`, `test_r8_*`, deferral tests; M1, M9, N5, R1, N8 killed; M14 equivalent; F-1 repro clean | Pass |
| R-9 / AC-9 (TST-011) | `Reader`: every query bounded by the cutoff in SQL (`source_time`, `effective_from`, `since`) | `test_ac9_*` seeds post-cutoff readings with identical results; `future_data_violations` covers `data_until`, snapshot source time, payments versus opening, close and latest decision; M6 killed | Pass |
| R-10 / AC-10 | `_record`, one transaction per accrual batch, `_defer` re-raises non-contention | `test_ac10_*` (5), `test_r10_*` | Pass |
| R-11 / AC-11 | `deploy/polyquack-evaluation.service` (`Type=oneshot`, same user, DB, env file, hardening), `.timer` (`OnCalendar=*:22`, `Persistent=true`); README | units read; install not runnable here | Not run — VM session (F-6) |
| R-12 / AC-12 | no order or account endpoint | `test_ac12_*`; suite runs without network | Pass |
| DEC-1 / DEC-8 / DEC-9 | `rule.py`, `_plan` | rule table, `test_dec1_*`, `test_dec9_*` | Pass |
| DEC-2 (as decided under F-4) | `Reader.pair_status`, `_evaluate_run` | `test_f4_*`; N1–N4, N7, M15 killed | Pass |
| DEC-4 / DEC-5 / DEC-6 / DEC-12 | `Reader.snapshot`, `latest_due`, causes | `test_dec4_*`, `test_dec5_*`, causes table | Pass |
| DEC-10 / DEC-11 | `_accrue`, `money.py` | amounts, signs and rounding asserted; M1, M9 killed | Pass |
| DEC-3 | `polymarket_fees.json`, `platforms.py` | `test_dec3_*` | Pass (reading accepted, L-1) |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | `Success: no issues found in 42 source files` |
| `uv run ruff check src tests` | Pass | lint | `All checks passed!` |
| `uv run ruff format --check src tests` | Pass | format | `42 files already formatted` |
| `uv run pytest` (runs 1 and 2) | Pass | all | `204 passed in 34.58s`; `204 passed in 30.42s` |
| `gitleaks detect --no-git --source . --redact --no-banner` | Pass | secrets | `no leaks found` |
| F-1 reproduction script (rerun) | Pass | R-8 | `payments after close: []` |
| Manual mutation, pass 2, 14 mutants, full suite each | 14 killed / 0 survived | Round 1 code and the F-1, F-2, F-4 bug classes | see Quality Metrics |
| Changed-line/branch coverage | Not run | — | `pytest-cov` not installed; not added |

## QA
1. Local deterministic QA: the suite with fake clocks, seeded readings and injected lock contention (AC-1..AC-10, AC-12). Expected: all pass without network. Actual: 204 passed twice.
2. VM QA (install, preregistration with the author's values, 24 h of decisions, NFR-008 over the real run, no ingestion loss). Actual: not run; F-6.

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| single sequential implementer (+ Round 1) | `src/polyquack/evaluation/`, `cli.py`, `schema.sql`, `db.py` (if needed), Polymarket fee file and its loading, `deploy/polyquack-evaluation.*`, `README.md`, `tests/**`, canonical docs | all within the set; `db.py`, `service.py`, `feed.py`, `book.py`, `ratelimit.py`, `deploy/polyquack-ingestion.service`, `docs/discovery/**`, `pyproject.toml`, `uv.lock` untouched; the M02 `verification.md` edit is the main session's F-5 bookkeeping, authorized by the author | Yes |

Ingestion tables and triggers in `schema.sql` are unchanged; only evaluation tables and two triggers were appended. The evaluator writes only `run`, `variant.first_run_at`, `decision`, `paper_position`, `paper_trade`, `paper_funding_payment`; `Reader.pair_status` only reads `instrument_status`.

## Contract / Integration Review
- Evaluation tables match the spec Contracts (`decision.action` CHECK, `decision.cause`, PKs `(run_id, pair_id, hour)` and `(position_id, platform_id, source_time)`); preregistration stored verbatim after validation.
- CLI `preregister` / `evaluate` / `variants` wired; `evaluate` exits 1 on a deferred write; a deferred pair now waits for its undecided hour, both for decisions and accrual.
- `schema.sql` additions use `IF NOT EXISTS`; no lockfile or project file change. Other repositories: not applicable.

## Quality Metrics
- Changed-line and branch coverage: no tool.
- Mutation (manual, one at a time, full suite, restored and confirmed by sha256 of every `src/polyquack/evaluation/*.py`, `schema.sql` and `tests/*.py`):
  - Pass 1: 20 written / 14 killed / 1 equivalent (M14) / 5 survived (M9, M11, M12, M17 → F-2; M15 → F-4).
  - Pass 2: 14 written / 14 killed. Re-applied: R1, M9, M11, M12, M15, M17. New: N1 `since < cutoff`; N2 `since` ignored; N3 delisted filter removed; N4 Hyperliquid status ignored; N5 accrual ignores `closed_at`; N6 deferred pair not added to `blocked`; N7 status read at now; N8 blocked-pair skip only for closed positions.
- Flaky or skipped tests: none in 2 full runs this pass.

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|
| L-1 | F-3 | the author, «Sí, la acepto (Recomendado)» (option selected in the main session) | 2026-11-09 | none; a published per-category Polymarket schedule becomes a new dated row |

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `docs/design/domain.md` | reverse = close + open; `no_action` causes; `hold`; snapshot age; H+21; funding amount; pair scoping as of the decision instant | all present | Pass |
| `docs/design/data/schema.dbml` | `decision.cause`; notes for DEC-5, DEC-10, DEC-11 | present | Pass |
| `docs/design/architecture/quality-attributes.md` | micro-USD rounding; NFR-008 by readings actually used | updated | Pass |
| `docs/design/ux/flows.mmd` | F-002 at H+21; hold versus no_action | updated | Pass |
| `docs/design/review.md` + M02 record | F-007, F-012, F-014 resolved citing this folder; M02 F-14 closed by DEC-3 | done | Pass |
| `README.md` | three commands, the timer, ingestion restart before the first `evaluate` | documented (`README.md:79`) | Pass |
| ADRs, `architecture.dsl`, `prd.md` | preserved | unchanged | Pass |

## Merge Risk
Low

Reason: no open defect; the no-future-data, accrual, catch-up and deferral logic was checked with 34 targeted mutants over two passes and every non-equivalent one is killed. The remaining risk is runtime behavior on the VM (two writers on one database, real data over 24 h), which F-6 covers before acceptance.
