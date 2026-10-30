import asyncio
import json
import logging
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from polyquack.ingestion.book import BookState
from polyquack.ingestion.feed import BookFeed
from polyquack.ingestion.models import BookLevels, FundingPayment, InstrumentInfo, PriceQuote
from polyquack.ingestion.platforms import Platform


class _LocalPlatform(Platform):
    name = "local"

    def __init__(self, ws_url: str, resync_book: BookLevels) -> None:
        self.ws_url = ws_url
        self._resync_book = resync_book

    async def instruments(self) -> list[InstrumentInfo]:
        return []

    async def funding(self, source_id: str, hour_ms: int) -> FundingPayment | None:
        return None

    async def prices(self) -> dict[str, PriceQuote]:
        return {}

    async def book(self, source_id: str) -> BookLevels:
        return self._resync_book

    def subscribe_messages(self, source_ids: list[str]) -> list[dict[str, Any]]:
        return [{"sub": source_ids}]

    def parse_book_message(self, message: Any) -> tuple[str, BookLevels] | None:
        if "bid" not in message:
            return None
        return "X", BookLevels([(message["bid"], 1.0)], [(message["bid"] + 1, 1.0)], 1)


def test_dropped_connection_invalidates_the_book_and_the_feed_resyncs_after_reconnecting() -> None:
    state = BookState()
    resync = BookLevels([(5.0, 1.0)], [(6.0, 1.0)], 9)
    observed: list[tuple[str, bool]] = []
    connections = 0
    finished = asyncio.Event()

    async def server(ws: ServerConnection) -> None:
        nonlocal connections
        await ws.recv()
        connections += 1
        if connections == 1:
            await ws.send(json.dumps({"bid": 100.0}))
            await asyncio.sleep(0.2)
            observed.append(("after first message", state.book is not None))
            await ws.close()
            await asyncio.sleep(0.2)
            observed.append(("after drop", state.book is not None))
        else:
            await asyncio.sleep(0.3)
            observed.append(("after reconnection and resync", state.book == resync))
            finished.set()
            await ws.wait_closed()

    async def scenario() -> None:
        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            feed = BookFeed(_LocalPlatform(f"ws://127.0.0.1:{port}", resync), {"X": state})
            task = asyncio.create_task(feed.run())
            await finished.wait()
            task.cancel()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))

    assert observed == [
        ("after first message", True),
        ("after drop", False),
        ("after reconnection and resync", True),
    ]


def test_reconnect_delay_returns_to_the_initial_one_after_an_aborted_healthy_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = BookState()
    connections = 0
    third_connected = asyncio.Event()

    async def server(ws: ServerConnection) -> None:
        nonlocal connections
        await ws.recv()
        connections += 1
        if connections < 3:
            await ws.send(json.dumps({"bid": 100.0}))
            await asyncio.sleep(0.1)
            ws.transport.abort()
        else:
            third_connected.set()
            await ws.wait_closed()

    async def scenario() -> None:
        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            platform = _LocalPlatform(f"ws://127.0.0.1:{port}", BookLevels([], [], 0))
            task = asyncio.create_task(BookFeed(platform, {"X": state}).run())
            await third_connected.wait()
            task.cancel()

    with caplog.at_level(logging.INFO, logger="polyquack.ingestion.feed"):
        asyncio.run(asyncio.wait_for(scenario(), timeout=20))

    delays = [r.getMessage() for r in caplog.records if "reconnecting" in r.getMessage()]
    assert delays == ["local: reconnecting in 1 s", "local: reconnecting in 1 s"]


def test_reconnect_delay_doubles_while_sessions_receive_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connections = 0
    second_connected = asyncio.Event()

    async def server(ws: ServerConnection) -> None:
        nonlocal connections
        await ws.recv()
        connections += 1
        if connections < 2:
            ws.transport.abort()
        else:
            second_connected.set()
            await ws.wait_closed()

    async def scenario() -> None:
        async with serve(server, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            platform = _LocalPlatform(f"ws://127.0.0.1:{port}", BookLevels([], [], 0))
            task = asyncio.create_task(BookFeed(platform, {"X": BookState()}).run())
            await second_connected.wait()
            task.cancel()

    with caplog.at_level(logging.INFO, logger="polyquack.ingestion.feed"):
        asyncio.run(asyncio.wait_for(scenario(), timeout=20))

    delays = [r.getMessage() for r in caplog.records if "reconnecting" in r.getMessage()]
    assert delays == ["local: reconnecting in 2 s"]
