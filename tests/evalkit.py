import json
from typing import Any

from polyquack.evaluation.runner import evaluate
from polyquack.ingestion.book import build_snapshot
from polyquack.ingestion.models import BookLevels, FeeRate, Levels
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

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
