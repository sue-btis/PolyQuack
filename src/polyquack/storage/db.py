import sqlite3
from dataclasses import dataclass
from pathlib import Path

from polyquack.ingestion.book import Snapshot
from polyquack.ingestion.models import InstrumentInfo
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, from_iso, iso

PLATFORMS = ("polymarket_perps", "hyperliquid")

# kind -> (reading table, its time column, interval length)
_READINGS = {
    "funding": ("funding_reading", "source_time", HOUR_MS),
    "book_snapshot": ("book_snapshot", "minute", MINUTE_MS),
    "price": ("price_reading", "minute", MINUTE_MS),
}


@dataclass(frozen=True)
class Target:
    asset: str
    platform: str
    instrument_id: int
    source_id: str


class Database:
    def __init__(self, path: Path | str, read_only: bool = False) -> None:
        self.conn = sqlite3.connect(path, timeout=5)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            self.conn.execute("PRAGMA query_only = ON")
            return
        self.conn.execute("PRAGMA journal_mode = WAL")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.conn.executescript(schema)
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO platform (name) VALUES (?)", [(n,) for n in PLATFORMS]
            )

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
                " WHERE pm.platform_id = ? AND hl.platform_id = ?",
                (iso(now_ms), self.platform_id(PLATFORMS[0]), self.platform_id(PLATFORMS[1])),
            )

    def targets(self, assets: tuple[str, ...]) -> list[Target]:
        found: list[Target] = []
        for asset in assets:
            rows = self.conn.execute(
                "SELECT a.symbol, p.name, i.id, i.source_id FROM pair"
                " JOIN asset a ON a.id = pair.asset_id"
                " JOIN instrument i ON i.id IN"
                "   (pair.polymarket_instrument_id, pair.hyperliquid_instrument_id)"
                " JOIN platform p ON p.id = i.platform_id"
                " WHERE a.symbol = ? ORDER BY p.id",
                (asset,),
            ).fetchall()
            found += [Target(*row) for row in rows]
        return found

    def unpaired_instruments(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT p.name, i.source_symbol FROM instrument i"
            " JOIN platform p ON p.id = i.platform_id"
            " WHERE i.asset_id NOT IN (SELECT asset_id FROM pair)"
            " ORDER BY p.id, i.source_symbol"
        ).fetchall()
        return [(str(p), str(s)) for p, s in rows]

    def insert_funding(
        self, instrument_id: int, source_time_ms: int, rate: float, received_ms: int
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO funding_reading VALUES (?, ?, ?, ?, 'live')",
                (instrument_id, iso(source_time_ms), rate, iso(received_ms)),
            )

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
