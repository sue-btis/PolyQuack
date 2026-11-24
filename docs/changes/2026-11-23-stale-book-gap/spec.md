# Stale book becomes a snapshot gap

Status: Ready for implementation
Size: quick
Reliability: lean
Implementation effort: medium
Triggered artifacts: none

Goal: when a minute closes and the instrument's in-memory book is more than 120 s older than the end of that minute, ingestion stores a final `book_snapshot` gap with cause `stale_book` instead of a snapshot row.

Why: on 2026-11-10, 11-11, 11-15 and 11-17 Polymarket Perps stopped pushing book messages while its edge proxy kept the websocket open and answered pings for 1.5 to 5 minutes. `BookFeed` only invalidates books on disconnection, so the last book was stored as each new minute (153 `(instrument_id, source_time)` ties, ages up to 251 s) and `completeness` counted those minutes as covered. Evidence: VM queries and journal recorded in the session notes of 2026-11-23; author chose this fix.

Evidence facts:
- Entry point: `src/polyquack/ingestion/service.py:212` (`Service._close_target_minute`)
- Covering tests: `tests/test_service.py:39`, `tests/test_service.py:48`
- Consumers of altered contracts: `gap.cause` gains the value `stale_book`: free text, read only by `src/polyquack/status.py:66` (display) — grep `grep -rn "cause" src --include=*.py`. `book_snapshot` rows are no longer written for those minutes: read by `src/polyquack/completeness.py` (count by minute) and `src/polyquack/evaluation/readings.py:151` (by `source_time`, within 120 s of the decision instant) — grep `grep -rn "book_snapshot" src`.

Scope:
- Include: the age check in `_close_target_minute`, its tests, and the design notes that describe snapshot gaps.
- Exclude: a feed watchdog or reconnect on silence; cleanup or rewriting of existing rows (tables are insert-only); staleness of `price_reading`; any change to the evaluator.

Acceptance:
- AC-1: a book whose `source_time` is more than 120 s before `minute + 60 s` produces one final `book_snapshot` gap for that minute with cause `stale_book`, and no snapshot row.
- AC-2: a book exactly 120 s old at the end of the minute is stored as a snapshot (boundary is strictly greater than).
- AC-3: existing behavior is preserved: a fresh book stores a snapshot and no gap; a missing book stores a gap with its invalid cause; an empty side stores `empty_book`.

Change surface:
- Expected: `src/polyquack/ingestion/service.py`, `tests/test_service.py`, `docs/design/data/schema.dbml` (gap.cause note), `docs/design/domain.md` (Book snapshot / Gap).
- Do not touch: `ingestion/feed.py`, `ingestion/book.py`, `evaluation/`, `storage/schema.sql`.

Canonical design:
- Affected authorities: `docs/design/domain.md`, `docs/design/data/schema.dbml`.
- Required synchronization: update — state that a minute whose book is older than 120 s at the minute's end is a gap with cause `stale_book`.

Quality:
- Tests: AC-1 and AC-2 as new tests in `tests/test_service.py`; existing service tests cover AC-3.
- Static/build: `uv run mypy --strict src tests`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest`, gitleaks.
- QA: after deploy, `journalctl -u polyquack-ingestion | grep stale_book` and the tie query `GROUP BY instrument_id, source_time HAVING count(*) > 1` restricted to minutes after the deploy.

Done when: `uv run pytest tests/test_service.py` passes with the AC-1 and AC-2 tests failing before the fix and passing after it. End-to-end on the VM depends on a future Polymarket stall and is not reproducible on demand.

Implementation:
1. Add the AC-1 and AC-2 tests; confirm AC-1 fails on the current code.
2. In `_close_target_minute`, when the book exists and `minute_ms + MINUTE_MS - book.source_time_ms > 120 s`, take the gap path with cause `stale_book`.
3. Update the two design notes; run the gates.

Stop if:
- a test or caller relies on a stale book being stored as a snapshot;
- the threshold needs to differ from 120 s or be configurable (new decision for the author).
