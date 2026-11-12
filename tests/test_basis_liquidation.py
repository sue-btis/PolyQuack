import sqlite3
from collections.abc import Collection
from pathlib import Path
from typing import Any

import pytest

from polyquack.evaluation import runner
from polyquack.evaluation.liquidation import liquidation_price
from polyquack.evaluation.preregistration import preregister
from polyquack.evaluation.runner import evaluate
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, iso

from .evalkit import (
    D0,
    H0,
    HL_ASKS,
    HL_BIDS,
    PM_ASKS,
    PM_BIDS,
    book,
    decision_at,
    decisions,
    fund_spread,
    future_data_violations,
    prereg_text,
    run_hours,
    seed_prices,
    seed_world,
    set_margin,
    set_price,
    standard_books,
)

REGISTERED_AT = H0 - 30 * MINUTE_MS
MARGIN = 0.025


def _minute(offset: int) -> int:
    return D0 + offset * MINUTE_MS


def _world(
    db: Database,
    margins: bool = True,
    pm_gaps: Collection[int] = (),
    hl_gaps: Collection[int] = (),
) -> tuple[int, int]:
    pm, hl = seed_world(db)
    preregister(db, prereg_text(), REGISTERED_AT)
    for instrument, gaps in ((pm, pm_gaps), (hl, hl_gaps)):
        if margins:
            set_margin(db, instrument, H0 - HOUR_MS, MARGIN)
        seed_prices(db, instrument, H0, 4 * 60, 100.0, skip=gaps)
    return pm, hl


def _open_world(
    db: Database,
    hours: int = 2,
    margins: bool = True,
    pm_gaps: Collection[int] = (),
    hl_gaps: Collection[int] = (),
) -> tuple[int, int]:
    """A short-Polymarket / long-Hyperliquid position opened at hour 0, priced at 100 throughout."""
    pm, hl = _world(db, margins, pm_gaps, hl_gaps)
    for index in range(hours):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, 0.0003)
        standard_books(db, pm, hl, decision_at(index))
    run_hours(db, 0)
    return pm, hl


def _measurements(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT minute, basis, basis_change, polymarket_liquidation_distance,"
        " hyperliquid_liquidation_distance FROM position_measurement ORDER BY minute"
    ).fetchall()


def _entry(db: Database, platform: str) -> tuple[float, float]:
    row = db.conn.execute(
        "SELECT t.avg_price, t.quantity FROM paper_trade t JOIN platform p ON p.id = t.platform_id"
        " WHERE t.kind = 'open' AND p.name = ?",
        (platform,),
    ).fetchone()
    return float(row[0]), float(row[1])


def _liquidations(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT p.name, t.hour, t.side, t.avg_price, t.best_price, t.quantity, t.fee,"
        " t.slippage, t.loss, t.snapshot_minute FROM paper_trade t"
        " JOIN platform p ON p.id = t.platform_id WHERE t.kind = 'liquidation' ORDER BY t.id"
    ).fetchall()


def _closes(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT p.name, t.hour, t.side, t.fee FROM paper_trade t"
        " JOIN platform p ON p.id = t.platform_id WHERE t.kind = 'close' ORDER BY t.id"
    ).fetchall()


def _position(db: Database) -> tuple[Any, ...]:
    row = db.conn.execute(
        "SELECT status, closed_at FROM paper_position ORDER BY id LIMIT 1"
    ).fetchone()
    return tuple(row)


def _payments(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT p.name, f.source_time, f.amount FROM paper_funding_payment f"
        " JOIN platform p ON p.id = f.platform_id ORDER BY f.source_time, p.id"
    ).fetchall()


def test_ac1_one_measurement_per_open_position_and_minute_before_the_next_decision(
    db: Database,
) -> None:
    _open_world(db)
    assert _measurements(db) == []

    run_hours(db, 1)

    rows = _measurements(db)
    assert [r[0] for r in rows] == [iso(_minute(i)) for i in range(60)]
    assert rows[0][1:3] == (0.0, 0.0)


def test_dec8_basis_is_polymarket_minus_hyperliquid_and_change_is_against_the_first_minute(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    set_price(db, pm, _minute(0), 101.0)
    set_price(db, pm, _minute(3), 101.5)
    set_price(db, hl, _minute(3), 99.0)

    run_hours(db, 1)

    rows = _measurements(db)
    assert rows[0][1:3] == pytest.approx((1.0, 0.0))
    assert rows[3][1:3] == pytest.approx((2.5, 1.5))
    assert rows[4][1:3] == pytest.approx((0.0, -1.0))


def test_ac1_a_missing_price_leaves_its_values_null_and_keeps_the_other_distance(
    db: Database,
) -> None:
    _open_world(db, hl_gaps={_minute(5)})

    run_hours(db, 1)

    row = _measurements(db)[5]
    assert row[1] is None and row[2] is None and row[4] is None
    assert row[3] is not None
    assert len(_measurements(db)) == 60


def test_dec8_the_baseline_is_the_first_minute_that_has_a_basis(db: Database) -> None:
    pm, hl = _open_world(db, pm_gaps={_minute(0)})
    set_price(db, pm, _minute(1), 103.0)

    run_hours(db, 1)

    rows = _measurements(db)
    assert rows[0][1:3] == (None, None)
    assert rows[1][1:3] == pytest.approx((3.0, 0.0))
    assert rows[2][1:3] == pytest.approx((0.0, -3.0))


def test_dec7_distances_follow_the_level_of_each_leg_at_the_minute_mark(db: Database) -> None:
    _open_world(db)
    pm_entry, _ = _entry(db, POLYMARKET)
    hl_entry, _ = _entry(db, HYPERLIQUID)

    run_hours(db, 1)

    row = _measurements(db)[0]
    pm_level = liquidation_price(False, pm_entry, 2.0, MARGIN)
    hl_level = liquidation_price(True, hl_entry, 2.0, MARGIN)
    assert row[3] == pytest.approx((pm_level - 100.0) / 100.0)
    assert row[4] == pytest.approx((100.0 - hl_level) / 100.0)


def test_dec7_a_maintenance_margin_change_moves_the_distance_from_its_effective_minute(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    set_margin(db, hl, _minute(30), 0.05)
    hl_entry, _ = _entry(db, HYPERLIQUID)

    run_hours(db, 1)

    rows = _measurements(db)
    before = (100.0 - liquidation_price(True, hl_entry, 2.0, MARGIN)) / 100.0
    after = (100.0 - liquidation_price(True, hl_entry, 2.0, 0.05)) / 100.0
    assert rows[29][4] == pytest.approx(before)
    assert rows[30][4] == pytest.approx(after)
    assert before != pytest.approx(after)


def test_dec7_without_maintenance_margin_there_is_no_distance_and_no_liquidation(
    db: Database,
) -> None:
    pm, hl = _open_world(db, margins=False)
    set_price(db, hl, _minute(4), 1.0)

    run_hours(db, 1)

    assert [r[3:5] for r in _measurements(db)][:6] == [(None, None)] * 6
    assert _liquidations(db) == []


def _crash(db: Database, hl: int, minute: int, mark: float) -> None:
    set_price(db, hl, _minute(minute), mark)
    book(db, hl, _minute(minute), HL_BIDS, HL_ASKS)


def test_ac2_a_long_leg_is_liquidated_in_the_crossing_minute_and_the_other_leg_is_closed(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    hl_entry, hl_quantity = _entry(db, HYPERLIQUID)
    level = liquidation_price(True, hl_entry, 2.0, MARGIN)
    _crash(db, hl, 10, 50.0)
    book(db, pm, _minute(10), PM_BIDS, PM_ASKS)

    run_hours(db, 1)

    assert _liquidations(db) == [
        (
            HYPERLIQUID,
            iso(_minute(10)),
            "sell",
            pytest.approx(level),
            pytest.approx(level),
            hl_quantity,
            0.0,
            0.0,
            500.0,
            iso(_minute(10)),
        )
    ]
    closes = _closes(db)
    assert [(c[0], c[1], c[2]) for c in closes] == [(POLYMARKET, iso(_minute(10)), "buy")]
    assert closes[0][3] > 0
    assert _position(db) == ("closed", iso(_minute(10)))
    rows = _measurements(db)
    assert rows[-1][0] == iso(_minute(10))
    assert rows[-1][4] < 0
    assert future_data_violations(db) == 0


def test_ac2_a_short_leg_is_liquidated_when_its_mark_rises_to_its_level(db: Database) -> None:
    pm, hl = _open_world(db)
    pm_entry, _ = _entry(db, POLYMARKET)
    level = liquidation_price(False, pm_entry, 2.0, MARGIN)
    set_price(db, pm, _minute(7), level + 1.0)
    book(db, pm, _minute(7), PM_BIDS, PM_ASKS)
    book(db, hl, _minute(7), HL_BIDS, HL_ASKS)

    run_hours(db, 1)

    liquidation = _liquidations(db)[0]
    assert liquidation[:3] == (POLYMARKET, iso(_minute(7)), "buy")
    assert liquidation[8] == 500.0
    assert [(c[0], c[2]) for c in _closes(db)] == [(HYPERLIQUID, "sell")]


def test_dec7_a_mark_exactly_at_the_level_liquidates_and_just_inside_it_does_not(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    hl_entry, _ = _entry(db, HYPERLIQUID)
    level = liquidation_price(True, hl_entry, 2.0, MARGIN)
    set_price(db, hl, _minute(5), level + 1e-6)
    _crash(db, hl, 6, level)
    book(db, pm, _minute(6), PM_BIDS, PM_ASKS)

    run_hours(db, 1)

    assert [x[1] for x in _liquidations(db)] == [iso(_minute(6))]


def test_dec4_an_uncovered_leg_stays_open_until_a_later_minute_can_close_it(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    set_price(db, hl, _minute(10), 50.0)
    book(db, pm, _minute(50), PM_BIDS, PM_ASKS)

    run_hours(db, 1)

    assert [x[0] for x in _liquidations(db)] == [HYPERLIQUID]
    assert _closes(db)[0][:2] == (POLYMARKET, iso(_minute(50)))
    assert _position(db) == ("closed", iso(_minute(50)))
    assert [r[0] for r in _measurements(db)][-1] == iso(_minute(50))


def test_dec4_while_uncovered_the_position_is_leg_liquidated_and_still_measured(
    db: Database,
) -> None:
    pm, hl = _open_world(db, hours=1)
    set_price(db, hl, _minute(10), 50.0)

    run_hours(db, 1)

    assert _position(db) == ("leg_liquidated", None)
    rows = _measurements(db)
    assert len(rows) == 60
    assert rows[11][4] is None and rows[11][3] is not None


def test_r3_funding_stops_for_a_leg_at_its_own_liquidation_while_the_other_keeps_accruing(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    set_price(db, hl, _minute(10), 50.0)
    book(db, pm, _minute(50), PM_BIDS, PM_ASKS)

    run_hours(db, 1)

    assert [p[0] for p in _payments(db)] == [POLYMARKET]
    assert future_data_violations(db) == 0


def test_r3_a_payment_is_rate_times_quantity_times_the_documented_price_per_platform(
    db: Database,
) -> None:
    pm, hl = _open_world(db)
    seed_prices(db, pm, H0, 4 * 60, 100.0, 90.0)
    seed_prices(db, hl, H0, 4 * 60, 100.0, 110.0)
    _, pm_quantity = _entry(db, POLYMARKET)
    _, hl_quantity = _entry(db, HYPERLIQUID)

    run_hours(db, 1)

    # PM is short and collects a positive rate at its mark; HL is long and pays at its index
    assert [p[2] for p in _payments(db)] == pytest.approx(
        [0.0004 * pm_quantity * 100.0, -0.0001 * hl_quantity * 110.0], abs=1e-6
    )


def test_r3_the_price_is_the_latest_at_or_before_the_payment_minute_within_sixty_minutes(
    db: Database,
) -> None:
    payment_minute = H0 + HOUR_MS
    gaps = set(range(H0, payment_minute + 30 * MINUTE_MS, MINUTE_MS))
    pm, hl = _open_world(db, pm_gaps=gaps, hl_gaps=gaps)
    set_price(db, pm, payment_minute - 60 * MINUTE_MS, 80.0)
    set_price(db, hl, payment_minute - 61 * MINUTE_MS, 80.0)
    set_price(db, pm, payment_minute + MINUTE_MS, 1.0)
    set_price(db, hl, payment_minute + MINUTE_MS, 1.0)
    _, pm_quantity = _entry(db, POLYMARKET)

    run_hours(db, 1)

    assert [(p[0], p[2]) for p in _payments(db)] == [
        (POLYMARKET, pytest.approx(0.0004 * pm_quantity * 80.0, abs=1e-6))
    ]


def test_r9_prices_seeded_after_the_cutoff_change_no_measurement_liquidation_or_payment(
    tmp_path: Path,
) -> None:
    def build(path: Path, future: bool) -> Database:
        db = Database(path)
        pm, hl = _open_world(db)
        if future:
            set_price(db, hl, _minute(60), 1.0)
            set_price(db, pm, _minute(61), 9999.0)
        run_hours(db, 1)
        return db

    clean, dirty = build(tmp_path / "a.db", False), build(tmp_path / "b.db", True)

    assert _measurements(dirty) == _measurements(clean)
    assert _liquidations(dirty) == _liquidations(clean) == []
    assert _payments(dirty) == _payments(clean)
    assert future_data_violations(dirty) == 0


def _lock_error() -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def test_ac10_a_deferred_measurement_blocks_the_pair_and_nothing_is_lost(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _open_world(db)
    original = runner._measure_position

    def flaky(*args: Any) -> None:
        raise _lock_error()

    monkeypatch.setattr(runner, "_measure_position", flaky)

    summary = evaluate(db, decision_at(1) + MINUTE_MS)
    monkeypatch.setattr(runner, "_measure_position", original)

    assert summary.deferred == 1 and summary.decided == 0
    assert db.conn.execute("SELECT count(*) FROM decision").fetchone()[0] == 1
    evaluate(db, decision_at(1) + 2 * MINUTE_MS)
    assert len(_measurements(db)) == 60
    assert db.conn.execute("SELECT count(*) FROM decision").fetchone()[0] == 2


def test_r1_measuring_again_adds_no_duplicate_rows(db: Database) -> None:
    _open_world(db)
    run_hours(db, 1)

    evaluate(db, decision_at(1) + 2 * MINUTE_MS)

    assert len(_measurements(db)) == 60


def test_r1_a_position_closed_at_a_decision_is_measured_only_before_it(db: Database) -> None:
    pm, hl = _world(db)
    for index, spread in enumerate([0.0003, -0.0003]):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, spread)
        standard_books(db, pm, hl, decision_at(index))
    run_hours(db, 0, 1)

    assert _position(db)[1] == iso(decision_at(1))
    assert _measurements(db)[-1][0] == iso(decision_at(1) - MINUTE_MS)


def test_r3_with_several_readings_in_the_window_the_latest_one_prices_the_payment(
    db: Database,
) -> None:
    payment_minute = H0 + HOUR_MS
    gaps = set(range(H0, payment_minute + 30 * MINUTE_MS, MINUTE_MS))
    pm, hl = _open_world(db, pm_gaps=gaps, hl_gaps=gaps)
    set_price(db, pm, payment_minute - 40 * MINUTE_MS, 70.0)
    set_price(db, pm, payment_minute - 5 * MINUTE_MS, 90.0)
    _, pm_quantity = _entry(db, POLYMARKET)

    run_hours(db, 1)

    assert [p[2] for p in _payments(db) if p[0] == POLYMARKET] == [
        pytest.approx(0.0004 * pm_quantity * 90.0, abs=1e-6)
    ]


def test_f3_the_basis_change_stays_against_the_first_basis_across_hour_chunks(
    db: Database,
) -> None:
    pm, hl = _open_world(db, hours=3)
    set_price(db, pm, _minute(59), 101.0)
    set_price(db, pm, _minute(90), 103.0)

    run_hours(db, 1, 2)

    rows = _measurements(db)
    assert rows[59][1:3] == pytest.approx((1.0, 1.0))
    assert rows[90][1:3] == pytest.approx((3.0, 3.0))


def _uncovered_world(db: Database) -> tuple[int, int]:
    pm, hl = _world(db)
    for index in range(4):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, 0.0003)
    standard_books(db, pm, hl, decision_at(0))
    run_hours(db, 0)
    set_price(db, hl, _minute(10), 50.0)
    book(db, pm, _minute(130), PM_BIDS, PM_ASKS)
    return pm, hl


def test_f3_an_uncovered_leg_is_not_liquidated_again_and_has_no_distance_in_later_chunks(
    db: Database,
) -> None:
    _uncovered_world(db)

    run_hours(db, 1, 2, 3)

    assert [x[0] for x in _liquidations(db)] == [HYPERLIQUID]
    rows = _measurements(db)
    assert all(r[4] is None for r in rows[11:])
    assert all(r[3] is not None for r in rows[11:])
    assert len(rows) == 131
    assert _position(db) == ("closed", iso(_minute(130)))


def test_f4_while_a_leg_is_uncovered_the_pair_opens_nothing_and_its_decision_is_hold(
    db: Database,
) -> None:
    _uncovered_world(db)

    run_hours(db, 1, 2)

    assert [row[1] for row in decisions(db)] == ["open", "hold", "hold"]
    assert db.conn.execute("SELECT count(*) FROM paper_position").fetchone() == (1,)


def test_f6_a_run_that_predates_the_measurement_step_is_measured_from_its_last_decision(
    db: Database,
) -> None:
    _open_world(db)
    with db.conn:
        db.conn.execute("UPDATE run SET measured_from = NULL")

    run_hours(db, 1)

    rows = _measurements(db)
    assert rows[0][0] == iso(_minute(1))
    assert len(rows) == 59
