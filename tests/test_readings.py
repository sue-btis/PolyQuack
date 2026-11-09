import pytest

from polyquack.evaluation.readings import Reader
from polyquack.ingestion.models import FeeRate
from polyquack.ingestion.platforms import POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS

from .evalkit import D0, H0, PM_ASKS, PM_BIDS, book, fund, seed_world


def test_r9_funding_after_the_cutoff_is_never_returned_even_inside_the_same_hour(
    db: Database,
) -> None:
    pm, _ = seed_world(db)
    fund(db, pm, H0, 0.0001)
    fund(db, pm, H0, 9.0, lag_ms=22 * MINUTE_MS)
    fund(db, pm, H0 + HOUR_MS, 7.0)

    rates = Reader(db.conn, D0).funding_by_hour(pm, H0, H0 + HOUR_MS)

    assert rates == {H0: 0.0001}


def test_r9_the_latest_reading_of_an_hour_up_to_the_cutoff_wins(db: Database) -> None:
    pm, _ = seed_world(db)
    fund(db, pm, H0, 0.0001, lag_ms=-1_000)
    fund(db, pm, H0, 0.0002, lag_ms=5_000)

    assert Reader(db.conn, D0).funding_by_hour(pm, H0, H0) == {H0: 0.0002}


def test_r9_data_until_is_the_latest_source_time_returned_and_never_after_the_cutoff(
    db: Database,
) -> None:
    pm, _ = seed_world(db)
    fund(db, pm, H0 - HOUR_MS, 0.0001)
    fund(db, pm, H0, 0.0002)
    fund(db, pm, H0, 5.0, lag_ms=30 * MINUTE_MS)
    reader = Reader(db.conn, D0)

    assert reader.data_until_ms is None
    reader.funding_by_hour(pm, H0 - HOUR_MS, H0)

    assert reader.data_until_ms == H0 + 51


@pytest.mark.parametrize(
    ("source_time_ms", "usable"),
    [(D0 - 120_000, True), (D0 - 120_001, False), (D0, True), (D0 + 1, False)],
)
def test_dec4_snapshot_must_be_at_or_before_the_cutoff_and_at_most_120_seconds_old(
    db: Database, source_time_ms: int, usable: bool
) -> None:
    pm, _ = seed_world(db)
    book(db, pm, D0 - 10 * MINUTE_MS, PM_BIDS, PM_ASKS, source_time_ms=source_time_ms)

    assert (Reader(db.conn, D0).snapshot(pm, 120_000) is not None) is usable


def test_dec4_the_latest_usable_snapshot_is_chosen(db: Database) -> None:
    pm, _ = seed_world(db)
    book(db, pm, D0 - 3 * MINUTE_MS, PM_BIDS, PM_ASKS)
    book(db, pm, D0 - 2 * MINUTE_MS, [(100.0, 1.0)], [(100.1, 1.0)])
    book(db, pm, D0, PM_BIDS, PM_ASKS)

    snapshot = Reader(db.conn, D0 + 2_000).snapshot(pm, 120_000)

    assert snapshot is not None
    assert snapshot.minute_ms == D0 - 2 * MINUTE_MS
    assert snapshot.bids == [(100.0, 1.0)]
    assert snapshot.asks == [(100.1, 1.0)]


def test_dec3_the_fee_is_the_base_tier_of_the_latest_row_effective_by_the_cutoff(
    db: Database,
) -> None:
    seed_world(db)
    db.sync_fees(POLYMARKET, [FeeRate("crypto", "0", 0.0009, 0.0002, D0 + 1)], D0 + 1)
    db.sync_fees(POLYMARKET, [FeeRate("crypto", "1000000", 0.0001, 0.0, D0 - 1)], D0 - 1)

    assert Reader(db.conn, D0).taker_fee(POLYMARKET, "crypto") == 0.0004
    assert Reader(db.conn, D0 + 1).taker_fee(POLYMARKET, "crypto") == 0.0009
    assert Reader(db.conn, D0).taker_fee(POLYMARKET, "equity") is None
    assert Reader(db.conn, H0 - 48 * HOUR_MS).taker_fee(POLYMARKET, "crypto") is None


def test_r8_payments_are_strictly_after_the_opening_and_clamped_to_the_cutoff(
    db: Database,
) -> None:
    pm, _ = seed_world(db)
    fund(db, pm, H0, 0.0001)
    fund(db, pm, H0 + HOUR_MS, 0.0002)
    fund(db, pm, H0 + 2 * HOUR_MS, 0.0003)
    reader = Reader(db.conn, H0 + 2 * HOUR_MS)

    payments = reader.payments(pm, H0 + 51, H0 + 10 * HOUR_MS)

    assert payments == [(H0 + HOUR_MS + 51, 0.0002)]
    assert reader.payments(pm, H0 + 50, H0 + 51) == [(H0 + 51, 0.0001)]


def test_f4_pair_status_is_read_as_of_the_cutoff_with_delisted_over_close_only_over_active(
    db: Database,
) -> None:
    pm, hl = seed_world(db)
    db.set_status(pm, "close_only", D0 - HOUR_MS)
    db.set_status(hl, "delisted", D0 + HOUR_MS)

    assert Reader(db.conn, D0 - 2 * HOUR_MS).pair_status(pm, hl) == "active"
    assert Reader(db.conn, D0).pair_status(pm, hl) == "close_only"
    assert Reader(db.conn, D0 + HOUR_MS).pair_status(pm, hl) == "delisted"
