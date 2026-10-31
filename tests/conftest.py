from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from polyquack.ingestion.book import BookState
from polyquack.ingestion.models import BookLevels, InstrumentInfo
from polyquack.ingestion.platforms import (
    HYPERLIQUID,
    POLYMARKET,
    Hyperliquid,
    Platform,
    PolymarketPerps,
)
from polyquack.ingestion.ratelimit import RateLimiter
from polyquack.ingestion.service import Service
from polyquack.storage.db import Database
from polyquack.times import MINUTE_MS, floor_to

T0 = floor_to(1_793_223_365_393, MINUTE_MS)

Handler = Callable[[httpx.Request], httpx.Response]


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def seed_btc(db: Database) -> None:
    db.upsert_instruments(POLYMARKET, [InstrumentInfo("6", "BTC-USD", "BTC")], T0)
    db.upsert_instruments(HYPERLIQUID, [InstrumentInfo("BTC", "BTC", "BTC")], T0)
    db.pair_instruments(T0)


def platforms_over(handler: Handler) -> dict[str, Platform]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return {
        POLYMARKET: PolymarketPerps(http, RateLimiter(0.8, sleep=no_sleep)),
        HYPERLIQUID: Hyperliquid(http, RateLimiter(0.8, sleep=no_sleep)),
    }


def make_service(
    db: Database, platforms: dict[str, Platform], now_ms: int, valid_book: bool = False
) -> Service:
    seed_btc(db)
    service = Service(db, platforms, ("BTC",), clock=lambda: now_ms, sleep=no_sleep)
    service.targets = db.targets(("BTC",))
    service.books = {t.instrument_id: BookState() for t in service.targets}
    if valid_book:
        for state in service.books.values():
            state.replace(BookLevels([(99.0, 1.0)], [(101.0, 1.0)], now_ms))
    return service
