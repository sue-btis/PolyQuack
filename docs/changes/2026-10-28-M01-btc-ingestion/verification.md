# M01 — One pair (BTC) is ingested end to end on the VM — Verification

Verdict: Blocked
Acceptance: Accepted by the author on 2026-10-30 with the open limitations below, after the VM QA in `vm-qa-log.md`; author decisions F-4 to F-12 still pending
Verified by: reviewer subagent, independent of the implementation session (medium); VM QA run by the author
Open limitations: AC-5 (reconnection after a 5-minute network cut) and AC-6 (recovery after a VM restart) were not run on the VM by the author's decision; only the local tests in `test_feed.py` and `test_service.py` cover them. The technical verdict was not re-run after the VM QA.

Size: medium
Reliability: strict

## Pass History
- Pass 1 (2026-10-28): Fail — F-1, F-2, F-3 open; decisions F-4 to F-12 pending; VM checks unverified.
- Pass 2 (2026-10-28): Blocked — F-1, F-2, F-3 fixed in Round 1; the VM evidence the spec requires cannot be produced in this environment; F-4 to F-12 pending.
- VM QA (2026-10-30, author, not a verifier pass): preconditions, install and the 2 h run passed; network cut and restart not run. See `vm-qa-log.md`.

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` |
| Declared base | none at Pass 1 and Pass 2 (unborn branch). Since 2026-10-29 the base is `98ae1a9` (translation commit on `docs/english-translation/josueDev`); the change now sits uncommitted on `feat/btc-ingestion/josueDev`, so later passes can use `git diff 98ae1a9` plus untracked files |
| Verified head / working tree | working tree as of 2026-10-28 ~21:25 -0600; all files untracked |
| Untracked before edits | `.gitignore`, `docs/**` (separate English translation; out of scope except the canonical edits) |
| Diff range | Pass 1 inventory (`pyproject.toml`, `uv.lock`, `README.md`, `.gitleaksignore`, `deploy/polyquack-ingestion.service`, `src/polyquack/**`, `tests/**`, the canonical edits in `prd.md`, `domain.md`, `schema.dbml`, `review.md`). Round 1 delta: `src/polyquack/ingestion/feed.py`; `tests/test_feed.py`, `test_parsers.py` (new), `test_book.py`, `test_service.py`, `test_storage.py`; `tests/fixtures/*.json` (6 new); `README.md`; `deploy/polyquack-ingestion.service`; `docs/design/review.md` (F-006). `pyproject.toml` and `uv.lock` unchanged since Pass 1; `docs/discovery/spikes/*.py` unchanged since 15:42 |
| Verification date | 2026-10-28 |

## Deviations
Implementer deviations recorded in `execution.md`, assessed in Pass 1 and still open as author decisions:
- F-5: REST depth 100 cut to 50. Forced by the API.
- F-6: delisted Hyperliquid instruments skipped. Now tested.
- F-7: `not_collected` gaps for downtime.
- F-8: `instruments` gap recorded as `final`.
- F-9: heartbeat and a ~20 s dead-connection window.
- F-10: `.gitleaksignore`. Verified false positive.
- F-4: ruff run over `docs/`.
- F-11: branch.

## Correction Rounds
- Round 1 (recorded in `execution.md`): F-1, F-2, F-3 addressed; files as in the Baseline delta; implementer's checks: mypy, ruff, pytest (48 passed), gitleaks.
- After Pass 2, the main session applied two editorial fixes the verifier flagged: the install step now uses the absolute path `/opt/polyquack/app/deploy/polyquack-ingestion.service` (README and `execution.md`), and `execution.md` names `tests/test_parsers.py` as the 23rd formatted file.

## Findings
| ID | Type | Finding | Evidence | Status |
|---|---|---|---|---|
| F-1 | defect | Backoff state not reset on abnormal close: the reconnect delay did not return to 1 s after a healthy session ended with `ConnectionClosedError` | Pass 1: `feed.py:29-42`; repro logged 2 s, 4 s. Pass 2: `_received` is set by the reading loop and read after any exit path (`feed.py:25,30,43,58-59`); the same scratchpad abort repro logs `reconnecting in 1 s` twice and passes; mutants M20 and M21 killed; repo regression test `test_reconnect_delay_returns_to_the_initial_one_after_an_aborted_healthy_session` | Fixed (Round 1) |
| F-2 | defect | Missing behaviour assertions (8 mutation survivors) and TST-1 not using trimmed real responses | Pass 2: 12 mutants killed (M1, M1b, M5, M11, M12, M13, M16, M16b, M18, M20, M21, M22). TST-1 runs the real instrument parsers over `tests/fixtures/pm_instruments.json` and `hl_meta.json`, then pairs, lists unpaired and repeats without duplicates (`tests/test_parsers.py:33-71`). The fixture shapes match the APIs; that they were fetched live is self-report | Fixed (Round 1) |
| F-3 | defect | Deployment procedure, ownership: the root-owned clone, `uv sync` as a user with no home and no `uv` on PATH | Pass 2: `useradd --create-home --home-dir /opt/polyquack`; `uv` installed by and for the user (`/opt/polyquack/.local/bin/uv`); the user clones into `/opt/polyquack/app`; unit `WorkingDirectory` and `ExecStart` updated (`deploy/polyquack-ingestion.service:9,12`); README and `execution.md` agree. Not executed (see QA) | Fixed (Round 1) |
| F-4 | decision | Out-of-scope edit: ruff rewrote 5 `docs/discovery/spikes/*.py` files; no backup; probes restored | `execution.md` Deviations; spike mtimes 15:42; all 5 pass `py_compile` | Open |
| F-5 | decision | Unrequested deviation: Polymarket REST resync `depth=100` cut to 50 | `platforms.py:96-98,131-142`; now tested | Open |
| F-6 | decision | Unrequested deviation: delisted Hyperliquid instruments not stored or paired | `platforms.py:167-170`; now tested | Open |
| F-7 | decision | Unrequested deviation: `not_collected` gaps for elapsed intervals | `service.py:110-130` | Open |
| F-8 | decision | Spec gap: `instruments` gap born `final` | `service.py:85-87` | Open |
| F-9 | decision | Staleness window: ~20 s during which a dead connection's book counts as valid (DEC-3) | `feed.py:14-16` | Open |
| F-10 | decision | File outside the Change Surface: `.gitleaksignore`; verified false positive | `.gitleaksignore:2`; isolated scan, line 957 | Open |
| F-11 | decision | Branch policy: work on `docs/english-translation/josueDev`, spec requires `feat/btc-ingestion/josueDev` before commit | `spec.md:112` | Open |
| F-12 | decision | Status coverage: platform-level `instruments` gaps not shown by `polyquack status` | `status.py:63-67` | Open |

## Requirement Compliance
| Requirement / AC | Implementation Evidence | Independent Check | Result |
|---|---|---|---|
| R-0 / AC-0 | git repo; `.gitignore` | ignored list correct; gitleaks: no leaks | Pass |
| R-1 / AC-1 | `service.py:79-104`, `platforms.py:100-105,164-170`, `db.py:50-95` | real-parser TST-1 over fixtures; instruments gap test; M11 and M22 killed | Pass locally; Blocked (VM) |
| R-2 / AC-2 | `service.py:214-257`, `platforms.py:107-120,172-185` | parser tests for both platforms; open gap; hour rounding (M12, M13 killed); 2 h not run | Blocked (VM) |
| R-3 / AC-3a | `feed.py` | drop, resync and reconnect tests; F-1 fixed | Pass locally; Blocked (VM log) |
| R-4 / AC-3 | `service.py:132-159`, `book.py` | snapshot or gap, never twice; DEC-1 boundary (M1, M1b killed) | Pass locally; Blocked (VM) |
| R-5 / AC-4 | `service.py:161-212` | source_time tests; failure and late gaps (M5 killed) | Pass locally; Blocked (VM) |
| R-6 / AC-7 | `ratelimit.py`, `platforms.py:42-58` | 6 rate tests; Pass 1 mutants M9, M14 killed | Pass locally; Blocked (VM, 2 h log) |
| R-7 / AC-5 | `feed.py`, `_pending` | reconnect reset fixed; network cut not run | Blocked (VM) |
| R-8 / AC-6 | `deploy/polyquack-ingestion.service`, README | procedure read; not executed | Blocked (VM) |
| R-9 / AC-9 | `schema.sql:106-119` | 3 tables x UPDATE/DELETE test | Pass |
| R-10 / AC-10 | `status.py`, `cli.py` | status and 24 h window tests (M18 killed); output after 2 h not seen; F-12 | Pass locally; Blocked (VM) |
| DEC-1 / DEC-2 | `book.py:40-65` | reach and truncation tests; inclusive boundary on both sides | Pass |
| DEC-3 | `book.py:22-37`, `feed.py` | invalidation and resync tests | Pass (F-9 window) |
| DEC-4 | `service.py:23-25`, `schema.sql:92-102` | statuses and closed intervals | Pass |
| DEC-5 | `pyproject.toml`, `uv.lock` | runtime deps httpx and websockets only; gates pass on 3.13 | Pass (3.12 unverified) |

## Automated Checks
| Command / Check | Result | Covers | Evidence / Notes |
|---|---|---|---|
| `uv run mypy --strict src tests` | Pass | types | Success: no issues found in 22 source files |
| `uv run ruff check` | Pass | lint | All checks passed! |
| `uv run ruff format --check` | Pass | format | 23 files already formatted |
| `uv run pytest -p no:cacheprovider` | Pass | TST-1..6 and Round 1 tests | 48 passed in 6.80s |
| `gitleaks detect --no-git --source . --redact --no-banner` | Pass | secrets | no leaks found |
| `check-package.mjs .` | Pass | canonical package | Package checks passed. |
| `presupuesto-comentarios.mjs --calibrar src` / `tests` | Pass | comment budget | 0 blocks flagged in each |
| F-1 abort repro (scratchpad copy) | Pass | backoff reset | `reconnecting in 1 s` x2 |
| survivor mutants (scratchpad copy) | 12/12 killed | F-2 | see Quality Metrics |
| Coverage | Not run | lines and branches | no tool installed |
| Dependency audit | Not run | advisories | no tool installed |

## QA
1. VM QA steps 1-6 (`execution.md` "Pending VM QA").
Expected: Done When.
Actual: not run — needs the VM.

## Ownership and Scope
| Workstream | Assigned Write Set | Actual Files | Compliant? |
|---|---|---|---:|
| single writer | Change Surface (`spec.md:94-102`) | Change Surface plus `.gitleaksignore` (F-10) plus 5 spike files (F-4, Pass 1 only; untouched in Round 1) | Partial (pending F-4, F-10) |

## Contract / Integration Review
- Frozen contract fidelity: `schema.sql` matches the DBML Ingestion tables; no order or account endpoints; no credentials.
- Integration gate: static and unit gates pass; parsers are contract-tested against fixtures with real shapes; live behaviour on the VM is unverified.
- Generated/migration/project/lockfile review: `uv.lock` and `pyproject.toml` unchanged since Pass 1; no migration (fresh schema).
- Other repositories: not applicable.

## Quality Metrics
- Changed-line coverage: no tool
- Changed-branch coverage: no tool
- Mutation (manual): Pass 1: 20 written / 10 killed / 2 equivalent / 8 survived. Pass 2: 12 written / 12 killed / 0 equivalent / 0 survived (M1, M1b, M5, M11, M12, M13, M16, M16b, M18, M20, M21 `_received` never set, M22 Polymarket asset field swapped).
- Flaky/skipped tests affecting scope: none seen

## Accepted Limitations
| ID | Finding | Accepted by | Date | Follow-up |
|---|---|---|---|---|

## Canonical Design Synchronization
| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `prd.md` FR-006, PD-005, PD-022 | reach/truncation; `Decided`; new row «B» | lines 150, 351, 368 | Pass |
| `domain.md` Book snapshot / Gap | reach; closed intervals, open/final | lines 13, 59 | Pass |
| `schema.dbml` | `bid_reach`/`ask_reach`; notes; `gap.status` note | lines 90-95, 121 | Pass |
| `review.md` F-006 / F-008 | RESOLVED citing the folder; F-006 says `check-package.mjs` exits 0 | lines 207, 244; `check-package.mjs` exit 0 | Pass |
| ADRs, `architecture.dsl`, `flows.mmd`, `quality-attributes.md` | untouched | no edits reported; no git history to prove it | N/A |

## Merge Risk
Medium

Reason:
The code-level defects are fixed, and the decision logic is covered by tests that kill every mutant tried. The remaining risk is the VM behaviour that has not been run (network cut, restart, the 2 h cadence, the install procedure) and the open author decisions F-4 to F-12.
