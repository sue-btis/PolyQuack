import sqlite3
from dataclasses import dataclass
from pathlib import Path

from polyquack.ingestion.book import Snapshot
from polyquack.ingestion.models import (
    ACTIVE,
    CLOSE_ONLY,
    DELISTED,
    FeeRate,
    FundingPayment,
    InstrumentInfo,
)
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, from_iso, iso

PLATFORMS = ("polymarket_perps", "hyperliquid")

# kind -> (reading table, its time column, interval length)
_READINGS = {
    "funding": ("funding_reading", "source_time", HOUR_MS),
    "book_snapshot": ("book_snapshot", "minute", MINUTE_MS),
    "price": ("price_reading", "minute", MINUTE_MS),
}


def _latest_status(alias: str) -> str:
    return (
        "COALESCE((SELECT s.status FROM instrument_status s"
        f" WHERE s.instrument_id = {alias}.id ORDER BY s.since DESC LIMIT 1), '{ACTIVE}')"
    )


def derive_pair_status(polymarket: str, hyperliquid: str) -> str:
    statuses = {polymarket, hyperliquid}
    if DELISTED in statuses:
        return DELISTED
    return CLOSE_ONLY if CLOSE_ONLY in statuses else ACTIVE


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    asset: str
    platform: str
    instrument_id: int
    source_id: str


class Database:
    def __init__(
        self, path: Path | str, read_only: bool = False, busy_timeout_ms: int = 5000
    ) -> None:
        self.conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000)
        self.conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self.conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            self.conn.execute("PRAGMA query_only = ON")
            return
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate_fee_schedule()
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.conn.executescript(schema)
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO platform (name) VALUES (?)", [(n,) for n in PLATFORMS]
            )

    def _migrate_fee_schedule(self) -> None:
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(fee_schedule)")]
        if not columns or "category" in columns:
            return
        if self.conn.execute("SELECT count(*) FROM fee_schedule").fetchone()[0]:
            raise MigrationError("fee_schedule has rows but no category column; migrate it by hand")
        with self.conn:
            self.conn.execute("DROP TABLE fee_schedule")

    def close(self) -> None:
        self.conn.close()

    def platform_id(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM platform WHERE name = ?", (name,)).fetchone()
        return int(row[0])

    def upsert_instruments(self, platform: str, infos: list[InstrumentInfo], now_ms: int) -> None:
        platform_id = self.platform_id(platform)
        with self.conn:
            for info in infos:
                self.conn.execute("INSERT OR IGNORE INTO asset (symbol) VALUES (?)", (info.asset,))
                self.conn.execute(
                    "INSERT OR IGNORE INTO instrument"
                    " (platform_id, asset_id, source_id, source_symbol, discovered_at)"
                    " SELECT ?, id, ?, ?, ? FROM asset WHERE symbol = ?",
                    (platform_id, info.source_id, info.source_symbol, iso(now_ms), info.asset),
                )

    def pair_instruments(self, now_ms: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO pair"
                " (asset_id, polymarket_instrument_id, hyperliquid_instrument_id, paired_at)"
                " SELECT pm.asset_id, pm.id, hl.id, ? FROM instrument pm"
                " JOIN instrument hl ON hl.asset_id = pm.asset_id"
                " WHERE pm.platform_id = ? AND hl.platform_id = ?"
                f" AND {_latest_status('pm')} != '{DELISTED}'"
                f" AND {_latest_status('hl')} != '{DELISTED}'",
                (iso(now_ms), self.platform_id(PLATFORMS[0]), self.platform_id(PLATFORMS[1])),
            )

    def pair_statuses(self, assets: tuple[str, ...] = ()) -> dict[str, str]:
        """Derived status per paired asset; an empty `assets` means every pair."""
        rows = self.conn.execute(
            f"SELECT a.symbol, {_latest_status('pm')}, {_latest_status('hl')} FROM pair"
            " JOIN asset a ON a.id = pair.asset_id"
            " JOIN instrument pm ON pm.id = pair.polymarket_instrument_id"
            " JOIN instrument hl ON hl.id = pair.hyperliquid_instrument_id"
            " ORDER BY a.symbol"
        ).fetchall()
        return {s: derive_pair_status(a, b) for s, a, b in rows if not assets or s in assets}

    def targets(self, assets: tuple[str, ...] = (), include_delisted: bool = False) -> list[Target]:
        statuses = self.pair_statuses(assets)
        rows = self.conn.execute(
            "SELECT a.symbol, p.name, i.id, i.source_id FROM pair"
            " JOIN asset a ON a.id = pair.asset_id"
            " JOIN instrument i ON i.id IN"
            "   (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)"
            " JOIN platform p ON p.id = i.platform_id"
            " ORDER BY a.symbol, p.id"
        ).fetchall()
        return [
            Target(*row)
            for row in rows
            if row[0] in statuses and (include_delisted or statuses[row[0]] != DELISTED)
        ]

    def unpaired_instruments(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT p.name, i.source_symbol FROM instrument i"
            " JOIN platform p ON p.id = i.platform_id"
            " WHERE i.asset_id NOT IN (SELECT asset_id FROM pair)"
            f" AND {_latest_status('i')} != '{DELISTED}'"
            " ORDER BY p.id, i.source_symbol"
        ).fetchall()
        return [(str(p), str(s)) for p, s in rows]

    def record_lifecycle(self, platform: str, infos: list[InstrumentInfo], now_ms: int) -> None:
        """Dated status and base-tier parameter rows, only where they differ from the latest."""
        platform_id = self.platform_id(platform)
        with self.conn:
            for info in infos:
                row = self.conn.execute(
                    "SELECT id FROM instrument WHERE platform_id = ? AND source_id = ?",
                    (platform_id, info.source_id),
                ).fetchone()
                self._set_status(int(row[0]), info.status, now_ms)
                self._set_parameters(int(row[0]), info, now_ms)

    def set_status(self, instrument_id: int, status: str, now_ms: int) -> None:
        with self.conn:
            self._set_status(instrument_id, status, now_ms)

    def _set_status(self, instrument_id: int, status: str, now_ms: int) -> None:
        latest = self.conn.execute(
            "SELECT status FROM instrument_status WHERE instrument_id = ?"
            " ORDER BY since DESC LIMIT 1",
            (instrument_id,),
        ).fetchone()
        if latest is None or latest[0] != status:
            self.conn.execute(
                "INSERT INTO instrument_status VALUES (?, ?, ?)",
                (instrument_id, iso(now_ms), status),
            )

    def _set_parameters(self, instrument_id: int, info: InstrumentInfo, now_ms: int) -> None:
        if (
            info.max_leverage is None
            or info.maintenance_margin is None
            or info.min_notional is None
        ):
            return
        values = (
            info.max_leverage,
            info.maintenance_margin,
            info.min_notional,
            info.liquidation_fee,
        )
        latest = self.conn.execute(
            "SELECT max_leverage, maintenance_margin, min_notional, liquidation_fee"
            " FROM instrument_parameters WHERE instrument_id = ?"
            " ORDER BY effective_from DESC LIMIT 1",
            (instrument_id,),
        ).fetchone()
        if latest is None or tuple(latest) != values:
            self.conn.execute(
                "INSERT INTO instrument_parameters VALUES (?, ?, ?, ?, ?, ?)",
                (instrument_id, iso(now_ms), *values),
            )

    def absent_instruments(self, platform: str, source_ids: set[str]) -> list[tuple[int, str]]:
        """Stored instruments of the platform missing from `source_ids` and not yet delisted."""
        rows = self.conn.execute(
            "SELECT i.id, i.source_id FROM instrument i WHERE i.platform_id = ?"
            f" AND {_latest_status('i')} != '{DELISTED}' ORDER BY i.id",
            (self.platform_id(platform),),
        ).fetchall()
        return [(int(i), str(s)) for i, s in rows if s not in source_ids]

    def sync_fees(self, platform: str, rates: list[FeeRate], now_ms: int) -> None:
        """Insert a dated row set per category when it differs from that category's latest."""
        platform_id = self.platform_id(platform)
        dated: dict[tuple[str, int], list[FeeRate]] = {}
        for rate in rates:
            effective = now_ms if rate.effective_from_ms is None else rate.effective_from_ms
            dated.setdefault((rate.category, effective), []).append(rate)
        with self.conn:
            for (category, effective), group in sorted(dated.items(), key=lambda kv: kv[0][1]):
                wanted = {(r.tier, r.taker, r.maker) for r in group}
                if wanted == self._latest_fees(platform_id, category):
                    continue
                self.conn.executemany(
                    "INSERT OR IGNORE INTO fee_schedule VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (platform_id, iso(effective), category, r.tier, r.taker, r.maker)
                        for r in group
                    ],
                )

    def _latest_fees(self, platform_id: int, category: str) -> set[tuple[str, float, float]]:
        rows = self.conn.execute(
            "SELECT tier, taker, maker FROM fee_schedule WHERE platform_id = ? AND category = ?"
            " AND effective_from = (SELECT max(effective_from) FROM fee_schedule"
            "   WHERE platform_id = ? AND category = ?)",
            (platform_id, category, platform_id, category),
        ).fetchall()
        return {(str(t), float(a), float(b)) for t, a, b in rows}

    def insert_funding(
        self, instrument_id: int, source_time_ms: int, rate: float, received_ms: int
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO funding_reading VALUES (?, ?, ?, ?, 'live')",
                (instrument_id, iso(source_time_ms), rate, iso(received_ms)),
            )

    def insert_funding_history(
        self, instrument_id: int, payments: list[FundingPayment], received_ms: int
    ) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO funding_reading VALUES (?, ?, ?, ?, 'history')",
                [
                    (instrument_id, iso(p.source_time_ms), p.rate, iso(received_ms))
                    for p in payments
                ],
            )

    def earliest_funding_ms(self, instrument_id: int) -> int | None:
        """Start of the first hour holding a funding reading or gap."""
        reading = self.conn.execute(
            "SELECT min(source_time) FROM funding_reading WHERE instrument_id = ?",
            (instrument_id,),
        ).fetchone()[0]
        gap = self.conn.execute(
            "SELECT min(starts_at) FROM gap WHERE instrument_id = ? AND kind = 'funding'",
            (instrument_id,),
        ).fetchone()[0]
        starts = []
        if reading is not None:
            starts.append(floor_to(from_iso(reading) + HOUR_MS // 2, HOUR_MS))
        if gap is not None:
            starts.append(from_iso(gap))
        return min(starts) if starts else None

    def oldest_open_funding_gap_ms(self, instrument_id: int) -> int | None:
        oldest = self.conn.execute(
            "SELECT min(starts_at) FROM gap"
            " WHERE instrument_id = ? AND kind = 'funding' AND status = 'open'",
            (instrument_id,),
        ).fetchone()[0]
        return None if oldest is None else from_iso(oldest)

    def close_funding_gaps(
        self, instrument_id: int, newest_payment_ms: int | None, now_ms: int
    ) -> int:
        """Settle the open funding gaps of an instrument against the stored readings.

        A gap with a reading becomes closed_with_data; one without a reading, while a later
        payment exists in the history just read, becomes final. Returns how many were settled.
        """
        gaps = self.conn.execute(
            "SELECT id, starts_at FROM gap"
            " WHERE instrument_id = ? AND kind = 'funding' AND status = 'open'",
            (instrument_id,),
        ).fetchall()
        newest_hour = (
            None
            if newest_payment_ms is None
            else floor_to(newest_payment_ms + HOUR_MS // 2, HOUR_MS)
        )
        settled = 0
        with self.conn:
            for gap_id, starts_at in gaps:
                start = from_iso(starts_at)
                has_reading = self.conn.execute(
                    "SELECT 1 FROM funding_reading WHERE instrument_id = ?"
                    " AND source_time >= ? AND source_time < ?",
                    (instrument_id, iso(start - HOUR_MS // 2), iso(start + HOUR_MS // 2)),
                ).fetchone()
                if has_reading:
                    status = "closed_with_data"
                elif newest_hour is not None and newest_hour > start:
                    status = "final"
                else:
                    continue
                self.conn.execute(
                    "UPDATE gap SET status = ?, closed_at = ? WHERE id = ?",
                    (status, iso(now_ms), gap_id),
                )
                settled += 1
        return settled

    def insert_snapshot(self, instrument_id: int, minute_ms: int, snap: Snapshot) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO book_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    instrument_id,
                    iso(minute_ms),
                    iso(snap.source_time_ms),
                    snap.best_bid,
                    snap.best_ask,
                    snap.bid_notional_05,
                    snap.ask_notional_05,
                    snap.bid_levels,
                    snap.ask_levels,
                    snap.bid_reach,
                    snap.ask_reach,
                ),
            )

    def insert_price(
        self,
        instrument_id: int,
        minute_ms: int,
        mark_price: float,
        index_price: float,
        source_time_ms: int | None,
        received_ms: int,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO price_reading VALUES (?, ?, ?, ?, ?, ?)",
                (
                    instrument_id,
                    iso(minute_ms),
                    mark_price,
                    index_price,
                    None if source_time_ms is None else iso(source_time_ms),
                    iso(received_ms),
                ),
            )

    def insert_gap(
        self,
        platform: str,
        instrument_id: int | None,
        kind: str,
        starts_ms: int,
        ends_ms: int,
        cause: str,
        status: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO gap (platform_id, instrument_id, kind, starts_at, ends_at, cause,"
                " status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self.platform_id(platform),
                    instrument_id,
                    kind,
                    iso(starts_ms),
                    iso(ends_ms),
                    cause,
                    status,
                ),
            )

    def insert_gaps(
        self,
        platform: str,
        instrument_id: int,
        kind: str,
        intervals: list[tuple[int, int]],
        cause: str,
        status: str,
    ) -> None:
        platform_id = self.platform_id(platform)
        with self.conn:
            self.conn.executemany(
                "INSERT INTO gap (platform_id, instrument_id, kind, starts_at, ends_at, cause,"
                " status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (platform_id, instrument_id, kind, iso(a), iso(b), cause, status)
                    for a, b in intervals
                ],
            )

    def covered_until_ms(self, instrument_id: int, kind: str) -> int | None:
        """End of the latest interval of this kind already holding a reading or a gap."""
        table, column, step = _READINGS[kind]
        ends: list[int] = []
        latest = self.conn.execute(
            f"SELECT max({column}) FROM {table} WHERE instrument_id = ?", (instrument_id,)
        ).fetchone()[0]
        if latest is not None:
            # Rounded, not floored: a payment stamped just before the hour belongs to that hour.
            ends.append(floor_to(from_iso(latest) + step // 2, step) + step)
        latest_gap = self.conn.execute(
            "SELECT max(ends_at) FROM gap WHERE instrument_id = ? AND kind = ?",
            (instrument_id, kind),
        ).fetchone()[0]
        if latest_gap is not None:
            ends.append(from_iso(latest_gap))
        return max(ends) if ends else None
