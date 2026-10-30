import asyncio
import json
import logging

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from polyquack.ingestion.book import BookState
from polyquack.ingestion.platforms import SOURCE_ERRORS, Platform

log = logging.getLogger(__name__)

MAX_RECONNECT_SECONDS = 60.0
# Dead connections surface within about 20 s; until then the book still reads as valid.
PING_INTERVAL_SECONDS = 10
PING_TIMEOUT_SECONDS = 10


class BookFeed:
    """Keeps the in-memory books of one platform fed from its live channel."""

    def __init__(self, platform: Platform, books: dict[str, BookState]) -> None:
        self._platform = platform
        self._books = books
        self._received = False

    async def run(self) -> None:
        delay = 1.0
        while True:
            self._received = False
            try:
                async with connect(
                    self._platform.ws_url,
                    ping_interval=PING_INTERVAL_SECONDS,
                    ping_timeout=PING_TIMEOUT_SECONDS,
                ) as ws:
                    await self._session(ws)
            except (OSError, WebSocketException, TimeoutError) as error:
                log.warning("%s: connection lost: %r", self._platform.name, error)
            finally:
                for state in self._books.values():
                    state.invalidate("disconnected")
            delay = 1.0 if self._received else min(delay * 2, MAX_RECONNECT_SECONDS)
            log.info("%s: reconnecting in %.0f s", self._platform.name, delay)
            await asyncio.sleep(delay)

    async def _session(self, ws: ClientConnection) -> None:
        name = self._platform.name
        log.info("%s: connected", name)
        for message in self._platform.subscribe_messages(list(self._books)):
            await ws.send(json.dumps(message))
        log.info("%s: subscribed to %s", name, ", ".join(self._books))
        side_tasks = [asyncio.create_task(self._resync())]
        if self._platform.heartbeat is not None:
            side_tasks.append(asyncio.create_task(self._heartbeat(ws)))
        try:
            async for raw in ws:
                if self._handle(raw):
                    self._received = True
        finally:
            for task in side_tasks:
                task.cancel()

    def _handle(self, raw: str | bytes) -> bool:
        try:
            message = json.loads(raw)
            update = self._platform.parse_book_message(message)
        except SOURCE_ERRORS as error:
            log.warning("%s: unreadable channel message: %r", self._platform.name, error)
            return False
        if update is None:
            if isinstance(message, dict) and ("error" in message or message.get("status") == "err"):
                log.warning("%s: channel error: %s", self._platform.name, message)
            return False
        source_id, book = update
        state = self._books.get(source_id)
        if state is None:
            return False
        state.replace(book)
        return True

    async def _resync(self) -> None:
        for source_id, state in self._books.items():
            try:
                book = await self._platform.book(source_id)
            except SOURCE_ERRORS as error:
                log.warning("%s: resync of %s failed: %r", self._platform.name, source_id, error)
                continue
            # A channel message is newer than the REST answer that crossed it.
            if state.book is None:
                state.replace(book)
            log.info("%s: resync of %s done", self._platform.name, source_id)

    async def _heartbeat(self, ws: ClientConnection) -> None:
        try:
            while True:
                await asyncio.sleep(self._platform.heartbeat_seconds)
                await ws.send(json.dumps(self._platform.heartbeat))
        except WebSocketException:
            return  # the reading loop sees the same closure and reconnects
