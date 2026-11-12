import json
import sqlite3
import time
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from polyquack import cli
from polyquack.evaluation import runner
from polyquack.evaluation.preregistration import preregister
from polyquack.evaluation.rule import Choice
from polyquack.evaluation.runner import ReevaluationError, evaluate, reevaluate
from polyquack.ingestion.models import FeeRate
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, iso

from .conftest import seed_pairs
from .evalkit import (
    D0,
    H0,
    HL_ASKS,
    HL_BIDS,
    HL_TAKER,
    PM_ASKS,
    PM_BIDS,
    PM_TAKER,
    decision_at,
    export_run,
    future_data_violations,
    prereg_text,
    seed_books,
    seed_prices,
    set_margin,
    set_price,
)

HORIZON_HOURS = 672
END = D0 + HORIZON_HOURS * HOUR_MS
NOW = END + 5 * MINUTE_MS
LAST = decision_at(HORIZON_HOURS - 1)
REGISTERED_AT = H0 - 30 * MINUTE_MS
BASE_RATE = 0.0001


def spiky(low: int, high: int) -> Callable[[int], float]:
    return lambda hour: 0.0003 if low <= hour < high else 0.0


@dataclass
class PairSpec:
    asset: str
    spread: Callable[[int], float] = lambda hour: 0.0
    paired_hour: int | None = None
    missing_hours: Collection[int] = ()
    missing_hl_hours: Collection[int] = ()
    missing_minutes: Collection[int] = ()
    missing_hl_minutes: Collection[int] = ()
    missing_pm_minutes: Collection[int] = ()
    no_data: bool = False
    price_gaps: Collection[int] = ()
    last_book_hour: int = HORIZON_HOURS


def build_world(db: Database, specs: list[PairSpec]) -> dict[str, tuple[int, int]]:
    seed_pairs(db, [spec.asset for spec in specs])
    fee_from = H0 - 24 * HOUR_MS
    db.sync_fees(POLYMARKET, [FeeRate("crypto", "0", PM_TAKER, 0.000125, fee_from)], fee_from)
    db.sync_fees(HYPERLIQUID, [FeeRate("", "0", HL_TAKER, 0.00015, fee_from)], fee_from)
    preregister(db, prereg_text(), REGISTERED_AT)
    ids = {(t.asset, t.platform): t.instrument_id for t in db.targets()}
    world: dict[str, tuple[int, int]] = {}
    for spec in specs:
        pm, hl = ids[spec.asset, POLYMARKET], ids[spec.asset, HYPERLIQUID]
        world[spec.asset] = (pm, hl)
        first_hour = -3 if spec.paired_hour is None else spec.paired_hour - 3
        if spec.paired_hour is not None:
            with db.conn:
                db.conn.execute(
                    "UPDATE pair SET paired_at = ? WHERE polymarket_instrument_id = ?",
                    (iso(H0 + spec.paired_hour * HOUR_MS), pm),
                )
        if spec.no_data:
            continue
        hours = range(first_hour, HORIZON_HOURS + 1)
        with db.conn:
            db.conn.executemany(
                "INSERT INTO funding_reading VALUES (?, ?, ?, ?, 'live')",
                [
                    (
                        pm,
                        iso(H0 + h * HOUR_MS + 51),
                        spec.spread(h) + BASE_RATE,
                        iso(H0 + h * HOUR_MS),
                    )
                    for h in hours
                    if h not in spec.missing_hours
                ]
                + [
                    (hl, iso(H0 + h * HOUR_MS + 51), BASE_RATE, iso(H0 + h * HOUR_MS))
                    for h in hours
                    if h not in spec.missing_hl_hours
                ],
            )
        first_minute = (
            D0 if spec.paired_hour is None else H0 + spec.paired_hour * HOUR_MS
        ) - MINUTE_MS
        last_book = D0 + spec.last_book_hour * HOUR_MS
        minutes = [
            m for m in range(first_minute, last_book, MINUTE_MS) if m not in spec.missing_minutes
        ]
        pm_minutes = [m for m in minutes if m not in spec.missing_pm_minutes]
        seed_books(db, pm, pm_minutes, PM_BIDS, PM_ASKS)
        hl_minutes = [m for m in minutes if m not in spec.missing_hl_minutes]
        seed_books(db, hl, hl_minutes, HL_BIDS, HL_ASKS)
        for instrument in (pm, hl):
            set_margin(db, instrument, H0 - HOUR_MS, 0.025)
            seed_prices(
                db,
                instrument,
                first_minute,
                (END - first_minute) // MINUTE_MS + 1,
                100.0,
                skip=spec.price_gaps,
            )
    return world


def _verdict(db: Database, run_id: int) -> dict[str, Any]:
    row = db.conn.execute(
        "SELECT outcome, max_collateral, annual_return_on_collateral, breakdown,"
        " variants_tested, reason, issued_at FROM verdict WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    return {
        "outcome": row[0],
        "max_collateral": row[1],
        "annual": row[2],
        "breakdown": json.loads(row[3]),
        "variants": row[4],
        "reason": row[5],
        "issued_at": row[6],
    }


def _run_status(db: Database, run_id: int) -> tuple[Any, ...]:
    row = db.conn.execute(
        "SELECT mode, starts_at, ends_at, status, reason FROM run WHERE id = ?", (run_id,)
    ).fetchone()
    return tuple(row)


def _excluded(db: Database, run_id: int) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT a.symbol, e.expected_hours, e.hours_without_funding, e.expected_minutes,"
        " e.minutes_without_snapshot, e.reason FROM excluded_pair e"
        " JOIN pair ON pair.id = e.pair_id JOIN asset a ON a.id = pair.asset_id"
        " WHERE e.run_id = ? ORDER BY a.symbol",
        (run_id,),
    ).fetchall()


def _start_live(db: Database) -> None:
    evaluate(db, D0 + MINUTE_MS)


@pytest.fixture(scope="module")
def overlap_world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Database]:
    """AAA holds hours 0-12 with its Hyperliquid leg liquidated at hour 3, BBB holds hours 7-22."""
    db = Database(tmp_path_factory.mktemp("overlap") / "overlap.db")
    world = build_world(db, [PairSpec("AAA", spiky(-10, 10)), PairSpec("BBB", spiky(5, 20))])
    set_price(db, world["AAA"][1], decision_at(3) + 7 * MINUTE_MS, 50.0)
    _start_live(db)
    yield db
    db.close()


@pytest.fixture(scope="module")
def held_world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Database, int, int]]:
    """AAA opens at hour 0 and is held to the horizon; one Hyperliquid payment has no price."""
    db = Database(tmp_path_factory.mktemp("held") / "held.db")
    payment_minute = H0 + 100 * HOUR_MS
    gap = set(range(payment_minute - 61 * MINUTE_MS, payment_minute + MINUTE_MS, MINUTE_MS))
    world = build_world(db, [PairSpec("AAA", spiky(-10, 10**6), price_gaps=gap)])
    set_price(db, world["AAA"][0], payment_minute, 100.0)
    _start_live(db)
    yield db, *world["AAA"]
    db.close()


def test_ac4_reevaluate_creates_a_reevaluation_run_at_the_live_start_and_decides_to_now(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(-10, 3))])
    _start_live(db)

    first = reevaluate(db, 1, decision_at(3) + MINUTE_MS)
    second = reevaluate(db, 1, decision_at(3) + MINUTE_MS)

    assert first.run_id != second.run_id
    assert _run_status(db, first.run_id) == ("reevaluation", iso(D0), None, "in_progress", None)
    counts = db.conn.execute(
        "SELECT run_id, count(*) FROM decision GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    assert counts == [(1, 1), (first.run_id, 4), (second.run_id, 4)]
    assert db.conn.execute("SELECT count(*) FROM verdict").fetchone()[0] == 0
    assert export_run(db, first.run_id) == export_run(db, second.run_id)


def test_ac4_a_partial_reevaluation_produces_trades_payments_and_measurements(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(-10, 10))])
    _start_live(db)

    result = reevaluate(db, 1, decision_at(2) + MINUTE_MS)

    for table, minimum in (
        ("paper_trade", 2),
        ("paper_funding_payment", 2),
        ("position_measurement", 100),
    ):
        count = db.conn.execute(
            f"SELECT count(*) FROM {table} t JOIN paper_position p ON p.id = t.position_id"
            " WHERE p.run_id = ?",
            (result.run_id,),
        ).fetchone()[0]
        assert count >= minimum, table
    assert future_data_violations(db) == 0


def test_ac4_reevaluating_an_unknown_variant_or_one_without_a_live_run_is_refused(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA")])

    with pytest.raises(ReevaluationError, match="variant 7"):
        reevaluate(db, 7, NOW)
    with pytest.raises(ReevaluationError, match="live run"):
        reevaluate(db, 1, NOW)


def test_r5_the_run_completes_at_the_horizon_with_the_verdict_after_closing_open_positions(
    held_world: tuple[Database, int, int],
) -> None:
    db, pm, hl = held_world

    run_id = reevaluate(db, 1, NOW).run_id

    assert _run_status(db, run_id) == ("reevaluation", iso(D0), iso(END), "complete", None)
    assert db.conn.execute(
        "SELECT status, opened_at, closed_at FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchall() == [("closed", iso(D0), iso(LAST))]
    assert db.conn.execute(
        "SELECT max(hour), count(*) FROM decision WHERE run_id = ?", (run_id,)
    ).fetchone() == (iso(LAST), HORIZON_HOURS)
    closes = db.conn.execute(
        "SELECT hour, kind FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " WHERE p.run_id = ? AND t.kind = 'close'",
        (run_id,),
    ).fetchall()
    assert closes == [(iso(LAST), "close")] * 2
    verdict = _verdict(db, run_id)
    assert verdict["outcome"] == "continue"
    assert verdict["variants"] == 1
    assert verdict["max_collateral"] == 1000.0
    assert verdict["issued_at"] == iso(NOW)
    assert future_data_violations(db) == 0


def _independent_basis(db: Database, run_id: int) -> float:
    """Price result of legs that were closed by a trade; a liquidated leg has none."""
    legs = db.conn.execute(
        "SELECT o.platform_id, p.polymarket_side, o.best_price, c.best_price, o.quantity"
        " FROM paper_trade o JOIN paper_position p ON p.id = o.position_id"
        " JOIN paper_trade c ON c.position_id = o.position_id AND c.platform_id = o.platform_id"
        "  AND c.kind = 'close' WHERE o.kind = 'open' AND p.run_id = ?",
        (run_id,),
    ).fetchall()
    pm_id = db.platform_id(POLYMARKET)
    return float(
        sum(
            (exit_ - entry) * quantity * (1 if (side == "long") == (platform == pm_id) else -1)
            for platform, side, entry, exit_, quantity in legs
        )
    )


def test_dec10_the_breakdown_is_the_signed_sum_of_the_stored_amounts(
    held_world: tuple[Database, int, int],
) -> None:
    db, _, _ = held_world
    run_id = reevaluate(db, 1, NOW).run_id
    verdict = _verdict(db, run_id)
    breakdown = verdict["breakdown"]
    funding, fees, slippage = db.conn.execute(
        "SELECT (SELECT sum(f.amount) FROM paper_funding_payment f"
        "  JOIN paper_position p ON p.id = f.position_id WHERE p.run_id = ?),"
        " sum(t.fee), sum(t.slippage) FROM paper_trade t"
        " JOIN paper_position p ON p.id = t.position_id WHERE p.run_id = ?",
        (run_id, run_id),
    ).fetchone()
    basis = _independent_basis(db, run_id)

    assert breakdown["funding"] == pytest.approx(funding, abs=1e-5)
    assert breakdown["fees"] == pytest.approx(fees, abs=1e-5)
    assert breakdown["slippage"] == pytest.approx(slippage, abs=1e-5)
    assert breakdown["basis"] == pytest.approx(basis, abs=1e-5)
    assert breakdown["basis"] < 0
    assert breakdown["liquidations"] == 0.0
    assert breakdown["net"] == pytest.approx(
        breakdown["funding"] - breakdown["fees"] - breakdown["slippage"] + breakdown["basis"],
        abs=1e-5,
    )
    assert breakdown["pairs"]["AAA"]["net"] == breakdown["net"]
    expected_annual = breakdown["net"] / 1000.0 * 365 / 28
    assert verdict["annual"] == pytest.approx(expected_annual)


def test_r3_a_payment_without_a_price_is_not_credited_and_is_counted_as_uncredited(
    held_world: tuple[Database, int, int],
) -> None:
    db, _, _ = held_world
    run_id = reevaluate(db, 1, NOW).run_id

    credited = db.conn.execute(
        "SELECT p.name, count(*) FROM paper_funding_payment f"
        " JOIN platform p ON p.id = f.platform_id JOIN paper_position pos ON pos.id = f.position_id"
        " WHERE pos.run_id = ? GROUP BY p.name ORDER BY p.name",
        (run_id,),
    ).fetchall()
    assert credited == [(HYPERLIQUID, HORIZON_HOURS - 1 - 1), (POLYMARKET, HORIZON_HOURS - 1)]
    assert _verdict(db, run_id)["breakdown"]["uncredited_payments"] == 1


def test_r7_two_reevaluations_over_the_same_data_are_byte_for_byte_identical(
    overlap_world: Database,
) -> None:
    first = reevaluate(overlap_world, 1, NOW).run_id
    second = reevaluate(overlap_world, 1, NOW + MINUTE_MS).run_id

    assert first != second
    exported = export_run(overlap_world, first)
    assert exported == export_run(overlap_world, second)
    assert '"liquidation"' in exported
    assert '"complete"' in exported
    assert (
        _verdict(overlap_world, first)["issued_at"] != _verdict(overlap_world, second)["issued_at"]
    )


def test_dec10_a_liquidated_leg_costs_its_margin_and_has_no_basis_effect(
    overlap_world: Database,
) -> None:
    run_id = reevaluate(overlap_world, 1, NOW).run_id

    breakdown = _verdict(overlap_world, run_id)["breakdown"]

    assert breakdown["liquidations"] == 500.0
    assert breakdown["pairs"]["AAA"]["liquidations"] == 500.0
    assert breakdown["pairs"]["BBB"]["liquidations"] == 0.0
    liquidated_leg_trades = overlap_world.conn.execute(
        "SELECT count(*) FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " WHERE p.run_id = ? AND t.kind = 'liquidation'",
        (run_id,),
    ).fetchone()[0]
    assert liquidated_leg_trades == 1
    assert breakdown["basis"] == pytest.approx(_independent_basis(overlap_world, run_id), abs=1e-5)
    assert breakdown["net"] == pytest.approx(
        breakdown["funding"]
        - breakdown["fees"]
        - breakdown["slippage"]
        + breakdown["basis"]
        - breakdown["liquidations"],
        abs=1e-5,
    )


def test_tst016_the_collateral_is_the_peak_of_overlapping_positions(
    overlap_world: Database,
) -> None:
    run_id = reevaluate(overlap_world, 1, NOW).run_id

    verdict = _verdict(overlap_world, run_id)

    assert verdict["max_collateral"] == 2000.0
    assert verdict["annual"] == pytest.approx(verdict["breakdown"]["net"] / 2000.0 * 365 / 28)


def test_tst016_positions_that_never_overlap_commit_one_collateral(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(-10, 10)), PairSpec("BBB", spiky(20, 30))])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert _verdict(db, run_id)["max_collateral"] == 1000.0


def test_r6_no_position_opened_gives_investigate_further_with_an_undefined_return(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA")])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    verdict = _verdict(db, run_id)
    assert verdict["outcome"] == "investigate_further"
    assert verdict["annual"] is None
    assert verdict["reason"] == "no positions"
    assert verdict["max_collateral"] == 0.0
    assert verdict["breakdown"]["net"] == 0.0
    assert _run_status(db, run_id)[3] == "complete"


def test_dec5_a_loss_making_run_is_discarded(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    world = build_world(db, [PairSpec("AAA", spiky(-10, 3))])
    set_price(db, world["AAA"][1], decision_at(1) + 5 * MINUTE_MS, 50.0)
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    verdict = _verdict(db, run_id)
    assert verdict["outcome"] == "discard"
    assert verdict["annual"] < 0


def _small() -> PairSpec:
    return PairSpec("AAA", paired_hour=660)


def _late_pair(**overrides: Any) -> PairSpec:
    return PairSpec("BBB", paired_hour=632, **overrides)


def _excluded_after(db: Database) -> list[tuple[Any, ...]]:
    return _excluded(db, reevaluate(db, 1, NOW).run_id)


def test_tst015_a_pair_entering_mid_period_is_judged_over_its_own_period_and_kept(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [_small(), _late_pair()])
    _start_live(db)

    assert _excluded_after(db) == []


@pytest.mark.parametrize(("missing", "excluded"), [(2, False), (3, True)])
def test_tst015_hours_without_funding_are_excluded_only_above_five_percent_of_expected(
    tmp_path: Path, missing: int, excluded: bool
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [_small(), _late_pair(missing_hours=range(640, 640 + missing))])
    _start_live(db)

    rows = _excluded_after(db)

    assert [r[0] for r in rows] == (["BBB"] if excluded else [])
    if excluded:
        assert rows[0][1:5] == (41, 3, 2421, 0)
        assert "hours without funding" in rows[0][5]


def test_tst015_an_hour_missing_on_both_platforms_counts_once_and_on_either_counts(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    spec = _late_pair(missing_hours=[640, 641, 642], missing_hl_hours=[640, 641, 642])
    build_world(db, [_small(), spec])
    _start_live(db)

    rows = _excluded_after(db)

    assert rows[0][2] == 3


def test_tst015_hours_missing_only_on_hyperliquid_count_as_without_funding(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [_small(), _late_pair(missing_hl_hours=[640, 641, 642])])
    _start_live(db)

    assert [r[0:3] for r in _excluded_after(db)] == [("BBB", 41, 3)]


def test_tst015_minutes_missing_only_on_hyperliquid_count_as_without_snapshot(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    gaps = {H0 + 640 * HOUR_MS + i * MINUTE_MS for i in range(243)}
    build_world(db, [_small(), _late_pair(missing_hl_minutes=gaps)])
    _start_live(db)

    assert [r[0] for r in _excluded_after(db)] == ["BBB"]


@pytest.mark.parametrize(("missing", "excluded"), [(242, False), (243, True)])
def test_tst015_minutes_without_snapshot_are_excluded_only_above_ten_percent_of_expected(
    tmp_path: Path, missing: int, excluded: bool
) -> None:
    db = Database(tmp_path / "x.db")
    gaps = {H0 + 640 * HOUR_MS + i * MINUTE_MS for i in range(missing)}
    build_world(db, [_small(), _late_pair(missing_minutes=gaps)])
    _start_live(db)

    rows = _excluded_after(db)

    assert [r[0] for r in rows] == (["BBB"] if excluded else [])
    if excluded:
        assert rows[0][1:5] == (41, 0, 2421, 243)
        assert "minutes without snapshot" in rows[0][5]


def test_tst015_a_pair_is_judged_only_until_it_is_delisted(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    world = build_world(
        db,
        [
            _small(),
            _late_pair(
                missing_hours=range(650, 673),
                missing_minutes=range(H0 + 650 * HOUR_MS, END, MINUTE_MS),
            ),
        ],
    )
    with db.conn:
        db.conn.execute(
            "INSERT INTO instrument_status VALUES (?, ?, 'delisted')",
            (world["BBB"][0], iso(H0 + 650 * HOUR_MS)),
        )
    _start_live(db)

    assert _excluded_after(db) == []


def test_tst015_when_every_pair_is_excluded_the_run_is_not_qualifiable_without_a_verdict(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [_late_pair(missing_hours=range(640, 650))])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    status = _run_status(db, run_id)
    assert status[3] == "not_qualifiable"
    assert "excluded" in status[4]
    assert db.conn.execute("SELECT count(*) FROM verdict").fetchone()[0] == 0


def test_dec12_positions_of_an_excluded_pair_stay_out_of_collateral_and_breakdown(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    spec = PairSpec("AAA", spiky(-10, 10), missing_hours=[h for h in range(40, 40 + 40)])
    build_world(db, [spec, _late_pair()])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert [r[0] for r in _excluded(db, run_id)] == ["AAA"]
    verdict = _verdict(db, run_id)
    assert verdict["outcome"] == "investigate_further"
    assert verdict["reason"] == "no positions"
    assert verdict["max_collateral"] == 0.0
    assert verdict["breakdown"]["funding"] == 0.0
    assert (
        db.conn.execute(
            "SELECT count(*) FROM paper_position WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        > 0
    )


def test_dec9_a_position_whose_close_cannot_fill_at_the_horizon_stays_open_and_is_reported(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(-10, 10**6), last_book_hour=HORIZON_HOURS - 2)])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert db.conn.execute(
        "SELECT status, closed_at FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchall() == [("open", None)]
    assert _verdict(db, run_id)["breakdown"]["unclosed_positions"] == 1


def test_dec6_the_live_run_stops_at_its_horizon_complete_and_without_a_verdict(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [_late_pair(spread=spiky(640, 650))])

    evaluate(db, NOW)

    assert _run_status(db, 1)[3:] == ("complete", None)
    assert db.conn.execute("SELECT count(*) FROM verdict").fetchone()[0] == 0
    assert db.conn.execute("SELECT max(hour) FROM decision").fetchone()[0] == iso(LAST)
    assert evaluate(db, NOW + HOUR_MS).decided == 0


def test_r9_the_verdict_run_reads_nothing_after_its_horizon(tmp_path: Path) -> None:
    def build(path: Path, future: bool) -> Database:
        db = Database(path)
        world = build_world(db, [PairSpec("AAA", spiky(-10, 10))])
        if future:
            set_price(db, world["AAA"][1], END + MINUTE_MS, 1.0)
            set_price(db, world["AAA"][0], LAST + 30 * MINUTE_MS, 9999.0)
        _start_live(db)
        return db

    clean, dirty = build(tmp_path / "a.db", False), build(tmp_path / "b.db", True)

    assert export_run(dirty, reevaluate(dirty, 1, NOW).run_id) == export_run(
        clean, reevaluate(clean, 1, NOW).run_id
    )


def test_r8_verdict_prints_outcome_breakdown_excluded_pairs_and_variants(
    overlap_world: Database, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = reevaluate(overlap_world, 1, NOW).run_id
    path = overlap_world.conn.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("POLYQUACK_DB", path)

    assert cli.main(["verdict", str(run_id)]) == 0

    out = capsys.readouterr().out
    for text in (
        "Outcome: discard",
        "Funding",
        "Fees",
        "Slippage",
        "Basis",
        "Liquidations",
        "Net",
        "2000",
        "Annual return",
        "Excluded pairs: none",
        "Variants tested: 1",
    ):
        assert text in out, text


def test_r8_verdict_of_a_run_without_one_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "x.db"
    db = Database(path)
    build_world(db, [_late_pair(missing_hours=range(640, 650))])
    _start_live(db)
    run_id = reevaluate(db, 1, NOW).run_id
    monkeypatch.setenv("POLYQUACK_DB", str(path))

    assert cli.main(["verdict", str(run_id)]) == 0
    assert cli.main(["verdict", "999"]) == 1

    out = capsys.readouterr()
    assert "not_qualifiable" in out.out and "BBB" in out.out and "hours without funding" in out.out
    assert "No run 999" in out.err


def test_r4_the_reevaluate_command_runs_and_reports_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "x.db"
    db = Database(path)
    build_world(db, [PairSpec("AAA", spiky(-10, 3))])
    _start_live(db)
    db.close()
    monkeypatch.setenv("POLYQUACK_DB", str(path))
    monkeypatch.setattr(time, "time", lambda: (decision_at(2) + MINUTE_MS) / 1000)

    assert cli.main(["reevaluate", "1"]) == 0
    assert cli.main(["reevaluate", "9"]) == 1

    captured = capsys.readouterr()
    assert "Re-evaluation run 2" in captured.out and "in_progress" in captured.out
    assert "variant 9" in captured.err


def test_dec13_variants_tested_counts_only_variants_that_have_run(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", paired_hour=660)])
    _start_live(db)
    preregister(db, prereg_text(rules={"window_hours": 4, "entry": 0.0003, "exit": 0.0001}), NOW)

    run_id = reevaluate(db, 1, NOW).run_id

    assert db.conn.execute("SELECT count(*) FROM variant").fetchone()[0] == 2
    assert _verdict(db, run_id)["variants"] == 1


def test_f1_a_pair_paired_after_the_horizon_plays_no_part_in_the_run(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    build_world(
        db,
        [_late_pair(missing_hours=range(640, 650)), PairSpec("ZZZ", paired_hour=700)],
    )
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert _run_status(db, run_id)[3] == "not_qualifiable"
    assert [r[0] for r in _excluded(db, run_id)] == ["BBB"]
    assert db.conn.execute("SELECT count(*) FROM verdict").fetchone()[0] == 0


def test_f1_a_pair_delisted_before_the_run_starts_plays_no_part_in_the_run(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    world = build_world(
        db, [_late_pair(missing_hours=range(640, 650)), PairSpec("ZZZ", no_data=True)]
    )
    with db.conn:
        db.conn.execute(
            "INSERT INTO instrument_status VALUES (?, ?, 'delisted')",
            (world["ZZZ"][0], iso(H0 - 2 * HOUR_MS)),
        )
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert _run_status(db, run_id)[3] == "not_qualifiable"
    assert db.conn.execute("SELECT count(*) FROM verdict").fetchone()[0] == 0


def test_f2_a_position_that_ends_in_its_opening_minute_still_commits_its_collateral(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    world = build_world(db, [PairSpec("AAA", spiky(-10, 1))])
    set_price(db, world["AAA"][1], D0, 50.0)
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    position = db.conn.execute(
        "SELECT opened_at, closed_at FROM paper_position WHERE run_id = ? ORDER BY id LIMIT 1",
        (run_id,),
    ).fetchone()
    assert position[0] == position[1]
    verdict = _verdict(db, run_id)
    assert verdict["reason"] is None
    assert verdict["outcome"] != "investigate_further"
    assert verdict["max_collateral"] >= 1000.0
    assert verdict["annual"] is not None


def test_f8_an_open_signal_at_the_last_decision_instant_becomes_hold(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(669, 10**6))])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    last = db.conn.execute(
        "SELECT action FROM decision WHERE run_id = ? AND hour = ?", (run_id, iso(LAST))
    ).fetchone()
    assert last == ("hold",)
    assert db.conn.execute(
        "SELECT count(*) FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchone() == (0,)
    verdict = _verdict(db, run_id)
    assert (verdict["outcome"], verdict["reason"]) == ("investigate_further", "no positions")


def test_f5_a_horizon_close_that_cannot_fill_is_retried_minute_by_minute_until_the_horizon_end(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    gap = set(range(D0 + 669 * HOUR_MS, LAST + 10 * MINUTE_MS, MINUTE_MS))
    build_world(db, [PairSpec("AAA", spiky(-10, 10**6), missing_minutes=gap)])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert db.conn.execute(
        "SELECT status, closed_at FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchall() == [("closed", iso(LAST + 10 * MINUTE_MS))]
    closes = db.conn.execute(
        "SELECT t.hour FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " WHERE p.run_id = ? AND t.kind = 'close'",
        (run_id,),
    ).fetchall()
    assert closes == [(iso(LAST + 10 * MINUTE_MS),)] * 2
    assert _verdict(db, run_id)["breakdown"]["unclosed_positions"] == 0


def test_f5_f3_an_uncovered_leg_is_closed_after_the_last_instant_by_the_horizon_retry(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    crash = decision_at(660) + 5 * MINUTE_MS
    gap = set(range(crash - 3 * MINUTE_MS, LAST + 10 * MINUTE_MS, MINUTE_MS))
    world = build_world(db, [PairSpec("AAA", spiky(-10, 10**6), missing_pm_minutes=gap)])
    set_price(db, world["AAA"][1], crash, 50.0)
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert db.conn.execute(
        "SELECT status, closed_at FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchall() == [("closed", iso(LAST + 10 * MINUTE_MS))]
    liquidations = db.conn.execute(
        "SELECT count(*) FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " WHERE p.run_id = ? AND t.kind = 'liquidation'",
        (run_id,),
    ).fetchone()[0]
    assert liquidations == 1
    holds = db.conn.execute(
        "SELECT count(*) FROM decision WHERE run_id = ? AND action = 'hold'", (run_id,)
    ).fetchone()[0]
    assert holds >= 11
    assert db.conn.execute(
        "SELECT count(*) FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchone() == (1,)


def _lock_error() -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def test_f10_a_deferred_horizon_close_blocks_the_accrual_past_the_close_that_comes_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", spiky(-10, 10**6))])
    original = runner._insert_trades
    injected: list[str] = []

    def flaky(db_: Database, position_id: int, hour: str, trades: Any, ids: Any) -> None:
        if hour == iso(LAST) and not injected:
            injected.append(hour)
            raise _lock_error()
        original(db_, position_id, hour, trades, ids)

    monkeypatch.setattr(runner, "_insert_trades", flaky)

    first = evaluate(db, NOW)
    second = evaluate(db, NOW + MINUTE_MS)

    assert (first.deferred, second.deferred) == (1, 0)
    assert db.conn.execute("SELECT status, closed_at FROM paper_position").fetchall() == [
        ("closed", iso(LAST))
    ]
    late = db.conn.execute(
        "SELECT count(*) FROM paper_funding_payment f JOIN paper_position p ON p.id = f.position_id"
        " WHERE f.source_time > p.closed_at"
    ).fetchone()[0]
    assert late == 0
    assert db.conn.execute("SELECT status FROM run").fetchone() == ("complete",)


def test_n6_a_reverse_signal_at_the_last_instant_becomes_a_close_and_opens_nothing(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    build_world(db, [PairSpec("AAA", lambda hour: 0.0003 if hour < 669 else -0.0003)])
    _start_live(db)

    run_id = reevaluate(db, 1, NOW).run_id

    assert db.conn.execute(
        "SELECT action FROM decision WHERE run_id = ? AND hour = ?", (run_id, iso(LAST))
    ).fetchone() == ("close",)
    assert db.conn.execute(
        "SELECT status, closed_at FROM paper_position WHERE run_id = ?", (run_id,)
    ).fetchall() == [("closed", iso(LAST))]


def test_n6_barring_an_open_turns_open_into_hold_and_reverse_into_close() -> None:
    assert runner._without_opening(Choice("open", "long")) == Choice("hold", None)
    assert runner._without_opening(Choice("reverse", "long")) == Choice("close", None)
    assert runner._without_opening(Choice("hold", None)) == Choice("hold", None)
    assert runner._without_opening(Choice("close", None)) == Choice("close", None)


def _unclosed_world(db: Database, **overrides: Any) -> int:
    build_world(
        db,
        [PairSpec("AAA", spiky(-10, 10**6), last_book_hour=HORIZON_HOURS - 2, **overrides)],
    )
    _start_live(db)
    return reevaluate(db, 1, NOW).run_id


def test_n11_a_leg_still_open_after_the_last_instant_is_credited_up_to_the_horizon_end(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "x.db")
    run_id = _unclosed_world(db)

    slot = iso(H0 + HORIZON_HOURS * HOUR_MS + 51)
    credited = db.conn.execute(
        "SELECT count(*) FROM paper_funding_payment f JOIN paper_position p ON p.id = f.position_id"
        " WHERE p.run_id = ? AND f.source_time = ?",
        (run_id, slot),
    ).fetchone()[0]
    assert credited == 2
    assert _verdict(db, run_id)["breakdown"]["uncredited_payments"] == 0


def test_n12_the_uncredited_count_runs_to_the_horizon_end(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    payment_minute = H0 + HORIZON_HOURS * HOUR_MS
    gap = set(range(payment_minute - 61 * MINUTE_MS, payment_minute + MINUTE_MS, MINUTE_MS))
    run_id = _unclosed_world(db, price_gaps=gap)

    assert _verdict(db, run_id)["breakdown"]["uncredited_payments"] == 2


def test_f13_a_lock_in_the_minute_retry_blocks_the_accrual_past_the_close_that_comes_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = Database(tmp_path / "x.db")
    retry_minute = LAST + 10 * MINUTE_MS
    gap = set(range(D0 + 669 * HOUR_MS, retry_minute, MINUTE_MS))
    build_world(db, [PairSpec("AAA", spiky(-10, 10**6), missing_minutes=gap)])
    original = runner._insert_trades
    injected: list[str] = []

    def flaky(db_: Database, position_id: int, hour: str, trades: Any, ids: Any) -> None:
        if hour == iso(retry_minute) and not injected:
            injected.append(hour)
            raise _lock_error()
        original(db_, position_id, hour, trades, ids)

    monkeypatch.setattr(runner, "_insert_trades", flaky)

    first = evaluate(db, NOW)
    second = evaluate(db, NOW + MINUTE_MS)

    assert injected and (first.deferred, second.deferred) == (1, 0)
    assert db.conn.execute("SELECT status, closed_at FROM paper_position").fetchall() == [
        ("closed", iso(retry_minute))
    ]
    late = db.conn.execute(
        "SELECT count(*) FROM paper_funding_payment f JOIN paper_position p ON p.id = f.position_id"
        " WHERE f.source_time > p.closed_at"
    ).fetchone()[0]
    assert late == 0
    assert db.conn.execute("SELECT status FROM run").fetchone() == ("complete",)
