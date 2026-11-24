# M04 — Basis, liquidation and E1 verdict — Verification

Verdict: Pass
Acceptance: Pending — the author's acceptance after the VM evidence F-9 (deploy; live-run measurements without ingestion loss; partial re-evaluation and its run time, ASM-2; post-horizon verdict of `reevaluate 1` and a second identical one)
Verified by: reviewer subagent, independent of the implementer (medium)
Open limitations: None

Size: medium
Reliability: strict

## Pass History
- Pass 1 (2026-11-11): Fail — F-1, F-2, F-3 open (defects); F-4 to F-9 open (decisions).
- Pass 2 (2026-11-11): Fail — F-1, F-2, F-3 fixed in Round 1; F-4, F-5, F-6, F-8 implemented as decided; F-10, F-11 open (defects); F-12 open (decision, later accepted as L-2).
- Pass 3 (2026-11-11): Fail — F-10, F-11 fixed in Round 2; F-13 open (defect, missing assertion in the F-10 class).
- Pass 4 (2026-11-11): Pass — F-13 fixed in Round 3 (one test, no source change); F-9 awaits the VM session.

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack`, branch `feat/basis-liquidation-verdict/josueDev` |
| Declared base | `cbd6299` (HEAD; Merge PR #5) |
| Verified head / working tree | HEAD `cbd6299` plus uncommitted work: 15 tracked files modified (+1064/−90); untracked `src/polyquack/evaluation/{liquidation,migration,verdict}.py`, `tests/test_{basis_liquidation,liquidation_math,reevaluation,verdict_rules}.py` |
| Untracked before edits | `docs/changes/2026-11-11-M04-basis-liquidation-verdict/`; `groma/` locally excluded |
| Diff range | `git diff cbd6299` + `git ls-files --others --exclude-standard` minus the change folder; pass 4 inspected the Round 3 delta: `tests/test_reevaluation.py` only (+33 lines, one test) |
| Verification date | 2026-11-11 |

## Deviations
- (a) to (f) judged in pass 1: (a) became F-4, (b) F-5, (e) F-7 (accepted, L-1); (c), (d), (f) conform. The live-run backfill became F-6, implemented in Round 1.
- Round 1 additions: `run.measured_from` (F-12, accepted as L-2); funding accrued to the horizon end for legs open after the last instant (follows the accrual rule and F-5; deferral fixed in Round 2; tested by F-11 and F-13).
- Round 2: deferred horizon closes and minute retries block their pair's accrual, matching the M03 blocked-pair rule. Round 3: test only.

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | defect | Out-of-window entities counted as kept; data after the horizon changed the verdict | `verdict.py:224`; probe `not_qualifiable`, verdicts 0; N1 killed | Fixed (Round 1) |
| F-2 | defect | Zero-length interval / "no positions" proxied by collateral | `verdict.py:47`, `:289`; `max_collateral([(5, 5, 1000.0)])` → `1000.0`; N2, N3 killed | Fixed (Round 1) |
| F-3 | defect | Missing assertions across chunks, decisions and the horizon | M12, M14, M32 killed | Fixed (Round 1) |
| F-4 | decision | No new position while an uncovered leg exists | Decided by the author, 2026-11-11, «No, bloquear (Recomendado)»; `runner.py:292`; N5 killed | Implemented as decided (Round 1) |
| F-5 | decision | Horizon close retried minute by minute; `unclosed_positions` only if still unfilled | Decided by the author, 2026-11-11, «No abrir + reintentar (Recomendado)»; `runner.py:822-874`; N7, N8 killed | Implemented as decided (Round 1) |
| F-6 | decision | The live run measures from deploy on | Decided by the author, 2026-11-11, «Desde el despliegue (Recomendado)»; `runner.py:268-288`, `:672`; N9, N10 killed | Implemented as decided (Round 1) |
| F-7 | decision | DEC-8 baseline = first measured minute that has a basis | Accepted by the author, 2026-11-11, «Sí, la acepto (Recomendado)» | Accepted (L-1) |
| F-8 | decision | No open at the last decision instant (a reverse becomes a close) | Decided by the author, 2026-11-11, «No abrir + reintentar (Recomendado)»; `runner.py:292`, `:349-354`; N4, N6 killed | Implemented as decided (Round 1) |
| F-9 | decision | VM evidence for a later session: deploy; live-run measurements from `measured_from` without ingestion loss; partial re-evaluation and its run time (ASM-2, including the per-minute retry); post-horizon (about 2026-12-07) verdict of `reevaluate 1` and a second identical one, in `vm-qa-log.md` | spec Quality Obligations and Done When | Open (VM session) |
| F-10 | defect | Deferral not blocking dependent accrual at the horizon | `runner.py:849-857`; probe: no payment after `closed_at`; F10a, F10b killed | Fixed (Round 2) |
| F-11 | defect | Missing assertions for Round 1 code (N6, N11, N12, N14) | all killed in pass 3 | Fixed (Round 2) |
| F-12 | decision | Contract addition `run.measured_from` | `schema.sql:148`, `migration.py:12`, `schema.dbml` | Accepted (L-2) |
| F-13 | defect | Missing assertion, F-10 class: a lock during the minute-by-minute horizon retry was untested | Round 3 adds `test_f13_a_lock_in_the_minute_retry_blocks_the_accrual_past_the_close_that_comes_next` (close unfillable until `LAST + 10 min`, one lock on that retry's trades, then the next run; asserts deferred `(1, 0)`, closed at the retry minute, no payment after `closed_at`, run `complete`). F10c re-applied: killed, and run alone only this test fails; F10e (retry deferral reported but the pair not blocked): killed | Fixed (Round 3) |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| R-1 / AC-1 | per-minute step from `max(opened_at, measured_from)` | `test_ac1_*`, `test_dec8_*`, `test_f3_*`, `test_f6_*` | Pass |
| R-2 / AC-2 | liquidation, DEC-4 close, horizon retry for an uncovered leg | `test_ac2_*`, `test_dec4_*`, `test_f3_*`, `test_f5_f3_*` | Pass |
| R-3 / AC-3 | `rate × quantity × price`, per-leg end, accrual to the horizon end skipping blocked pairs | `test_r3_*`, `test_n11_*`, `test_n12_*`, `test_f10_*`, `test_f13_*`; F10a to F10e killed | Pass |
| R-4 / AC-4 | `reevaluate` | `test_ac4_*`, `test_r4_*` | Pass |
| R-5 / AC-5 | empty-period filter, retry close, exclusion, breakdown | `test_r5_*`, `test_tst015_*`, `test_f1_*`, `test_f5_*` | Pass |
| R-6 / AC-6 | no positions counted by positions of non-excluded pairs | `test_r6_*`, `test_f2_*`, `test_f8_*` | Pass |
| R-7 / AC-7 | no wall-clock reads in decisions or amounts | `test_r7_*` (byte-for-byte exports) | Pass |
| R-8 / AC-8 | `render_verdict`, CLI | `test_r8_*` | Pass |
| R-9 / AC-9 | cutoffs in SQL; empty-period pairs ignored | `test_r9_*`, `test_f1_*` | Pass |
| R-10 / AC-10 | deferral blocks the pair in the hourly loop, the horizon close and the horizon retry | `test_ac10_*`, `test_f10_*`, `test_f13_*` | Pass |
| TST-014 to TST-018 | `test_liquidation_math.py`, `test_basis_liquidation.py`, `test_tst015_*`, `test_tst016_*`, `test_r6_*`, `test_r7_*` | green | Pass |
| DEC-1 to DEC-13 | as passes 1 to 3 | green; manual mutations killed in every class the spec names (DEC-5, 7, 10, 11, 12) | Pass |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | `Success: no issues found in 49 source files` |
| `uv run ruff check src tests` | Pass | lint | `All checks passed!` |
| `uv run ruff format --check src tests` | Pass | format | `49 files already formatted` |
| `gitleaks detect --no-git --source . --redact --no-banner` | Pass | secrets | `no leaks found` |
| `uv run pytest` (runs 1 and 2) | Pass | full suite | `288 passed in 169.41s`; `288 passed in 181.70s` |
| Probes (scratch `vt2/test_probe2.py`, pass 3; no source change since) | Pass | F-1, F-2, F-10 | `not_qualifiable`; collateral 1000.0; no payment after `closed_at` |
| Migration on a real M03-schema database with rows (pass 2; no migration change since) | Pass | migration | `loss` and `measured_from` added once, rows kept; `test_migration.py` covers both |
| Manual mutation (fresh scratch copy; SHA-256 equal before and after) | 2 written, 2 killed | F-13 class | see Quality Metrics |
| Changed-line/branch coverage | Not run | — | no tool installed |

## QA
VM QA assigned to a later session (F-9). Local, automated: a lock on the close at the last instant (`test_f10_*`) and a lock on the minute retry after an unfillable close (`test_f13_*`) both leave no payment after `closed_at` and the run `complete`.

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| single implementer (sequential), Rounds 1 to 3 | `src/polyquack/evaluation/**`, `cli.py`, `storage/schema.sql`, `README.md`, `tests/**`, Canonical Design Impact docs | within the write set; nothing under ingestion, `storage/db.py`, `deploy/`, `docs/discovery`, ADRs, `architecture.dsl`, manifest; freeze triggers unchanged; the evaluator writes no ingestion table | Yes |

## Contract / Integration Review
- The Contracts schema plus `run.measured_from` (accepted, L-2); variant 1's preregistration unchanged.
- CLI `reevaluate` and `verdict` wired; `evaluate` and `reevaluate` run the idempotent migration; horizon close, retry and accrual share one `blocked` set and `finish_run` is skipped after any deferral.
- No lockfile or pyproject change; the migration keeps rows on a real M03 schema. Other repositories: not applicable.

## Quality Metrics
- Changed-line and branch coverage: no tool.
- Mutation, pass 4 (focused suite plus `test_migration`): 2 written / 2 killed (F10c, F10e).
- Cumulative over passes 1 to 4: 42 written; every non-equivalent survivor became a finding and was later killed by a test (F-3, F-11, F-13). Equivalent: M36, M37. Unspecified behaviour: M33.
- Flaky or skipped tests: none in two full runs.

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|
| L-1 | F-7 | the author, «Sí, la acepto (Recomendado)» (option selected in the main session) | 2026-11-11 | none |
| L-2 | F-12 | the author, «Sí, la acepto (Recomendado)» (option selected in the main session) | 2026-11-11 | none |

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `docs/product/prd.md` | PD-023, BR-003, FR-015, FR-017 | present | Pass |
| `docs/design/domain.md` | DEC-1..4, 7, 9, 10, 12, re-evaluation run, F-013, Round 1 rules | present | Pass |
| `docs/design/data/schema.dbml` | Contracts changes plus `run.measured_from` | present | Pass |
| `docs/design/ux/flows.mmd` | per-minute step, no-positions branch, hold when opening is barred, horizon retry | present | Pass |
| `docs/design/architecture/quality-attributes.md` | NFR-007 compares two re-evaluations | present | Pass |
| `docs/design/review.md` | F-013 resolved citing the folder | present | Pass |
| `README.md` | `reevaluate`, `verdict` | present | Pass |
| ADRs, `architecture.dsl`, ingestion artifacts, manifest | preserved | unchanged | Pass |

## Merge Risk
Low

Reason: every defect is fixed and asserted by tests that kill the corresponding mutants; decisions are implemented or accepted. What remains is VM evidence (F-9): deploy, live measurement without ingestion loss, ASM-2 timing including the per-minute retry, and the post-horizon verdict, needed before the author's acceptance.
