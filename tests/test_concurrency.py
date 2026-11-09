import asyncio
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest

from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.ingestion.service import _is_lock_contention
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

from .conftest import T0, make_service_for, platforms_over
from .exchange import FakeExchange

HOUR = floor_to(T0, HOUR_MS)


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    other = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")
    return other


def _snapshots(db: Database) -> list[str]:
    rows = db.conn.execute("SELECT minute FROM book_snapshot ORDER BY minute").fetchall()
    return [str(r[0]) for r in rows]


def test_a_second_writer_shorter_than_the_busy_timeout_does_not_lose_the_snapshot(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "shared.db")
    service = make_service_for(db, platforms_over(lambda r: httpx.Response(500)), ["BTC"], T0)
    other = _hold_write_lock(tmp_path / "shared.db")
    release = threading.Timer(0.3, lambda: other.execute("COMMIT"))
    release.start()

    service.close_minute(T0)

    release.join()
    assert _snapshots(db) == [iso(T0)] * 2
    assert db.conn.execute("SELECT count(*) FROM gap").fetchone()[0] == 0


def test_a_second_writer_longer_than_the_busy_timeout_leaves_a_gap_at_the_next_tick(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = Database(tmp_path / "shared.db", busy_timeout_ms=200)
    service = make_service_for(db, platforms_over(lambda r: httpx.Response(500)), ["BTC"], T0)
    service.close_minute(T0 - MINUTE_MS)
    other = _hold_write_lock(tmp_path / "shared.db")

    with caplog.at_level(logging.ERROR):
        service.close_minute(T0)

    assert iso(T0) not in _snapshots(db)
    assert "write failed" in caplog.text
    other.execute("COMMIT")

    service.close_minute(T0 + MINUTE_MS)

    gaps = db.conn.execute(
        "SELECT starts_at, cause, status FROM gap WHERE instrument_id = 1"
    ).fetchall()
    assert gaps == [(iso(T0), "not_collected", "final")]
    assert iso(T0 + MINUTE_MS) in _snapshots(db)


def test_a_write_error_that_is_not_lock_contention_propagates_out_of_the_minute_close(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service_for(db, platforms_over(lambda r: httpx.Response(500)), ["BTC"], T0)

    def broken(*args: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "insert_snapshot", broken)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        service.close_minute(T0)


def _coded(code: int | None) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("x")
    if code is not None:
        error.sqlite_errorcode = code
    return error


@pytest.mark.parametrize(
    ("code", "is_lock"),
    [
        (sqlite3.SQLITE_BUSY, True),
        (sqlite3.SQLITE_LOCKED, True),
        (261, True),  # SQLITE_BUSY_RECOVERY
        (517, True),  # SQLITE_BUSY_SNAPSHOT
        (773, True),  # SQLITE_BUSY_TIMEOUT
        (262, True),  # SQLITE_LOCKED_SHAREDCACHE
        (sqlite3.SQLITE_ERROR, False),
        (10, False),  # SQLITE_IOERR
        (1555, False),  # SQLITE_CONSTRAINT_PRIMARYKEY
        (None, False),
    ],
)
def test_lock_contention_is_classified_by_the_primary_result_code(
    code: int | None, is_lock: bool
) -> None:
    assert _is_lock_contention(_coded(code)) is is_lock


def test_a_non_lock_error_while_writing_history_propagates(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    exchange = FakeExchange()
    exchange.hl_funding["BTC"] = [(T0, "0.0000125")]
    service = make_service_for(db, exchange.platforms(), ["BTC"], T0 + HOUR_MS)

    def broken(*args: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "insert_funding_history", broken)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        asyncio.run(service.backfill_funding(HYPERLIQUID))


def test_elapsed_intervals_of_an_instrument_are_written_in_one_transaction(db: Database) -> None:
    assets = [f"A{n:02d}" for n in range(38)]
    service = make_service_for(db, platforms_over(lambda r: httpx.Response(500)), assets, T0)
    service.close_minute(T0)
    statements: list[str] = []
    db.conn.set_trace_callback(statements.append)

    service.close_minute(T0 + 60 * MINUTE_MS)

    commits = statements.count("COMMIT")
    assert len(service.targets) == 76
    assert commits <= 2 * len(service.targets)
    gaps = db.conn.execute("SELECT count(*) FROM gap").fetchone()[0]
    assert gaps == 59 * len(service.targets)


def test_one_simulated_hour_of_100_pairs_closes_every_minute_and_the_hour(
    db: Database,
) -> None:
    assets = [f"A{n:03d}" for n in range(100)]
    answered = set(assets[:90])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hyperliquid.xyz":
            coin = json.loads(request.content)["coin"]
            rows = [{"coin": coin, "fundingRate": "0.0000125", "time": HOUR + 30}]
            return httpx.Response(200, json=rows if coin in answered else [])
        number = int(request.url.params["instrument_id"])
        has = assets[number - 1] in answered
        data = [{"funding_rate": "0.0000125", "timestamp": HOUR + 30}] if has else []
        return httpx.Response(200, json={"data": data, "more": False})

    service = make_service_for(db, platforms_over(handler), assets, HOUR + 16 * MINUTE_MS)
    durations: list[float] = []
    for minute in range(60):
        started = time.perf_counter()
        service.close_minute(HOUR + minute * MINUTE_MS)
        durations.append(time.perf_counter() - started)
    for name in (POLYMARKET, HYPERLIQUID):
        asyncio.run(service.collect_funding(name, HOUR))

    per_instrument = db.conn.execute(
        "SELECT instrument_id, count(*) FROM book_snapshot GROUP BY instrument_id"
    ).fetchall()
    assert len(per_instrument) == 200 and {n for _, n in per_instrument} == {60}
    funding = db.conn.execute("SELECT count(*) FROM funding_reading").fetchone()[0]
    funding_gaps = db.conn.execute("SELECT count(*) FROM gap WHERE kind = 'funding'").fetchone()[0]
    assert (funding, funding_gaps) == (180, 20)
    print(f"close of 200: max {max(durations):.3f} s, mean {sum(durations) / 60:.3f} s")
    # The real budget is the minute itself; single closes spike to several seconds on
    # Windows commits, so a tight max bound fails at random.
    assert sum(durations) / 60 < 1.0 and max(durations) < 30.0
