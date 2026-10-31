# M01 — One pair (BTC) is ingested end to end on the VM — Execution

Status: Implemented — verification blocked (the VM checks of Done When are pending; everything verifiable locally passed)

## Baseline
| Field | Value |
|---|---|
| Repository | `C:\Users\Josue Escobar\Documents\projects\mine\Polyquack` (git repository, no commits) |
| Branch | `docs/english-translation/josueDev` (unborn). The spec's stop condition names `feat/btc-ingestion/josueDev`; the instruction for this run was not to create or switch branches, so the work sits on the unborn branch, uncommitted |
| Planned base | none (no commit exists) |
| Current start commit | none |
| Working tree before edits | `.gitignore` and `docs/` untracked (English translation of `docs/`, done just before this change); nothing staged |
| Pre-existing relevant changes | The whole `docs/` tree is uncommitted. There is no commit to diff against: the verifier compares against the file lists below |
| Untracked files before edits | `.gitignore`, `docs/**` |
| Without version control | Files to touch and pre-change state: new files (all of `pyproject.toml`, `uv.lock`, `README.md`, `.gitleaksignore`, `src/`, `tests/`, `deploy/`) did not exist. Pre-edit content of the five edited documents was not hashed; the exact edit sites are listed under Canonical Design Synchronization |

## Preflight Verdict
Safe sequentially only

Reason: a single writer; no overlap with other changes. No commit exists, so "base vs current" cannot be compared and the final diff can only be reviewed as a file inventory. `audit.md` was consistent with the repository and the live APIs except for the points under Deviations (REST book depth, instrument counts).

## Execution Topology
Sequential (single writer, shared tree).

## Executed Work
| Workstream / Task | REQ IDs | Status | Files Changed | Checks | Evidence |
|---|---|---|---|---|---|
| Project and tooling | R-0, DEC-5 | Completed | `pyproject.toml`, `uv.lock`, `README.md`, `.gitleaksignore` | gates below | `uv sync` resolved httpx 0.28.1, websockets 17.3; dev mypy 2.4.1, pytest 9.2.0, ruff 0.17.3 |
| Storage | R-1, R-9 | Completed | `src/polyquack/storage/schema.sql`, `db.py` | `tests/test_storage.py` | 11 Ingestion tables, `book_snapshot.bid_reach/ask_reach`, insert-only triggers, WAL, `busy_timeout` |
| Platforms and rate control | R-1, R-2, R-5, R-6 | Completed | `ingestion/platforms.py`, `ratelimit.py`, `models.py` | `tests/test_ratelimit.py`, `tests/test_service.py` | 429 / `ip_rate_limited` / `Retry-After` handled in the single request path |
| Book and live feed | R-3, R-4, R-7, DEC-1, DEC-3 | Completed | `ingestion/book.py`, `feed.py` | `tests/test_book.py`, `tests/test_feed.py` | the feed test uses a local websocket server: drop, invalidation, reconnection, REST resync |
| Service, CLI, status | R-1 to R-5, R-7, R-10 | Completed | `ingestion/service.py`, `cli.py`, `config.py`, `status.py`, `times.py` | `tests/test_service.py`, live smoke run | see Smoke run |
| VM unit | R-8 | Written, not exercised | `deploy/polyquack-ingestion.service` | none possible here | pending VM QA |
| Canonical documents | F-006, F-008, PD-022 | Completed | `docs/product/prd.md`, `docs/design/domain.md`, `docs/design/data/schema.dbml`, `docs/design/review.md` | `dbml2sql` exit 0, 22 `CREATE TABLE` | see Canonical Design Synchronization |

Tests were written after the code; no red-then-green evidence exists, and none is claimed. The one failure seen was a wrong expected literal in a test I wrote (`iso()` example), corrected after checking the real UTC time independently.

## Integration Gates
| Gate | Owner | Diff Inspected? | Checks | Result |
|---|---|---:|---|---|
| Static and unit gates | main thread | Yes (file inventory; no git diff possible) | `uv run mypy --strict src tests` | `Success: no issues found in 21 source files`, exit 0 |
| | | | `uv run ruff check` | `All checks passed!`, exit 0 |
| | | | `uv run ruff format --check` | `22 files already formatted`, exit 0 |
| | | | `uv run pytest` | `34 passed in 2.75s`, exit 0 |
| | | | `gitleaks detect --no-git --source . --redact` | first run: 1 finding (false positive, see Deviations); after `.gitleaksignore`: `no leaks found` |
| DBML | main thread | Yes | `npx -y -p @dbml/cli dbml2sql docs/design/data/schema.dbml` | exit 0, 22 `CREATE TABLE`, `bid_reach`/`ask_reach` present |

The interpreter used by `uv` for these runs was CPython 3.13.12; `requires-python` is `>=3.12`, and 3.12 itself was not run.

## Requirement Status
| Requirement | Implementation | Acceptance Evidence | Status |
|---|---|---|---|
| R-0 | repository already existed; `.gitignore` already complete, not modified; `.gitleaksignore` added | `git status --short` lists no `*.db`, caches or `.venv`; gitleaks clean after the ignore entry | Completed |
| R-1 | `Service.refresh_instruments`, `_instruments_loop` (retry 5 s doubling to 300 s, refresh every 24 h), `Database.pair_instruments`, `unpaired_instruments` | smoke run: 89 + 179 instruments stored, 38 pairs, BTC paired; TST-1 equivalents in `test_storage.py`; gap on failure in `test_service.py`. The retry loop itself is not unit-tested | Completed |
| R-2 | `Service.collect_funding`, `_funding_loop` | smoke run stored the 21:00 UTC payment of both platforms with source times `…:00.045Z` and `…:00.078Z`; open gap and success paths in `test_service.py`. The 2-hour sequence and the 15-minute deadline in real time are not run | Partial (2 h on the VM pending) |
| R-3 | `BookFeed`, channels `book::{iid}::50` and `l2Book` | smoke log shows `connected`, `subscribed`, `resync … done` for both platforms; reconnection in `test_feed.py` | Completed |
| R-4 | `Service.close_minute`, `book.build_snapshot` | smoke run: 4 snapshots per instrument, 0 gaps; `test_book.py`, `test_service.py` | Completed locally; 2 h pending |
| R-5 | `Service.collect_prices` | smoke run: 4 price readings per instrument; Polymarket `source_time` filled, Hyperliquid null; `test_service.py` | Completed locally; 2 h pending |
| R-6 | `RateLimiter`, `Platform._request` | `test_ratelimit.py`; smoke log: 8 price requests in 4 minutes (2 per minute); no 429 seen | Completed locally; 2 h pending |
| R-7 | `BookFeed.run` reconnection, `Service._pending` gap fill | `test_feed.py` (drop, invalidation, reconnect, resync) and `test_service.py` (elapsed minutes become gaps). The 5-minute network cut was not run | Partial (VM pending) |
| R-8 | `deploy/polyquack-ingestion.service` | none possible here | Not verified (VM pending) |
| R-9 | triggers in `schema.sql` | `test_storage.py::test_reading_tables_reject_update_and_delete` (3 tables x UPDATE and DELETE) | Completed |
| R-10 | `polyquack status`, `status.render_status` | smoke run output shows funding, book, price per pair and platform, gaps (merged ranges), and 192 unpaired instruments | Completed |

## Smoke Run (2026-10-28, local, public read-only APIs, not part of the gates)
Command: `POLYQUACK_DB=<scratchpad>/smoke.db timeout 270 uv run polyquack run`, 21:51:10Z to 21:55:40Z (about 4.5 min, killed by `timeout`, exit 124). Database and log are in the session scratchpad, outside the repository.

- Instruments: Polymarket 89 stored; Hyperliquid 179 stored (delisted entries skipped, see Deviations); 38 pairs.
- Channels: both connected on the first attempt, no reconnection in 4.5 min (the library pings every 10 s and the Hyperliquid JSON ping every 30 s were exercised; no pong handling was needed). REST resync done on both.
- Funding (ASM-1, ASM-2): the 21:00Z payment was stored for both platforms with source times 21:00:00.045Z (Polymarket) and 21:00:00.078Z (Hyperliquid), rate `1.25e-05` on both. Times are within the 1 min tolerance; the unit of the Hyperliquid rate cannot be proven from this alone (it equals Polymarket's, as in `audit.md`).
- Book: Hyperliquid reach 0.00024 on both sides (20 levels, DEC-1 truncation as predicted), `bid_levels` about 400 chars. Polymarket `::50` reach 0.0057 to 0.0205 (one side below 0.005 in one snapshot: 0.0044 ask, so the truncated case also occurs on Polymarket, as `audit.md` says). Notional at 0.5%: 3.3M to 3.4M (Polymarket), 3.1M to 10.2M (Hyperliquid).
- Prices: 4 readings per instrument; Polymarket `source_time` filled (e.g. `21:52:00.999`), Hyperliquid null `source_time`, `received_at` filled.
- Gaps: 0 rows. 429: none.
- Request count: 8 `price request` log lines in 4 minutes = 2 per minute. The `httpx` INFO log lists every REST request.
- Message formats: no difference from `audit.md` on the endpoints and channels used. The Polymarket REST book rejects `depth=50` (`depth must be one of 10, 100, 500, 1000`), so the resync uses `depth=100` cut to 50 levels (see Deviations).
- Local clock: the local machine runs about 1.5 s behind the servers' `Date`, so snapshot `source_time` of the Polymarket and Hyperliquid messages is sometimes after the end of its minute. This is a property of the machine's clock, not of the code, but it shows that clock synchronization on the VM must be checked (pending QA step).

## Deviations
- **REST book depth (Polymarket):** `audit.md` and the channel use 50 levels; the REST endpoint accepts only 10/100/500/1000. The resync requests `depth=100` and keeps the first 50 levels so that a resynced book has the same content as the channel (`PolymarketPerps.rest_depth`).
- **Delisted Hyperliquid instruments are skipped** at discovery (`isDelisted`): instrument lifecycle is M02 and a delisted coin must not be paired. The live count was 179 non-delisted, against 235 in `universe` seen with `metaAndAssetCtxs`.
- **Gaps for time the service was not running (not asked by a requirement, derived from the Goal "each minute or hour without data is recorded as a gap" and R-7/R-8):** `Service._pending` closes every elapsed interval that has neither a reading nor a gap, with cause `not_collected` (`final` for snapshots and prices, `open` for funding). It covers the downtime of a stopped service and a stalled loop with the same code, and keeps "never both nor neither".
- **`instruments` gap status:** the spec fixes the statuses of snapshot, price and funding gaps (DEC-4) but not of `instruments`. It is recorded as `final`. The author may prefer `closed_with_data` once a retry succeeds.
- **Heartbeat:** Hyperliquid documents `{"method":"ping"}` after 60 s of silence, implemented every 30 s. Polymarket Perps documents no ping or idle timeout (the fetched pages say nothing); it relies on the websockets library's protocol pings every 10 s plus the 100 ms book pushes. Dead connections are detected in about 20 s (`ping_timeout`); during that window the in-memory book still counts as valid under DEC-3 and the snapshot carries the old `source_time`.
- **`.gitleaksignore` added** (not in the Change Surface): `gitleaks detect --no-git --source .` reported one `generic-api-key` finding in `docs/site/polyquack-architecture.html` (a minified bundled script, variable `keyCount`; no credential). Without an allowlist AC-0 ("gitleaks with no findings") cannot pass. The ignore entry is the exact finding fingerprint.
- **`ruff format` and `ruff check --fix` ran on `docs/` by mistake** before `pyproject.toml` excluded `docs`. They rewrote the formatting of seven Python files that the spec says not to touch and that have no git history to restore from: `docs/discovery/spikes/DQ-006-ladders/download.py`, `docs/discovery/spikes/DQ-006-ladders/ladders.py`, `docs/discovery/spikes/DQ-C-weather/probe.py`, `docs/discovery/spikes/DQ-E-funding/probe.py`, `docs/discovery/spikes/DQ-E-funding/out_of_sample.py`, and the two probes in this change folder (`probes/depth_hyperliquid.py`, `probes/depth_polymarket.py`). `ruff format` preserves behavior; the `--fix` run applied 11 safe lint fixes in total (which files and which fixes was not recorded; they can include unused-import removals). `pyproject.toml` now has `extend-exclude = ["docs"]`. If the author keeps a copy of the pre-change files, restoring them is advisable. The two probes were later restored from the main session's pre-change copies and rerun.
- **`dbml-error.log`:** `dbml2sql` created an empty `dbml-error.log` at the repository root. The delete command was held by the permission guard (no answer) and was not retried; the file is empty and listed in `.gitignore`. Remove it by hand.
- **Branch:** see Baseline.

## Canonical Design Synchronization
- `docs/product/prd.md`: FR-006 (reach and truncation sentence); PD-005 status `Decided`, "Replaced by PD-006" moved to the Decision column; new row PD-022 after PD-021 with quote «B» (author, 2026-10-28), affects FR-006, `domain.md`, `schema.dbml` -> updated.
- `docs/design/domain.md`: definition of Book snapshot (reach, truncated volume, PD-022); lifecycle line of Gap (closed intervals, what is born `open` and `final`) -> updated.
- `docs/design/data/schema.dbml`: `book_snapshot.bid_reach` and `ask_reach` added; notes of `*_notional_05` and `*_levels` ("up to 0.5% or up to the reach"); note of `gap.status`; `gap.ends_at` unchanged (`not null`) -> updated; `dbml2sql` exit 0, 22 tables.
- `docs/design/review.md`: F-006 and F-008 `Status: RESOLVED`, each with a `Resolution` line citing this folder -> updated. The counters of the historical cycle entries (`MINOR open`) were not rewritten.
- `docs/design/data/schema.dbml` vs `src/polyquack/storage/schema.sql`: the SQL is hand-derived for the 11 Ingestion tables (no generator); the column order of `book_snapshot` follows the DBML and the positional `INSERT` in `db.py` depends on it.
- Preserved: ADR-001 to ADR-006, `architecture.dsl`, `flows.mmd`, `quality-attributes.md`, Evaluation and Publishing tables, F-007 and F-010 to F-015. The contradiction between the published Polymarket limits and ADR-004 / `quality-attributes.md` remains recorded in the spec and is not corrected.
- `check-package.mjs` was not run by the implementation; the verifier ran it afterwards (exit 0, "Package checks passed.") and F-006 in `review.md` says so.

## Ownership / Contract Conflicts
None.

## Blockers
- No stop condition triggered. ASM-1 and ASM-2 held in the smoke run; the message formats matched `audit.md`. ASM-5 (systemd and Python >= 3.12 on the VM) is not yet checked.
- Not verifiable here: 2 h run, 5 min network cut, VM restart (R-2 over 2 h, R-7, R-8, Done When).

## Independent Verification Readiness
Not ready for the final verdict until the VM QA below is run and logged. Ready for the verifier to inspect the code, the tests and the gates.

## Pending VM QA (manual, with a log)
Run on the VM as a user with sudo.

1. Preconditions (ASM-5 and clock):
   ```
   python3 --version            # must be 3.12 or newer
   systemctl --version | head -1
   timedatectl                  # "System clock synchronized: yes"
   ```
2. Install and enable (this procedure has never been executed on a VM; it was corrected after verification finding F-3 by reading, not by running):
   ```
   sudo useradd --system --create-home --home-dir /opt/polyquack --shell /usr/sbin/nologin polyquack
   sudo -u polyquack -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
   sudo -u polyquack -H git clone -b feat/btc-ingestion/josueDev https://github.com/sue-btis/PolyQuack.git /opt/polyquack/app
   sudo -u polyquack -H /opt/polyquack/.local/bin/uv sync --no-dev --directory /opt/polyquack/app
   sudo install -m 644 /opt/polyquack/app/deploy/polyquack-ingestion.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now polyquack-ingestion
   systemctl is-active polyquack-ingestion       # active
   systemctl is-enabled polyquack-ingestion      # enabled
   ```
3. 2 h run (AC-2, AC-3, AC-4, AC-7, AC-10): Needs the `sqlite3` command-line tool (install it with the VM's package manager).
   ```
   journalctl -u polyquack-ingestion --since "2 hours ago" > m01-run.log
   grep -c "price request" m01-run.log           # about 240 = 2 per minute
   grep -c " 429" m01-run.log                    # expected 0 unhandled
   sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack status
   ```
   Expected: per platform 2 funding readings (or a funding gap per missing hour), a snapshot and a price (or its gap) per minute, Hyperliquid prices with null `source_time`. Count them:
   ```
   sqlite3 /var/lib/polyquack/polyquack.db "select instrument_id, count(*) from book_snapshot group by 1; select instrument_id, count(*) from price_reading group by 1; select kind, status, count(*) from gap group by 1,2;"
   ```
   Check no minute has both a snapshot and a `book_snapshot` gap:
   ```
   sqlite3 /var/lib/polyquack/polyquack.db "select count(*) from gap g join book_snapshot b on b.instrument_id=g.instrument_id and b.minute=g.starts_at where g.kind='book_snapshot';"   # 0
   ```
4. Network cut (AC-5): disconnect the VM's network for 5 minutes, then restore it.
   ```
   journalctl -u polyquack-ingestion --since "15 minutes ago" | grep -E "connection lost|connected|subscribed|resync"
   sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack status
   ```
   Expected: `snapshot` and `price` gaps for the cut minutes, `connected` + `subscribed` + `resync … done` after the restore, new snapshots afterwards.
5. VM restart (AC-6): `sudo reboot`; after it comes back, within 10 minutes:
   ```
   systemctl is-active polyquack-ingestion
   sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack status
   ```
   Expected: the latest book and price readings are less than 10 minutes after boot; the minutes while the VM was off appear as `not_collected` gaps.
6. Record the outputs in a log next to this file and report any deviation to the verifier.

## Correction Rounds
### Round 1 — after verification pass 1 (2026-10-28)
- Findings addressed: F-1, F-2, F-3. F-4 to F-12 (author decisions) were not touched.
- Files changed: `src/polyquack/ingestion/feed.py`; `tests/test_feed.py`, `tests/test_parsers.py` (new), `tests/test_book.py`, `tests/test_service.py`, `tests/test_storage.py`; `tests/fixtures/` (new: `pm_instruments.json`, `hl_meta.json`, `pm_book_depth100.json`, `hl_book.json`, `pm_funding.json`, `hl_funding.json`, fetched once from the public read-only endpoints and trimmed only in the instrument lists); `README.md`, `deploy/polyquack-ingestion.service`; in this file the VM QA install and status commands; `docs/design/review.md` (F-006 resolution text).
- New diff range: working tree (no commits); the inventory is the one in `verification.md` plus the files above.
- Preflight delta: none. No formatter or linter was run on `docs/` (`pyproject.toml` excludes it; ruff was run as `ruff ... src tests`).

**F-1 (reconnect delay not reset after an abnormal close).**
- Regression test first: `tests/test_feed.py::test_reconnect_delay_returns_to_the_initial_one_after_an_aborted_healthy_session` (local websocket server sends a book message and aborts the transport, twice). Before the fix `uv run pytest tests/test_feed.py` failed: `AssertionError: assert ['local: reco...cting in 4 s'] == ['local: reco...cting in 1 s']`, with the log showing `reconnecting in 2 s` then `reconnecting in 4 s`; `1 failed, 1 passed in 8.00s`.
- Fix: `BookFeed` keeps `_received`, set by the reading loop whenever a book message is applied, and `run` resets the delay from it whatever the exit path. After the fix: `2 passed in 3.84s`.
- Added `test_reconnect_delay_doubles_while_sessions_receive_nothing` so the growth is also pinned.

**F-2 (behaviour tests for the survivors).** New tests: late-price gap (`test_service.py`), Hyperliquid delisted skip, Polymarket and Hyperliquid funding parsers including request parameters, tolerance and closest-payment choice (`test_parsers.py`), funding stamped just before the hour (`test_storage.py`), REST depth 100 cut to 50 and Hyperliquid book parsing (`test_parsers.py`), status 24 h window (`test_service.py`), reconnect reset (`test_feed.py`), exact 0.5% boundary inclusive on both sides (`test_book.py`). TST-1 now runs the real instrument parsers over the trimmed real lists (Polymarket: SP500, BTC, ETH; Hyperliquid: BTC, ETH, kPEPE and three delisted coins), pairs them, lists the unpaired ones and repeats the load without duplicates; the earlier `InstrumentInfo`-built pairing test in `test_storage.py` was replaced by it.
- Mutation re-check by hand on the survivors, one mutant at a time, each restored afterwards (the tree was diffed against a backup and is identical): late check removed, delisted filter removed, closest payment changed to the farthest, hour rounding removed, bid cut removed, ask cut removed, status window sign flipped, inclusive bid boundary made exclusive, inclusive ask boundary made exclusive, delay reset removed. Each mutant made one test fail (`1 failed` each); none survived.

**F-3 (VM install steps).** The service user is now created with its home at `/opt/polyquack` (`--create-home`), installs its own `uv` there, and clones into `/opt/polyquack/app`, so it owns the checkout, `.venv` and the uv cache; the unit's `WorkingDirectory` and `ExecStart` point at `/opt/polyquack/app`. Status and `sqlite3` commands were adjusted (`sudo -u polyquack env POLYQUACK_DB=... .../polyquack status`; `sqlite3` needs to be installed). This procedure is still unexecuted on a VM: it was corrected by reading, and step 2 of the VM QA is the first time it will run.

**Review ledger.** `docs/design/review.md` F-006 now says `check-package.mjs` exits 0 ("Package checks passed.", run by the verifier).

**Checks run after the round (repository root, 2026-10-28):**
| Command | Result |
|---|---|
| `uv run mypy --strict src tests` | `Success: no issues found in 22 source files`, exit 0 |
| `uv run ruff check src tests` | `All checks passed!`, exit 0 |
| `uv run ruff format --check src tests` | `22 files already formatted`, exit 0 |
| `uv run ruff check` | `All checks passed!`, exit 0 |
| `uv run ruff format --check` | `23 files already formatted` (the extra file is `tests/test_parsers.py`), exit 0 |
| `uv run pytest` | `48 passed in 7.25s`, exit 0 |
| `gitleaks detect --no-git --source . --redact --no-banner` | `no leaks found`, exit 0 |
