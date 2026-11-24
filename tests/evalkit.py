import json
from collections.abc import Collection, Iterable
from typing import Any

from polyquack.evaluation.runner import evaluate
from polyquack.ingestion.book import build_snapshot
from polyquack.ingestion.models import BookLevels, FeeRate, Levels
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, from_iso, iso

from .conftest import T0, seed_pairs

H0 = floor_to(T0, HOUR_MS) + HOUR_MS
D0 = H0 + 21 * MINUTE_MS
FEE_FROM = H0 - 24 * HOUR_MS
PM_TAKER = 0.0004
HL_TAKER = 0.00045
ENTRY = 0.0002
EXIT = 0.00005


def decision_at(hour_index: int) -> int:
    return D0 + hour_index * HOUR_MS


def prereg(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "method": "E1",
        "rules": {"window_hours": 3, "entry": ENTRY, "exit": EXIT},
        "metric": "net_return_on_collateral",
        "horizon_days": 28,
        "criterion": {"min_annual_net_return_on_collateral": 0.10},
        "size_per_leg_usd": 1000,
        "leverage": 2,
        "decision_minute": 21,
        "snapshot_max_age_seconds": 120,
    }
    document.update(overrides)
    return document


def prereg_text(**overrides: Any) -> str:
    return json.dumps(prereg(**overrides))


def seed_world(db: Database, with_fees: bool = True) -> tuple[int, int]:
    """One AAA pair with both taker fees; returns the Polymarket and Hyperliquid instrument ids."""
    seed_pairs(db, ["AAA"])
    pm, hl = (t.instrument_id for t in db.targets())
    if with_fees:
        db.sync_fees(POLYMARKET, [FeeRate("crypto", "0", PM_TAKER, 0.000125, FEE_FROM)], FEE_FROM)
        db.sync_fees(HYPERLIQUID, [FeeRate("", "0", HL_TAKER, 0.00015, FEE_FROM)], FEE_FROM)
    return pm, hl


def fund(db: Database, instrument_id: int, hour_ms: int, rate: float, lag_ms: int = 51) -> None:
    db.insert_funding(instrument_id, hour_ms + lag_ms, rate, hour_ms + 2 * MINUTE_MS)


def fund_spread(db: Database, pm: int, hl: int, hour_ms: int, spread: float) -> None:
    fund(db, pm, hour_ms, spread + 0.0001)
    fund(db, hl, hour_ms, 0.0001)


def book(
    db: Database,
    instrument_id: int,
    minute_ms: int,
    bids: Levels,
    asks: Levels,
    source_time_ms: int | None = None,
) -> None:
    source = minute_ms + 5_000 if source_time_ms is None else source_time_ms
    snapshot = build_snapshot(BookLevels(bids, asks, source))
    assert snapshot is not None
    db.insert_snapshot(instrument_id, minute_ms, snapshot)


PM_BIDS: Levels = [(100.0, 6.0), (99.9, 10.0)]
PM_ASKS: Levels = [(100.1, 20.0)]
HL_BIDS: Levels = [(99.9, 20.0)]
HL_ASKS: Levels = [(100.1, 3.0), (100.2, 50.0)]


def standard_books(db: Database, pm: int, hl: int, decision_ms: int) -> None:
    minute = decision_ms - MINUTE_MS
    book(db, pm, minute, PM_BIDS, PM_ASKS)
    book(db, hl, minute, HL_BIDS, HL_ASKS)


def run_hours(db: Database, *hour_indexes: int) -> None:
    """Evaluate once per hour index, the clock one minute after that decision instant."""
    for index in hour_indexes:
        evaluate(db, decision_at(index) + MINUTE_MS)


def decisions(db: Database) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT hour, action, funding_spread, cause FROM decision ORDER BY rowid"
    ).fetchall()


def iso_decision(hour_index: int) -> str:
    return iso(decision_at(hour_index))


def seed_prices(
    db: Database,
    instrument_id: int,
    first_minute_ms: int,
    minutes: int,
    mark: float,
    index: float | None = None,
    skip: Collection[int] = (),
) -> None:
    rows = [
        (instrument_id, iso(m), mark, mark if index is None else index, None, iso(m))
        for m in range(first_minute_ms, first_minute_ms + minutes * MINUTE_MS, MINUTE_MS)
        if m not in skip
    ]
    with db.conn:
        db.conn.executemany("INSERT OR REPLACE INTO price_reading VALUES (?, ?, ?, ?, ?, ?)", rows)


def set_price(
    db: Database, instrument_id: int, minute_ms: int, mark: float, index: float | None = None
) -> None:
    seed_prices(db, instrument_id, minute_ms, 1, mark, index)


def set_margin(db: Database, instrument_id: int, effective_ms: int, margin: float) -> None:
    with db.conn:
        db.conn.execute(
            "INSERT INTO instrument_parameters VALUES (?, ?, 20, ?, 10, NULL)",
            (instrument_id, iso(effective_ms), margin),
        )


def seed_funding_hours(
    db: Database, instrument_id: int, hours_ms: Iterable[int], rate: float
) -> None:
    with db.conn:
        db.conn.executemany(
            "INSERT OR IGNORE INTO funding_reading VALUES (?, ?, ?, ?, 'live')",
            [(instrument_id, iso(h + 51), rate, iso(h + 2 * MINUTE_MS)) for h in hours_ms],
        )


def seed_books(
    db: Database,
    instrument_id: int,
    minutes_ms: Iterable[int],
    bids: Levels = PM_BIDS,
    asks: Levels = PM_ASKS,
) -> None:
    snapshot = build_snapshot(BookLevels(bids, asks, 0))
    assert snapshot is not None
    rows = [
        (
            instrument_id,
            iso(m),
            iso(m + 5_000),
            snapshot.best_bid,
            snapshot.best_ask,
            snapshot.bid_notional_05,
            snapshot.ask_notional_05,
            snapshot.bid_levels,
            snapshot.ask_levels,
            snapshot.bid_reach,
            snapshot.ask_reach,
        )
        for m in minutes_ms
    ]
    with db.conn:
        db.conn.executemany(
            "INSERT OR IGNORE INTO book_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def future_data_violations(db: Database) -> int:
    """Count readings that postdate the instant they were used at; zero means no future data."""
    late_reads = db.conn.execute("SELECT count(*) FROM decision WHERE data_until > hour")
    early_payments = db.conn.execute(
        "SELECT count(*) FROM paper_funding_payment f JOIN paper_position p ON p.id = f.position_id"
        " WHERE f.source_time <= p.opened_at"
        "  OR f.source_time > (SELECT max(hour) FROM decision WHERE run_id = p.run_id)"
        "  OR f.source_time > p.closed_at"
        "  OR f.source_time > COALESCE((SELECT min(t.hour) FROM paper_trade t"
        "   WHERE t.position_id = p.id AND t.platform_id = f.platform_id"
        "   AND t.kind IN ('close', 'liquidation')), f.source_time)"
    )
    late_snapshots = db.conn.execute(
        "SELECT b.source_time, t.hour, EXISTS (SELECT 1 FROM decision d"
        "  WHERE d.run_id = p.run_id AND d.pair_id = p.pair_id AND d.hour = t.hour)"
        " FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " JOIN pair ON pair.id = p.pair_id"
        " JOIN instrument i ON i.platform_id = t.platform_id"
        "  AND i.id IN (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)"
        " JOIN book_snapshot b ON b.instrument_id = i.id AND b.minute = t.snapshot_minute"
        " WHERE t.kind != 'liquidation'"
    ).fetchall()
    # A minute step reads up to the end of its minute; a decision only up to its instant.
    late_snapshot_count = sum(
        from_iso(source) > from_iso(hour) + (0 if at_decision else MINUTE_MS)
        for source, hour, at_decision in late_snapshots
    )
    unpriced_liquidations = db.conn.execute(
        "SELECT count(*) FROM paper_trade t JOIN paper_position p ON p.id = t.position_id"
        " JOIN pair ON pair.id = p.pair_id"
        " JOIN instrument i ON i.platform_id = t.platform_id"
        "  AND i.id IN (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)"
        " WHERE t.kind = 'liquidation' AND NOT EXISTS (SELECT 1 FROM price_reading r"
        "  WHERE r.instrument_id = i.id AND r.minute = t.hour)"
    )
    wrong_minute_measurements = db.conn.execute(
        "SELECT count(*) FROM position_measurement m JOIN paper_position p ON p.id = m.position_id"
        " JOIN pair ON pair.id = p.pair_id"
        " LEFT JOIN price_reading a ON a.instrument_id = pair.polymarket_instrument_id"
        "  AND a.minute = m.minute"
        " LEFT JOIN price_reading b ON b.instrument_id = pair.hyperliquid_instrument_id"
        "  AND b.minute = m.minute"
        " WHERE m.minute < p.opened_at OR m.minute > COALESCE(p.closed_at, m.minute)"
        "  OR (m.basis IS NULL) != (a.mark_price IS NULL OR b.mark_price IS NULL)"
        "  OR (m.basis IS NOT NULL AND abs(m.basis - (a.mark_price - b.mark_price)) > 1e-9)"
    )
    counts = (
        cursor.fetchone()[0]
        for cursor in (late_reads, early_payments, unpriced_liquidations, wrong_minute_measurements)
    )
    return int(sum(counts)) + late_snapshot_count


def export_run(db: Database, run_id: int) -> str:
    """Everything a run produced as sorted JSON, without row ids or the verdict's issue time."""

    def rows(sql: str, *args: Any) -> list[list[Any]]:
        return [list(row) for row in db.conn.execute(sql, args).fetchall()]

    positions = db.conn.execute(
        "SELECT p.id, a.symbol, p.polymarket_side, p.notional_per_leg, p.leverage, p.opened_at,"
        " p.closed_at, p.status FROM paper_position p JOIN pair ON pair.id = p.pair_id"
        " JOIN asset a ON a.id = pair.asset_id WHERE p.run_id = ?"
        " ORDER BY a.symbol, p.opened_at, p.id",
        (run_id,),
    ).fetchall()
    exported: dict[str, Any] = {
        "run": rows("SELECT status, starts_at, ends_at, reason FROM run WHERE id = ?", run_id),
        "decisions": rows(
            "SELECT a.symbol, d.hour, d.action, d.data_until, d.funding_spread, d.cause"
            " FROM decision d JOIN pair ON pair.id = d.pair_id JOIN asset a ON a.id = pair.asset_id"
            " WHERE d.run_id = ? ORDER BY a.symbol, d.hour",
            run_id,
        ),
        "positions": [
            {
                "position": list(position[1:]),
                "trades": rows(
                    "SELECT p.name, t.kind, t.hour, t.side, t.avg_price, t.best_price, t.quantity,"
                    " t.fee, t.slippage, t.loss, t.snapshot_minute FROM paper_trade t"
                    " JOIN platform p ON p.id = t.platform_id WHERE t.position_id = ?"
                    " ORDER BY t.id",
                    position[0],
                ),
                "payments": rows(
                    "SELECT p.name, f.source_time, f.rate, f.amount FROM paper_funding_payment f"
                    " JOIN platform p ON p.id = f.platform_id WHERE f.position_id = ?"
                    " ORDER BY f.source_time, p.name",
                    position[0],
                ),
                "measurements": rows(
                    "SELECT minute, basis, basis_change, polymarket_liquidation_distance,"
                    " hyperliquid_liquidation_distance FROM position_measurement"
                    " WHERE position_id = ? ORDER BY minute",
                    position[0],
                ),
            }
            for position in positions
        ],
        "excluded": rows(
            "SELECT a.symbol, e.expected_hours, e.hours_without_funding, e.expected_minutes,"
            " e.minutes_without_snapshot, e.reason FROM excluded_pair e"
            " JOIN pair ON pair.id = e.pair_id JOIN asset a ON a.id = pair.asset_id"
            " WHERE e.run_id = ? ORDER BY a.symbol",
            run_id,
        ),
        "verdict": rows(
            "SELECT outcome, max_collateral, annual_return_on_collateral, breakdown,"
            " variants_tested, reason FROM verdict WHERE run_id = ?",
            run_id,
        ),
    }
    return json.dumps(exported, sort_keys=True)
