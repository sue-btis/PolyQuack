import sqlite3

import pytest

from polyquack.ingestion.platforms import POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

from .conftest import T0, seed_btc

READINGS = {
    "funding_reading": (
        "INSERT INTO funding_reading VALUES (1, 't', 0.1, 't', 'live')",
        "UPDATE funding_reading SET rate = 0.2",
    ),
    "book_snapshot": (
        "INSERT INTO book_snapshot VALUES (1, 'm', 't', 1, 2, 1, 1, '[]', '[]', 0.1, 0.1)",
        "UPDATE book_snapshot SET best_bid = 2",
    ),
    "price_reading": (
        "INSERT INTO price_reading VALUES (1, 'm', 1, 1, NULL, 't')",
        "UPDATE price_reading SET mark_price = 2",
    ),
}


@pytest.mark.parametrize("table", READINGS)
def test_reading_tables_reject_update_and_delete(db: Database, table: str) -> None:
    seed_btc(db)
    insert, update = READINGS[table]
    db.conn.execute(insert)

    with pytest.raises(sqlite3.IntegrityError, match="insert-only"):
        db.conn.execute(update)
    with pytest.raises(sqlite3.IntegrityError, match="insert-only"):
        db.conn.execute(f"DELETE FROM {table}")


def test_gap_status_can_still_be_updated(db: Database) -> None:
    seed_btc(db)
    db.insert_gap(POLYMARKET, 1, "funding", T0, T0 + 1, "x", "open")

    with db.conn:
        db.conn.execute("UPDATE gap SET status = 'closed_with_data', closed_at = 't'")


def test_funding_stamped_just_before_the_hour_covers_that_hour(db: Database) -> None:
    seed_btc(db)
    hour = floor_to(T0, HOUR_MS)

    db.insert_funding(1, hour - 50, 0.0000125, hour + MINUTE_MS)

    assert db.covered_until_ms(1, "funding") == hour + HOUR_MS


def test_requesting_the_instruments_again_does_not_duplicate_rows(db: Database) -> None:
    for _ in range(2):
        seed_btc(db)

    counts = [
        db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("asset", "instrument", "pair")
    ]
    assert counts == [1, 2, 1]


def test_iso_has_millisecond_precision_and_sorts_like_time() -> None:
    assert iso(1_793_223_365_393) == "2026-10-28T21:36:05.393Z"
    assert iso(T0) < iso(T0 + 1)
