import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from polyquack.evaluation import runner
from polyquack.evaluation.preregistration import preregister
from polyquack.evaluation.runner import evaluate
from polyquack.ingestion.models import FeeRate, Levels
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, from_iso, iso

from .conftest import T0, seed_pairs
from .evalkit import (
    D0,
    H0,
    HL_ASKS,
    HL_BIDS,
    HL_TAKER,
    PM_ASKS,
    PM_BIDS,
    PM_TAKER,
    book,
    decision_at,
    decisions,
    fund,
    fund_spread,
    future_data_violations,
    iso_decision,
    prereg_text,
    run_hours,
    seed_prices,
    seed_world,
    standard_books,
)

REGISTERED_AT = H0 - 30 * MINUTE_MS


def _world(db: Database, with_fees: bool = True) -> tuple[int, int]:
    pm, hl = seed_world(db, with_fees=with_fees)
    preregister(db, prereg_text(), REGISTERED_AT)
    for instrument in (pm, hl):
        seed_prices(db, instrument, H0 - HOUR_MS, 10 * 60, 100.0)
    return pm, hl


def _trades(db: Database) -> list[tuple[str, ...]]:
    return db.conn.execute(
        "SELECT p.name, t.kind, t.hour, t.side, t.avg_price, t.best_price, t.quantity, t.fee,"
        " t.slippage, t.snapshot_minute FROM paper_trade t JOIN platform p ON p.id = t.platform_id"
        " ORDER BY t.id"
    ).fetchall()


def _positions(db: Database) -> list[tuple[str, float, float, str, str | None, str]]:
    return db.conn.execute(
        "SELECT polymarket_side, notional_per_leg, leverage, opened_at, closed_at, status"
        " FROM paper_position ORDER BY id"
    ).fetchall()


def _payments(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT p.name, f.source_time, f.rate, f.amount FROM paper_funding_payment f"
        " JOIN platform p ON p.id = f.platform_id ORDER BY f.source_time, p.id"
    ).fetchall()


def _filled_quantity(levels: Levels, notional: float) -> float:
    quantity = 0.0
    for price, size in levels:
        take = min(size, notional / price)
        quantity += take
        notional -= take * price
    assert notional < 1e-9
    return quantity


def _assert_trade(
    trade: tuple[str, ...],
    head: tuple[str, str, str, str],
    avg: float,
    best: float,
    quantity: float,
    fee: float,
    slippage: float,
    snapshot_minute: str,
) -> None:
    assert trade[:4] == head
    assert trade[4:9] == pytest.approx((avg, best, quantity, fee, slippage), abs=1e-6)
    assert trade[9] == snapshot_minute


def test_r4_a_first_evaluate_before_any_decision_instant_starts_no_run(db: Database) -> None:
    _world(db)

    summary = evaluate(db, H0 + 10 * MINUTE_MS)

    assert (summary.runs_started, summary.decided) == (0, 0)
    assert db.conn.execute("SELECT count(*) FROM run").fetchone()[0] == 0
    assert db.conn.execute("SELECT first_run_at FROM variant").fetchone()[0] is None


def test_r4_the_first_run_starts_at_the_first_due_decision_instant_and_freezes_the_variant(
    db: Database,
) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)

    summary = evaluate(db, D0 + 5 * MINUTE_MS)

    assert (summary.runs_started, summary.decided) == (1, 1)
    run = db.conn.execute("SELECT mode, starts_at, status, ends_at FROM run").fetchone()
    assert run == ("live", iso(D0), "in_progress", None)
    first_run_at = db.conn.execute("SELECT first_run_at FROM variant").fetchone()[0]
    assert first_run_at == iso(D0 + 5 * MINUTE_MS)
    evaluate(db, D0 + 6 * MINUTE_MS)
    assert db.conn.execute("SELECT count(*) FROM run").fetchone()[0] == 1


def test_ac4_two_missed_hours_are_decided_in_order_each_with_its_own_cutoff(
    db: Database,
) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)
    run_hours(db, 0)
    fund_spread(db, pm, hl, H0 + HOUR_MS, 0.00001)
    fund_spread(db, pm, hl, H0 + 2 * HOUR_MS, 0.00002)
    fund_spread(db, pm, hl, H0 + 3 * HOUR_MS, 0.00003)

    evaluate(db, decision_at(2) + 5 * MINUTE_MS)

    rows = decisions(db)
    assert [r[0] for r in rows] == [iso_decision(0), iso_decision(1), iso_decision(2)]
    assert [r[2] for r in rows[1:]] == pytest.approx([0.00001, 0.00002])
    assert future_data_violations(db) == 0


def test_r4_a_decision_instant_exactly_at_the_clock_is_due(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)

    assert evaluate(db, D0).decided == 1


def test_r4_every_in_progress_run_is_decided_not_only_new_ones(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)
    run_hours(db, 0)
    preregister(db, prereg_text(), decision_at(0) + 2 * MINUTE_MS)
    fund_spread(db, pm, hl, H0 + HOUR_MS, 0.0)

    summary = evaluate(db, decision_at(1) + MINUTE_MS)

    assert summary.runs_started == 1
    per_run = db.conn.execute(
        "SELECT run_id, count(*) FROM decision GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    assert per_run == [(1, 2), (2, 1)]


def test_ac5_one_decision_per_pair_per_hour_and_a_missing_rate_gives_no_action(
    db: Database,
) -> None:
    seed_pairs(db, ["AAA", "BBB", "CCC"])
    preregister(db, prereg_text(), REGISTERED_AT)
    ids = {(t.asset, t.platform): t.instrument_id for t in db.targets()}
    fund_spread(db, ids["AAA", POLYMARKET], ids["AAA", HYPERLIQUID], H0, 0.0)
    fund(db, ids["BBB", POLYMARKET], H0, 0.0001)
    db.set_status(ids["CCC", POLYMARKET], "delisted", T0)

    evaluate(db, D0 + MINUTE_MS)
    evaluate(db, D0 + 2 * MINUTE_MS)

    rows = db.conn.execute(
        "SELECT a.symbol, d.action, d.funding_spread, d.cause FROM decision d"
        " JOIN pair ON pair.id = d.pair_id JOIN asset a ON a.id = pair.asset_id ORDER BY a.symbol"
    ).fetchall()
    assert rows == [("AAA", "hold", 0.0, None), ("BBB", "no_action", None, "missing_rate")]


def test_r5_a_missing_rate_of_either_platform_is_no_action_without_a_spread(db: Database) -> None:
    pm, hl = _world(db)
    standard_books(db, pm, hl, D0)
    fund(db, hl, H0, 0.0001)

    run_hours(db, 0)

    assert decisions(db) == [(iso_decision(0), "no_action", None, "missing_rate")]
    assert _trades(db) == []


def test_r5_missing_hours_in_the_window_are_skipped_not_counted_as_zero(db: Database) -> None:
    pm, hl = _world(db)
    standard_books(db, pm, hl, D0)
    fund_spread(db, pm, hl, H0 - HOUR_MS, 0.0003)
    fund_spread(db, pm, hl, H0, 0.00015)

    run_hours(db, 0)

    # skipping the third, missing hour gives 0.000225 (> entry 0.0002); counting it as zero 0.00015
    assert decisions(db)[0][1] == "open"


def test_r5_a_hold_while_flat_keeps_the_spread_and_trades_nothing(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0001)

    run_hours(db, 0)

    assert decisions(db) == [(iso_decision(0), "hold", pytest.approx(0.0001), None)]
    assert _trades(db) == [] and _positions(db) == []


def test_ac6_open_walks_the_book_and_records_price_fee_slippage_and_snapshot(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)

    run_hours(db, 0)

    assert decisions(db) == [(iso_decision(0), "open", pytest.approx(0.0003), None)]
    assert _positions(db) == [("short", 1000.0, 2.0, iso(D0), None, "open")]
    pm_trade, hl_trade = _trades(db)
    pm_quantity = _filled_quantity(PM_BIDS, 1000.0)
    hl_quantity = _filled_quantity(HL_ASKS, 1000.0)
    minute = iso(D0 - MINUTE_MS)
    _assert_trade(
        pm_trade,
        (POLYMARKET, "open", iso(D0), "sell"),
        1000.0 / pm_quantity,
        100.0,
        pm_quantity,
        1000.0 * PM_TAKER,
        abs(1000.0 / pm_quantity - 100.0) * pm_quantity,
        minute,
    )
    _assert_trade(
        hl_trade,
        (HYPERLIQUID, "open", iso(D0), "buy"),
        1000.0 / hl_quantity,
        100.1,
        hl_quantity,
        1000.0 * HL_TAKER,
        abs(1000.0 / hl_quantity - 100.1) * hl_quantity,
        minute,
    )


def test_dec9_a_negative_mean_opens_long_on_polymarket_and_short_on_hyperliquid(
    db: Database,
) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, -0.0003)
    standard_books(db, pm, hl, D0)

    run_hours(db, 0)

    assert [p[0] for p in _positions(db)] == ["long"]
    assert [(t[0], t[3]) for t in _trades(db)] == [(POLYMARKET, "buy"), (HYPERLIQUID, "sell")]


def test_dec11_stored_money_has_at_most_six_decimals(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)

    run_hours(db, 0)

    rows = db.conn.execute("SELECT fee, slippage FROM paper_trade").fetchall()
    assert all(value == round(value, 6) for row in rows for value in row)
    assert rows[0][1] > 0


def _lifecycle(db: Database) -> None:
    """Open at hour 0, hold at 1, close at 2 (mean 0), flat at 3."""
    pm, hl = _world(db)
    for index, spread in enumerate([0.0003, 0.00012, -0.00042, 0.0]):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, spread)
        standard_books(db, pm, hl, decision_at(index))
    run_hours(db, 0, 1, 2, 3)


def test_r5_r7_open_then_hold_in_position_then_close_then_hold_flat(db: Database) -> None:
    _lifecycle(db)

    assert [row[1] for row in decisions(db)] == ["open", "hold", "close", "hold"]
    assert _positions(db) == [("short", 1000.0, 2.0, iso(D0), iso(decision_at(2)), "closed")]
    assert [(t[1], t[2]) for t in _trades(db)] == [
        ("open", iso(D0)),
        ("open", iso(D0)),
        ("close", iso(decision_at(2))),
        ("close", iso(decision_at(2))),
    ]


def test_r6_close_walks_the_opposite_side_for_the_open_quantity_with_the_traded_notional_fee(
    db: Database,
) -> None:
    _lifecycle(db)

    trades = _trades(db)
    pm_quantity, hl_quantity = float(trades[0][6]), float(trades[1][6])
    minute = iso(decision_at(2) - MINUTE_MS)
    _assert_trade(
        trades[2],
        (POLYMARKET, "close", iso(decision_at(2)), "buy"),
        100.1,
        100.1,
        pm_quantity,
        100.1 * pm_quantity * PM_TAKER,
        0.0,
        minute,
    )
    _assert_trade(
        trades[3],
        (HYPERLIQUID, "close", iso(decision_at(2)), "sell"),
        99.9,
        99.9,
        hl_quantity,
        99.9 * hl_quantity * HL_TAKER,
        0.0,
        minute,
    )


def test_ac8_funding_accrues_after_the_opening_and_through_the_closing_decision(
    db: Database,
) -> None:
    _lifecycle(db)

    # short PM collects a positive rate and pays a negative one; long HL pays a positive rate;
    # the amount is rate * quantity * price (the seeded price is 100 on both platforms)
    pm_quantity, hl_quantity = float(_trades(db)[0][6]), float(_trades(db)[1][6])
    assert _payments(db) == [
        (
            POLYMARKET,
            iso(H0 + HOUR_MS + 51),
            pytest.approx(0.00022),
            pytest.approx(0.00022 * pm_quantity * 100, abs=1e-6),
        ),
        (
            HYPERLIQUID,
            iso(H0 + HOUR_MS + 51),
            0.0001,
            pytest.approx(-0.0001 * hl_quantity * 100, abs=1e-6),
        ),
        (
            POLYMARKET,
            iso(H0 + 2 * HOUR_MS + 51),
            pytest.approx(-0.00032),
            pytest.approx(-0.00032 * pm_quantity * 100, abs=1e-6),
        ),
        (
            HYPERLIQUID,
            iso(H0 + 2 * HOUR_MS + 51),
            0.0001,
            pytest.approx(-0.0001 * hl_quantity * 100, abs=1e-6),
        ),
    ]
    assert future_data_violations(db) == 0


def test_ac8_catch_up_credits_each_payment_once(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    run_hours(db, 0)
    for index in (1, 2):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, 0.0003)
        standard_books(db, pm, hl, decision_at(index))

    evaluate(db, decision_at(2) + MINUTE_MS)
    evaluate(db, decision_at(2) + 2 * MINUTE_MS)

    assert len(_payments(db)) == 4


def test_ac8_a_payment_ingested_late_is_credited_by_a_later_run(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    run_hours(db, 0)
    fund_spread(db, pm, hl, H0 + HOUR_MS, 0.0003)
    standard_books(db, pm, hl, decision_at(1))
    run_hours(db, 1)
    fund(db, hl, H0 + 2 * HOUR_MS, 0.0001)
    run_hours(db, 2)
    assert len(_payments(db)) == 3

    fund(db, pm, H0 + 2 * HOUR_MS, 0.0004)
    run_hours(db, 3)

    assert len(_payments(db)) == 4


def test_ac7_reverse_closes_and_opens_the_opposite_position_in_one_decision(db: Database) -> None:
    pm, hl = _world(db)
    for index, spread in enumerate([0.0003, -0.0012]):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, spread)
        standard_books(db, pm, hl, decision_at(index))

    run_hours(db, 0, 1)

    assert [row[1] for row in decisions(db)] == ["open", "reverse"]
    assert _positions(db) == [
        ("short", 1000.0, 2.0, iso(D0), iso(decision_at(1)), "closed"),
        ("long", 1000.0, 2.0, iso(decision_at(1)), None, "open"),
    ]
    at_reverse = [t[:4] for t in _trades(db) if t[2] == iso(decision_at(1))]
    assert at_reverse == [
        (POLYMARKET, "close", iso(decision_at(1)), "buy"),
        (HYPERLIQUID, "close", iso(decision_at(1)), "sell"),
        (POLYMARKET, "open", iso(decision_at(1)), "buy"),
        (HYPERLIQUID, "open", iso(decision_at(1)), "sell"),
    ]
    assert len(_trades(db)) == 6


@pytest.mark.parametrize(
    ("setup", "cause"),
    [
        ("stale_snapshot", "no_usable_snapshot"),
        ("future_snapshot", "no_usable_snapshot"),
        ("one_leg_without_snapshot", "no_usable_snapshot"),
        ("thin_polymarket", "thin_book"),
        ("thin_hyperliquid", "thin_book"),
        ("no_fee", "missing_fee"),
        ("fee_after_cutoff", "missing_fee"),
    ],
)
def test_r6_dec6_a_leg_that_cannot_trade_makes_the_decision_no_action_with_a_cause(
    db: Database, setup: str, cause: str
) -> None:
    pm, hl = _world(db, with_fees=setup not in ("no_fee", "fee_after_cutoff"))
    fund_spread(db, pm, hl, H0, 0.0003)
    minute = D0 - MINUTE_MS
    if setup == "stale_snapshot":
        book(db, pm, minute, PM_BIDS, PM_ASKS, source_time_ms=D0 - 121_000)
        book(db, hl, minute, HL_BIDS, HL_ASKS)
    elif setup == "future_snapshot":
        book(db, pm, minute, PM_BIDS, PM_ASKS, source_time_ms=D0 + 1_000)
        book(db, hl, minute, HL_BIDS, HL_ASKS)
    elif setup == "one_leg_without_snapshot":
        book(db, pm, minute, PM_BIDS, PM_ASKS)
    elif setup == "thin_polymarket":
        book(db, pm, minute, [(100.0, 5.0)], PM_ASKS)
        book(db, hl, minute, HL_BIDS, HL_ASKS)
    elif setup == "thin_hyperliquid":
        book(db, pm, minute, PM_BIDS, PM_ASKS)
        book(db, hl, minute, HL_BIDS, [(100.1, 3.0)])
    else:
        standard_books(db, pm, hl, D0)
    if setup == "fee_after_cutoff":
        db.sync_fees(POLYMARKET, [FeeRate("crypto", "0", PM_TAKER, 0.0, D0 + 1)], D0 + 1)
        db.sync_fees(HYPERLIQUID, [FeeRate("", "0", HL_TAKER, 0.0, D0 + 1)], D0 + 1)

    run_hours(db, 0)

    assert decisions(db) == [(iso_decision(0), "no_action", pytest.approx(0.0003), cause)]
    assert _trades(db) == [] and _positions(db) == []


def test_r6_a_close_that_cannot_fill_keeps_the_position_open(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    run_hours(db, 0)
    fund_spread(db, pm, hl, H0 + HOUR_MS, -0.0003)
    book(db, pm, decision_at(1) - MINUTE_MS, PM_BIDS, PM_ASKS)
    book(db, hl, decision_at(1) - MINUTE_MS, [(99.9, 1.0)], HL_ASKS)

    run_hours(db, 1)

    assert decisions(db)[1][1:] == ("no_action", pytest.approx(-0.0003), "thin_book")
    assert _positions(db)[0][4:] == (None, "open")
    assert len(_trades(db)) == 2


def test_dec4_the_latest_usable_snapshot_is_used_when_a_newer_one_is_after_the_cutoff(
    db: Database,
) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    book(db, pm, D0, [(1.0, 1e9)], [(1.1, 1e9)], source_time_ms=D0 + 1_000)

    run_hours(db, 0)

    assert decisions(db)[0][1] == "open"
    assert {t[9] for t in _trades(db)} == {iso(D0 - MINUTE_MS)}


def _future_world(path: Path, with_future: bool) -> Database:
    db = Database(path)
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    if with_future:
        extreme: tuple[Levels, Levels] = ([(1.0, 1e9)], [(1.1, 1e9)])
        fund(db, pm, H0, 9.0, lag_ms=22 * MINUTE_MS)
        fund(db, hl, H0, -9.0, lag_ms=22 * MINUTE_MS)
        fund_spread(db, pm, hl, H0 + HOUR_MS, 5.0)
        book(db, pm, D0, *extreme, source_time_ms=D0 + 5_000)
        book(db, hl, D0, *extreme, source_time_ms=D0 + 5_000)
        book(db, pm, D0 + MINUTE_MS, *extreme)
    return db


def test_ac9_readings_after_the_cutoff_with_extreme_values_change_no_decision(
    tmp_path: Path,
) -> None:
    clean = _future_world(tmp_path / "clean.db", with_future=False)
    dirty = _future_world(tmp_path / "dirty.db", with_future=True)

    evaluate(clean, D0 + MINUTE_MS)
    evaluate(dirty, D0 + MINUTE_MS)

    assert decisions(dirty) == decisions(clean)
    assert _trades(dirty) == _trades(clean)
    assert _positions(dirty) == _positions(clean)
    assert _payments(dirty) == _payments(clean)
    assert future_data_violations(dirty) == 0
    snapshot_source = dirty.conn.execute("SELECT data_until FROM decision").fetchone()[0]
    assert snapshot_source == iso(D0 - MINUTE_MS + 5_000)


def test_ac9_data_until_without_any_reading_is_the_decision_instant(db: Database) -> None:
    _world(db)

    run_hours(db, 0)

    assert db.conn.execute("SELECT data_until, hour FROM decision").fetchone() == (
        iso_decision(0),
        iso_decision(0),
    )


def _hold_write_lock(path: Path, seconds: float) -> threading.Thread:
    ready = threading.Event()

    def hold() -> None:
        conn = sqlite3.connect(path, timeout=0)
        conn.execute("BEGIN IMMEDIATE")
        ready.set()
        time.sleep(seconds)
        conn.rollback()
        conn.close()

    thread = threading.Thread(target=hold)
    thread.start()
    assert ready.wait(5)
    return thread


def test_ac10_a_second_writer_holding_the_lock_under_the_busy_timeout_loses_no_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "busy.db"
    db = Database(path, busy_timeout_ms=5000)
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    holder = _hold_write_lock(path, 0.4)

    started = time.monotonic()
    summary = evaluate(db, D0 + MINUTE_MS)
    holder.join()

    assert time.monotonic() - started >= 0.3
    assert (summary.decided, summary.deferred) == (1, 0)
    assert [row[1] for row in decisions(db)] == ["open"]


def test_ac10_contention_beyond_the_timeout_is_logged_and_the_hour_is_decided_next_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "busy.db"
    db = Database(path, busy_timeout_ms=50)
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    holder = _hold_write_lock(path, 1.0)

    with caplog.at_level(logging.ERROR):
        summary = evaluate(db, D0 + MINUTE_MS)
    holder.join()

    assert summary.deferred >= 1 and summary.decided == 0
    assert decisions(db) == []
    assert "locked" in caplog.text
    assert evaluate(db, D0 + 2 * MINUTE_MS).decided == 1
    assert [row[1] for row in decisions(db)] == ["open"]


def test_ac10_a_deferred_hour_blocks_later_hours_of_the_same_pair_until_it_is_decided(
    tmp_path: Path,
) -> None:
    path = tmp_path / "busy.db"
    db = Database(path, busy_timeout_ms=50)
    pm, hl = _world(db)
    for index in (0, 1, 2):
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, 0.0003)
        standard_books(db, pm, hl, decision_at(index))
    run_hours(db, 0)
    holder = _hold_write_lock(path, 1.0)

    summary = evaluate(db, decision_at(2) + MINUTE_MS)
    holder.join()
    evaluate(db, decision_at(2) + 2 * MINUTE_MS)

    assert summary.decided == 0
    assert [row[0] for row in decisions(db)] == [iso_decision(i) for i in (0, 1, 2)]


def test_r10_the_evaluator_writes_no_ingestion_table(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    tables = ("funding_reading", "book_snapshot", "price_reading", "gap", "fee_schedule")
    before = {t: db.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}

    run_hours(db, 0, 1, 2)

    after = {t: db.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    assert after == before


def test_dec5_the_decision_instant_is_the_hour_plus_the_decision_minute(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)

    run_hours(db, 0)

    assert from_iso(decisions(db)[0][0]) - H0 == 21 * MINUTE_MS


def test_ac8_a_reading_stamped_exactly_at_the_opening_is_not_credited(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    fund(db, pm, H0, 0.0004, lag_ms=21 * MINUTE_MS)
    standard_books(db, pm, hl, D0)
    run_hours(db, 0)
    fund_spread(db, pm, hl, H0 + HOUR_MS, 0.0003)
    standard_books(db, pm, hl, decision_at(1))

    run_hours(db, 1)

    assert [p[1] for p in _payments(db)] == [iso(H0 + HOUR_MS + 51)] * 2


def _lock_error() -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def _two_pairs(db: Database) -> dict[tuple[str, str], int]:
    seed_pairs(db, ["AAA", "BBB"])
    db.sync_fees(POLYMARKET, [FeeRate("crypto", "0", PM_TAKER, 0.000125, D0 - 48 * HOUR_MS)], 0)
    db.sync_fees(HYPERLIQUID, [FeeRate("", "0", HL_TAKER, 0.00015, D0 - 48 * HOUR_MS)], 0)
    preregister(db, prereg_text(), REGISTERED_AT)
    return {(t.asset, t.platform): t.instrument_id for t in db.targets()}


def _seed_hour(db: Database, ids: dict[tuple[str, str], int], index: int, spread: float) -> None:
    for asset in ("AAA", "BBB"):
        pm, hl = ids[asset, POLYMARKET], ids[asset, HYPERLIQUID]
        fund_spread(db, pm, hl, H0 + index * HOUR_MS, spread if asset == "AAA" else 0.0)
        standard_books(db, pm, hl, decision_at(index))


def _defer_pair_at(
    monkeypatch: pytest.MonkeyPatch, db: Database, asset: str, hour_index: int
) -> None:
    pair_id = db.conn.execute(
        "SELECT pair.id FROM pair JOIN asset a ON a.id = pair.asset_id WHERE a.symbol = ?",
        (asset,),
    ).fetchone()[0]
    original = runner._decide

    def flaky(db_: Database, run: runner.LiveRun, pair: runner.Pair, cutoff_ms: int) -> None:
        if pair.id == pair_id and cutoff_ms == decision_at(hour_index):
            raise _lock_error()
        original(db_, run, pair, cutoff_ms)

    monkeypatch.setattr(runner, "_decide", flaky)


def test_ac10_a_deferred_pair_is_neither_decided_nor_accrued_past_its_last_decided_hour(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _two_pairs(db)
    _seed_hour(db, ids, 0, 0.0003)
    evaluate(db, decision_at(0) + MINUTE_MS)
    _seed_hour(db, ids, 1, -0.0003)
    _seed_hour(db, ids, 2, 0.0)
    _defer_pair_at(monkeypatch, db, "AAA", 1)

    summary = evaluate(db, decision_at(2) + MINUTE_MS)
    monkeypatch.undo()
    evaluate(db, decision_at(2) + 2 * MINUTE_MS)

    assert summary.deferred == 1
    assert future_data_violations(db) == 0
    assert _positions(db)[0][4] == iso(decision_at(1))


def test_ac10_hours_after_a_deferral_wait_for_it_while_other_pairs_go_on(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _two_pairs(db)
    for index in (0, 1, 2):
        _seed_hour(db, ids, index, 0.0)
    evaluate(db, decision_at(0) + MINUTE_MS)
    _defer_pair_at(monkeypatch, db, "AAA", 1)

    summary = evaluate(db, decision_at(2) + MINUTE_MS)

    assert (summary.decided, summary.deferred) == (2, 1)
    by_asset = db.conn.execute(
        "SELECT a.symbol, count(*) FROM decision d JOIN pair ON pair.id = d.pair_id"
        " JOIN asset a ON a.id = pair.asset_id GROUP BY a.symbol ORDER BY a.symbol"
    ).fetchall()
    assert by_asset == [("AAA", 1), ("BBB", 3)]


def test_dec11_funding_payments_are_rounded_to_six_decimals(db: Database) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0003)
    standard_books(db, pm, hl, D0)
    run_hours(db, 0)
    fund(db, pm, H0 + HOUR_MS, 0.000123456789)
    fund(db, hl, H0 + HOUR_MS, 0.0001)
    standard_books(db, pm, hl, decision_at(1))

    run_hours(db, 1)

    pm_quantity, hl_quantity = float(_trades(db)[0][6]), float(_trades(db)[1][6])
    amounts = [p[3] for p in _payments(db)]
    assert amounts == [
        round(0.000123456789 * pm_quantity * 100, 6),
        round(-0.0001 * hl_quantity * 100, 6),
    ]


def test_dec1_the_window_is_the_last_n_hours_and_excludes_the_hour_n_back(db: Database) -> None:
    pm, hl = _world(db)
    standard_books(db, pm, hl, D0)
    fund_spread(db, pm, hl, H0 - 3 * HOUR_MS, 0.0012)
    for back in (2, 1, 0):
        fund_spread(db, pm, hl, H0 - back * HOUR_MS, 0.0)

    run_hours(db, 0)

    assert decisions(db)[0][1] == "hold"


def test_dec1_a_reading_stamped_just_before_the_first_window_hour_still_counts(
    db: Database,
) -> None:
    pm, hl = _world(db)
    standard_books(db, pm, hl, D0)
    fund(db, pm, H0 - 2 * HOUR_MS, 0.0010, lag_ms=-10_000)
    fund(db, hl, H0 - 2 * HOUR_MS, 0.0001, lag_ms=-10_000)
    for back in (1, 0):
        fund_spread(db, pm, hl, H0 - back * HOUR_MS, 0.0)

    run_hours(db, 0)

    assert decisions(db)[0][1] == "open"


def test_f4_a_pair_delisted_after_an_hour_is_still_decided_for_that_hour_on_catch_up(
    db: Database,
) -> None:
    pm, hl = _world(db)
    fund_spread(db, pm, hl, H0, 0.0)
    fund_spread(db, pm, hl, H0 + HOUR_MS, 0.0)
    db.set_status(pm, "delisted", D0 + 30 * MINUTE_MS)

    evaluate(db, decision_at(1) + MINUTE_MS)

    assert [row[0] for row in decisions(db)] == [iso_decision(0)]


def test_f4_close_only_still_decides_and_a_cutoff_before_pairing_is_not_decided(
    db: Database,
) -> None:
    pm, hl = _world(db)
    db.set_status(hl, "close_only", T0 - HOUR_MS)
    preregister(db, prereg_text(), T0 - 3 * HOUR_MS)
    first = D0
    while first - HOUR_MS > T0 - 3 * HOUR_MS:
        first -= HOUR_MS

    evaluate(db, D0 + MINUTE_MS)

    cutoffs = [c for c in range(first, D0 + 1, HOUR_MS) if c >= T0]
    assert [row[0] for row in decisions(db)] == [iso(c) for c in cutoffs]
    assert len(cutoffs) < len(range(first, D0 + 1, HOUR_MS))
