import asyncio

from polyquack.ingestion.platforms import HISTORY_FLOOR_MS, HYPERLIQUID, POLYMARKET
from polyquack.ingestion.service import Service
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

from .conftest import T0, make_service_for, seed_pairs
from .exchange import FakeExchange

HOUR = floor_to(T0, HOUR_MS)
NOW = HOUR + 5 * MINUTE_MS


def _hourly(first_hour: int, last_hour: int, stamp: int = 40) -> list[tuple[int, str]]:
    return [(h + stamp, "0.0000125") for h in range(first_hour, last_hour + 1, HOUR_MS)]


def _service(db: Database, exchange: FakeExchange, assets: list[str], now: int = NOW) -> Service:
    return make_service_for(db, exchange.platforms(), assets, now, valid_book=False)


def _funding(db: Database, platform: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        "SELECT r.source_time, r.origin FROM funding_reading r"
        " JOIN instrument i ON i.id = r.instrument_id JOIN platform p ON p.id = i.platform_id"
        " WHERE p.name = ? ORDER BY r.source_time",
        (platform,),
    ).fetchall()
    return [(str(a), str(b)) for a, b in rows]


def test_polymarket_backfill_pages_backward_from_the_floor_and_stores_nothing_before_it(
    db: Database,
) -> None:
    exchange = FakeExchange()
    before_floor = HISTORY_FLOOR_MS - 5 * HOUR_MS
    exchange.pm_funding["1"] = _hourly(before_floor, HOUR)
    service = _service(db, exchange, ["BTC"])

    asyncio.run(service.backfill_funding(POLYMARKET))

    stored = _funding(db, POLYMARKET)
    expected_hours = (HOUR - HISTORY_FLOOR_MS) // HOUR_MS + 1
    assert len(stored) == expected_hours > 200
    assert stored[0][0] == iso(HISTORY_FLOOR_MS + 40)
    assert {origin for _, origin in stored} == {"history"}
    pages = [r for r in exchange.requests if r == (POLYMARKET, "/v1/info/funding")]
    assert len(pages) == -(-expected_hours // 100)


def test_hyperliquid_backfill_pages_forward_in_pages_of_500(db: Database) -> None:
    exchange = FakeExchange()
    exchange.hl_funding["BTC"] = _hourly(HISTORY_FLOOR_MS - 3 * HOUR_MS, HOUR)
    service = _service(db, exchange, ["BTC"])

    asyncio.run(service.backfill_funding(HYPERLIQUID))

    stored = _funding(db, HYPERLIQUID)
    expected_hours = (HOUR - HISTORY_FLOOR_MS) // HOUR_MS + 1
    assert len(stored) == expected_hours
    assert stored[0][0] == iso(HISTORY_FLOOR_MS + 40)
    assert [r for r in exchange.requests if r[0] == HYPERLIQUID] == [
        (HYPERLIQUID, "fundingHistory")
    ] * (1 + expected_hours // 500)


def test_backfill_runs_up_to_the_earliest_stored_hour_and_is_not_repeated_once_complete(
    db: Database,
) -> None:
    exchange = FakeExchange()
    exchange.pm_funding["1"] = _hourly(HISTORY_FLOOR_MS, HOUR + 3 * HOUR_MS)
    service = _service(db, exchange, ["BTC"])
    target = next(t for t in service.targets if t.platform == POLYMARKET)
    db.insert_funding(target.instrument_id, HOUR + 40, 0.0000125, NOW)

    asyncio.run(service.backfill_funding(POLYMARKET))

    hours = [t for t, _ in _funding(db, POLYMARKET)]
    assert hours[-1] == iso(HOUR + 40)
    assert iso(HOUR + HOUR_MS + 40) not in hours
    requests_after_first = len(exchange.requests)

    asyncio.run(service.backfill_funding(POLYMARKET))

    assert len(exchange.requests) == requests_after_first


def test_history_requests_of_a_platform_never_overlap(db: Database) -> None:
    exchange = FakeExchange()
    assets = ["AAA", "BBB", "CCC"]
    for number, asset in enumerate(assets, start=1):
        exchange.pm_funding[str(number)] = _hourly(HISTORY_FLOOR_MS, HOUR)
        exchange.hl_funding[asset] = _hourly(HISTORY_FLOOR_MS, HOUR)
    service = _service(db, exchange, assets)

    async def both() -> None:
        await asyncio.gather(
            service.backfill_funding(POLYMARKET), service.backfill_funding(HYPERLIQUID)
        )

    asyncio.run(both())

    assert exchange.max_in_flight["api.perpetuals.polymarket.com"] == 1
    assert exchange.max_in_flight["api.hyperliquid.xyz"] == 1
    assert len(_funding(db, POLYMARKET)) > 3 * 100


def _outage(db: Database, service: Service, platform: str) -> list[int]:
    """Funding stored for HOUR, then the service is down until HOUR + 4 h."""
    target = next(t for t in service.targets if t.platform == platform)
    db.insert_funding(target.instrument_id, HOUR + 40, 0.0000125, NOW)
    assert service._pending(target, "funding", HOUR + 4 * HOUR_MS)
    return [HOUR + n * HOUR_MS for n in range(1, 4)]


def test_recovery_closes_outage_gaps_with_real_readings_and_book_gaps_stay_final(
    db: Database,
) -> None:
    exchange = FakeExchange()
    exchange.pm_funding["1"] = _hourly(HISTORY_FLOOR_MS, HOUR + 5 * HOUR_MS)
    service = _service(db, exchange, ["BTC"], now=HOUR + 4 * HOUR_MS + 25 * MINUTE_MS)
    missed = _outage(db, service, POLYMARKET)
    for state in service.books.values():
        state.invalidate("disconnected")
    service.close_minute(HOUR)
    service.close_minute(HOUR + 60 * MINUTE_MS)

    asyncio.run(service.recover_funding(POLYMARKET))

    funding_gaps = db.conn.execute(
        "SELECT starts_at, status, closed_at FROM gap WHERE kind = 'funding' ORDER BY starts_at"
    ).fetchall()
    assert funding_gaps == [(iso(h), "closed_with_data", iso(service._now())) for h in missed]
    stored = dict(_funding(db, POLYMARKET))
    assert all(stored[iso(h + 40)] == "history" for h in missed)
    book_gaps = db.conn.execute(
        "SELECT DISTINCT status FROM gap WHERE kind = 'book_snapshot'"
    ).fetchall()
    assert book_gaps == [("final",)]
    assert (
        db.conn.execute("SELECT count(*) FROM gap WHERE kind = 'book_snapshot'").fetchone()[0]
        == 2 * 61
    )


def test_gap_without_payment_in_history_but_with_later_ones_becomes_final(db: Database) -> None:
    exchange = FakeExchange()
    hours = [h for h in range(HOUR, HOUR + 6 * HOUR_MS, HOUR_MS) if h != HOUR + 2 * HOUR_MS]
    exchange.hl_funding["BTC"] = [(h + 40, "0.0000125") for h in hours]
    service = _service(db, exchange, ["BTC"], now=HOUR + 4 * HOUR_MS + 25 * MINUTE_MS)
    _outage(db, service, HYPERLIQUID)

    asyncio.run(service.recover_funding(HYPERLIQUID))

    statuses = db.conn.execute(
        "SELECT starts_at, status FROM gap WHERE kind = 'funding' ORDER BY starts_at"
    ).fetchall()
    assert statuses == [
        (iso(HOUR + HOUR_MS), "closed_with_data"),
        (iso(HOUR + 2 * HOUR_MS), "final"),
        (iso(HOUR + 3 * HOUR_MS), "closed_with_data"),
    ]
    assert iso(HOUR + 2 * HOUR_MS + 40) not in dict(_funding(db, HYPERLIQUID))


def test_gap_stays_open_when_history_has_nothing_later_or_the_request_fails(
    db: Database,
) -> None:
    exchange = FakeExchange()
    exchange.hl_funding["BTC"] = [(HOUR + 40, "0.0000125")]
    service = _service(db, exchange, ["BTC"], now=HOUR + 4 * HOUR_MS + 25 * MINUTE_MS)
    _outage(db, service, HYPERLIQUID)

    asyncio.run(service.recover_funding(HYPERLIQUID))
    exchange.fail_history = True
    exchange.hl_funding["BTC"] = _hourly(HOUR, HOUR + 5 * HOUR_MS)
    asyncio.run(service.recover_funding(HYPERLIQUID))

    statuses = db.conn.execute("SELECT DISTINCT status FROM gap WHERE kind = 'funding'").fetchall()
    assert statuses == [("open",)]
    assert len(_funding(db, HYPERLIQUID)) == 1


def test_gap_stays_open_when_the_history_in_the_window_only_has_earlier_payments(
    db: Database,
) -> None:
    exchange = FakeExchange()
    exchange.hl_funding["BTC"] = [(HOUR + HOUR_MS + 40, "0.0000125")]
    service = _service(db, exchange, ["BTC"], now=HOUR + 4 * HOUR_MS + 25 * MINUTE_MS)
    _outage(db, service, HYPERLIQUID)

    asyncio.run(service.recover_funding(HYPERLIQUID))

    statuses = db.conn.execute(
        "SELECT starts_at, status FROM gap WHERE kind = 'funding' ORDER BY starts_at"
    ).fetchall()
    assert statuses == [
        (iso(HOUR + HOUR_MS), "closed_with_data"),
        (iso(HOUR + 2 * HOUR_MS), "open"),
        (iso(HOUR + 3 * HOUR_MS), "open"),
    ]


def test_recovery_without_open_gaps_makes_no_request(db: Database) -> None:
    exchange = FakeExchange()
    seed_pairs(db, ["BTC"])
    service = Service(db, exchange.platforms(), (), clock=lambda: NOW)
    service.targets = db.targets()

    asyncio.run(service.recover_funding(POLYMARKET))

    assert exchange.requests == []
