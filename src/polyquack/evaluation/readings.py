import json
import sqlite3
from dataclasses import dataclass

from polyquack.ingestion.models import ACTIVE, Levels
from polyquack.storage.db import derive_pair_status
from polyquack.times import HOUR_MS, floor_to, from_iso, iso

BASE_TIER = "0"


@dataclass(frozen=True)
class BookSnapshot:
    minute_ms: int
    source_time_ms: int
    bids: Levels
    asks: Levels


class Reader:
    """The evaluator's only read path; every query bounds `source_time` by the cutoff."""

    def __init__(self, conn: sqlite3.Connection, cutoff_ms: int) -> None:
        self._conn = conn
        self._cutoff = iso(cutoff_ms)
        self._cutoff_ms = cutoff_ms
        self.data_until_ms: int | None = None

    def _seen(self, source_time: str) -> None:
        moment = from_iso(source_time)
        if self.data_until_ms is None or moment > self.data_until_ms:
            self.data_until_ms = moment

    def funding_by_hour(
        self, instrument_id: int, first_hour_ms: int, last_hour_ms: int
    ) -> dict[int, float]:
        """Rate per hour (rounded like ingestion), the latest reading up to the cutoff winning."""
        rows = self._conn.execute(
            "SELECT source_time, rate FROM funding_reading WHERE instrument_id = ?"
            " AND source_time >= ? AND source_time < ? AND source_time <= ?"
            " ORDER BY source_time",
            (
                instrument_id,
                iso(first_hour_ms - HOUR_MS // 2),
                iso(last_hour_ms + HOUR_MS // 2),
                self._cutoff,
            ),
        ).fetchall()
        rates: dict[int, float] = {}
        for source_time, rate in rows:
            self._seen(source_time)
            rates[floor_to(from_iso(source_time) + HOUR_MS // 2, HOUR_MS)] = float(rate)
        return rates

    def payments(self, instrument_id: int, after_ms: int, until_ms: int) -> list[tuple[int, float]]:
        """Funding readings with `after_ms < source_time <= min(until_ms, cutoff)`."""
        rows = self._conn.execute(
            "SELECT source_time, rate FROM funding_reading WHERE instrument_id = ?"
            " AND source_time > ? AND source_time <= ? ORDER BY source_time",
            (instrument_id, iso(after_ms), iso(min(until_ms, self._cutoff_ms))),
        ).fetchall()
        for source_time, _ in rows:
            self._seen(source_time)
        return [(from_iso(source_time), float(rate)) for source_time, rate in rows]

    def snapshot(self, instrument_id: int, max_age_ms: int) -> BookSnapshot | None:
        row = self._conn.execute(
            "SELECT minute, source_time, bid_levels, ask_levels FROM book_snapshot"
            " WHERE instrument_id = ? AND source_time <= ? AND source_time >= ?"
            " ORDER BY source_time DESC LIMIT 1",
            (instrument_id, self._cutoff, iso(self._cutoff_ms - max_age_ms)),
        ).fetchone()
        if row is None:
            return None
        self._seen(row[1])
        return BookSnapshot(
            from_iso(row[0]),
            from_iso(row[1]),
            [(float(p), float(q)) for p, q in json.loads(row[2])],
            [(float(p), float(q)) for p, q in json.loads(row[3])],
        )

    def pair_status(self, polymarket_instrument_id: int, hyperliquid_instrument_id: int) -> str:
        """Derived pair status from each instrument's latest status row dated by the cutoff."""
        statuses = []
        for instrument_id in (polymarket_instrument_id, hyperliquid_instrument_id):
            row = self._conn.execute(
                "SELECT status FROM instrument_status WHERE instrument_id = ? AND since <= ?"
                " ORDER BY since DESC LIMIT 1",
                (instrument_id, self._cutoff),
            ).fetchone()
            statuses.append(ACTIVE if row is None else str(row[0]))
        return derive_pair_status(statuses[0], statuses[1])

    def taker_fee(self, platform: str, category: str) -> float | None:
        """Base-tier taker rate of the latest schedule effective by the cutoff."""
        row = self._conn.execute(
            "SELECT f.taker FROM fee_schedule f JOIN platform p ON p.id = f.platform_id"
            " WHERE p.name = ? AND f.category = ? AND f.tier = ? AND f.effective_from <= ?"
            " ORDER BY f.effective_from DESC LIMIT 1",
            (platform, category, BASE_TIER, self._cutoff),
        ).fetchone()
        return None if row is None else float(row[0])
