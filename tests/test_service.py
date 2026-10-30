import asyncio

import httpx

from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.status import render_status
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

from .conftest import T0, make_service, platforms_over

PM_TICKERS = [
    {
        "instrument_id": 6,
        "symbol": "BTC-USD",
        "index_price": "81177",
        "mark_price": "81181",
        "funding_rate": "0.0000125",
        "timestamp": 1793223365393,
    }
]
HL_META_AND_CTXS = [
    {"universe": [{"szDecimals": 5, "name": "BTC", "maxLeverage": 40}]},
    [{"funding": "0.0000125", "markPx": "81187.0", "oraclePx": "81213.9"}],
]
HOUR = floor_to(T0, HOUR_MS)


def _rows(db: Database, sql: str) -> list[tuple[object, ...]]:
    return db.conn.execute(sql).fetchall()


def _prices_ok(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.hyperliquid.xyz":
        return httpx.Response(200, json=HL_META_AND_CTXS)
    return httpx.Response(200, json=PM_TICKERS)


def test_minute_with_a_valid_book_has_a_snapshot_and_no_gap(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0, valid_book=True)

    service.close_minute(T0)

    assert len(_rows(db, "SELECT * FROM book_snapshot")) == 2
    assert _rows(db, "SELECT * FROM gap") == []


def test_minute_without_a_valid_book_has_a_final_gap_and_no_snapshot(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0)
    for state in service.books.values():
        state.invalidate("disconnected")

    service.close_minute(T0)

    assert _rows(db, "SELECT * FROM book_snapshot") == []
    assert (
        _rows(db, "SELECT kind, starts_at, ends_at, cause, status FROM gap")
        == [("book_snapshot", iso(T0), iso(T0 + MINUTE_MS), "disconnected", "final")] * 2
    )


def test_elapsed_minutes_missed_by_a_stopped_service_become_gaps(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0, valid_book=True)
    service.close_minute(T0)

    service.close_minute(T0 + 3 * MINUTE_MS)

    gaps = _rows(db, "SELECT starts_at, cause FROM gap WHERE instrument_id = 1 ORDER BY starts_at")
    assert gaps == [
        (iso(T0 + MINUTE_MS), "not_collected"),
        (iso(T0 + 2 * MINUTE_MS), "not_collected"),
    ]
    minutes = _rows(db, "SELECT minute FROM book_snapshot WHERE instrument_id = 1 ORDER BY minute")
    assert minutes == [(iso(T0),), (iso(T0 + 3 * MINUTE_MS),)]


def test_a_minute_is_never_closed_twice(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0, valid_book=True)

    service.close_minute(T0)
    for state in service.books.values():
        state.invalidate("disconnected")
    service.close_minute(T0)

    assert _rows(db, "SELECT * FROM gap") == []
    assert len(_rows(db, "SELECT * FROM book_snapshot")) == 2


def test_hour_without_funding_leaves_an_open_gap(db: Database) -> None:
    def no_payment(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hyperliquid.xyz":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"data": [], "more": False})

    service = make_service(db, platforms_over(no_payment), HOUR + 16 * MINUTE_MS)

    asyncio.run(service.collect_funding(HYPERLIQUID, HOUR))

    assert _rows(db, "SELECT * FROM funding_reading") == []
    assert _rows(db, "SELECT kind, starts_at, ends_at, cause, status FROM gap") == [
        ("funding", iso(HOUR), iso(HOUR + HOUR_MS), "no_payment_at_source", "open")
    ]


def test_funding_payment_is_stored_with_the_source_time_and_live_origin(db: Database) -> None:
    payment_time = HOUR + 45

    def paid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"coin": "BTC", "fundingRate": "0.0000125", "premium": "0", "time": payment_time}
            ],
        )

    service = make_service(db, platforms_over(paid), HOUR + 2 * MINUTE_MS)

    asyncio.run(service.collect_funding(HYPERLIQUID, HOUR))

    assert _rows(db, "SELECT source_time, rate, received_at, origin FROM funding_reading") == [
        (iso(payment_time), 0.0000125, iso(HOUR + 2 * MINUTE_MS), "live")
    ]
    assert _rows(db, "SELECT * FROM gap") == []


def test_prices_store_polymarket_source_time_and_hyperliquid_null_source_time(
    db: Database,
) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0 + 1_000)

    asyncio.run(service.collect_prices(T0))

    rows = _rows(
        db,
        "SELECT p.name, r.mark_price, r.index_price, r.source_time, r.received_at"
        " FROM price_reading r JOIN instrument i ON i.id = r.instrument_id"
        " JOIN platform p ON p.id = i.platform_id ORDER BY p.id",
    )
    assert rows == [
        (POLYMARKET, 81181.0, 81177.0, iso(1793223365393), iso(T0 + 1_000)),
        (HYPERLIQUID, 81187.0, 81213.9, None, iso(T0 + 1_000)),
    ]
    assert _rows(db, "SELECT * FROM gap") == []


def test_failed_price_request_leaves_a_final_price_gap(db: Database) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hyperliquid.xyz":
            return httpx.Response(500)
        return httpx.Response(200, json=PM_TICKERS)

    service = make_service(db, platforms_over(failing), T0 + 1_000)

    asyncio.run(service.collect_prices(T0))

    assert _rows(db, "SELECT kind, starts_at, ends_at, cause, status FROM gap") == [
        ("price", iso(T0), iso(T0 + MINUTE_MS), "RestError('HTTP 500')", "final")
    ]
    assert len(_rows(db, "SELECT * FROM price_reading")) == 1


def test_price_response_arriving_after_its_minute_is_a_late_gap(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0 + MINUTE_MS)

    asyncio.run(service.collect_prices(T0))

    assert _rows(db, "SELECT * FROM price_reading") == []
    assert _rows(db, "SELECT kind, cause, status FROM gap") == [
        ("price", "late", "final"),
        ("price", "late", "final"),
    ]


def test_failed_instruments_request_leaves_a_gap_and_stores_nothing(db: Database) -> None:
    service = make_service(
        db, platforms_over(lambda request: httpx.Response(503)), T0, valid_book=True
    )

    assert asyncio.run(service.refresh_instruments(HYPERLIQUID)) is False

    assert _rows(db, "SELECT kind, instrument_id, status FROM gap") == [
        ("instruments", None, "final")
    ]


def test_status_shows_latest_readings_gaps_and_unpaired_instruments(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0 + 1_000, valid_book=True)
    service.close_minute(T0)
    asyncio.run(service.collect_prices(T0))
    service.close_minute(T0 + 2 * MINUTE_MS)

    text = render_status(db, ("BTC",), T0 + 3 * MINUTE_MS)

    assert "Pair BTC" in text
    assert f"book:    {iso(T0 + 2 * MINUTE_MS)}" in text
    assert "mark=81181.0 index=81177.0" in text
    assert "funding: none" in text
    assert "book_snapshot" in text and "not_collected" in text
    assert "Unpaired instruments: 0" in text


def test_status_lists_only_gaps_of_the_last_24_hours(db: Database) -> None:
    service = make_service(db, platforms_over(_prices_ok), T0)
    now = T0 + 30 * HOUR_MS
    old_start, recent_start = now - 25 * HOUR_MS, now - 23 * HOUR_MS
    for start in (old_start, recent_start):
        db.insert_gap(
            POLYMARKET, service.targets[0].instrument_id, "price", start, start + 1, "x", "final"
        )

    text = render_status(db, ("BTC",), now)

    assert "gaps in the last 24 h: 1 interval(s)" in text
    assert iso(recent_start) in text
    assert iso(old_start) not in text
