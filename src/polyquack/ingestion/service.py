import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from polyquack.ingestion.book import BookState, build_snapshot
from polyquack.ingestion.feed import BookFeed
from polyquack.ingestion.models import DELISTED, FundingPayment, PriceQuote
from polyquack.ingestion.platforms import (
    FUNDING_TOLERANCE_MS,
    HISTORY_FLOOR_MS,
    SOURCE_ERRORS,
    Platform,
)
from polyquack.storage.db import Database, Target
from polyquack.times import HOUR_MS, MINUTE_MS, floor_to, iso

log = logging.getLogger(__name__)

INSTRUMENTS_REFRESH_SECONDS = 24 * 3600
INSTRUMENTS_RETRY_START_SECONDS = 5.0
INSTRUMENTS_RETRY_MAX_SECONDS = 300.0
FUNDING_START_AFTER_HOUR_MS = MINUTE_MS
FUNDING_DEADLINE_AFTER_HOUR_MS = 15 * MINUTE_MS
FUNDING_RETRY_SECONDS = 30.0
PRICE_OFFSET_MS = 1_000
RECOVERY_MINUTE_MS = 20 * MINUTE_MS

# Funding gaps can still be recovered from the source's history, so they are born open.
_GAP_STATUS = {"funding": "open", "book_snapshot": "final", "price": "final"}
_STEP_MS = {"funding": HOUR_MS, "book_snapshot": MINUTE_MS, "price": MINUTE_MS}


def _is_lock_contention(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    # Python reports extended codes (e.g. SQLITE_BUSY_TIMEOUT); the primary code is the low byte.
    return code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


class MissingPairError(Exception):
    pass


class TargetsChanged(Exception):
    """The set of pairs to ingest changed; the process restarts to rebuild books and feeds."""


class Service:
    def __init__(
        self,
        db: Database,
        platforms: dict[str, Platform],
        assets: tuple[str, ...],
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.db = db
        self.platforms = platforms
        self.assets = assets
        self.targets: list[Target] = []
        self.books: dict[int, BookState] = {}
        self._now = clock
        self._sleep = sleep
        self._ready = asyncio.Event()
        self._refreshed: set[str] = set()

    async def run(self) -> None:
        self._load_targets()
        try:
            async with asyncio.TaskGroup() as group:
                for name in self.platforms:
                    group.create_task(self._instruments_loop(name))
                group.create_task(self._ingest())
        except* TargetsChanged:
            log.info("stopping so that the service manager restarts with the new targets")

    def _load_targets(self) -> None:
        targets = self.db.targets(self.assets)
        if targets:
            self.targets = targets
            self._ready.set()
            covered = {t.asset for t in targets}
            for asset in self.assets:
                if asset not in covered:
                    log.warning("filter asset %s has no target pair", asset)

    @contextmanager
    def _guarded(self, what: str) -> Iterator[None]:
        """Lock contention past the busy timeout is logged and leaves no row; others propagate."""
        try:
            yield
        except sqlite3.OperationalError as error:
            if not _is_lock_contention(error):
                raise
            log.error("%s: write failed: %r", what, error)

    async def _ingest(self) -> None:
        await self._ready.wait()
        self.books = {t.instrument_id: BookState() for t in self.targets}
        async with asyncio.TaskGroup() as group:
            for name, platform in self.platforms.items():
                books = {
                    t.source_id: self.books[t.instrument_id]
                    for t in self.targets
                    if t.platform == name
                }
                group.create_task(BookFeed(platform, books).run())
                group.create_task(self._funding_loop(name))
                group.create_task(self._history_loop(name))
            group.create_task(self._minute_loop())
            group.create_task(self._price_loop())

    async def refresh_instruments(self, name: str) -> bool:
        started = self._now()
        platform = self.platforms[name]
        try:
            infos = await platform.instruments()
        except SOURCE_ERRORS as error:
            log.warning("%s: instruments request failed: %r", name, error)
            self.db.insert_gap(
                name, None, "instruments", started, self._now(), repr(error), "final"
            )
            return False
        self.db.upsert_instruments(name, infos, started)
        self.db.record_lifecycle(name, infos, started)
        await self._settle_absent(name, {info.source_id for info in infos}, started)
        self.db.pair_instruments(started)
        await self._refresh_fees(name, started)
        log.info("%s: %d instruments stored", name, len(infos))
        return True

    async def _settle_absent(self, name: str, present: set[str], now_ms: int) -> None:
        for instrument_id, source_id in self.db.absent_instruments(name, present):
            try:
                settled = await self.platforms[name].has_settlement(source_id)
            except SOURCE_ERRORS as error:
                log.warning("%s: lookup of absent instrument %s failed: %r", name, source_id, error)
                continue
            if settled:
                self.db.set_status(instrument_id, DELISTED, now_ms)
                log.info("%s: instrument %s settled, now delisted", name, source_id)
            else:
                log.warning(
                    "%s: instrument %s is absent from the list; status unchanged", name, source_id
                )

    async def _refresh_fees(self, name: str, now_ms: int) -> None:
        try:
            rates = await self.platforms[name].fees()
        except SOURCE_ERRORS as error:
            log.warning("%s: fees request failed: %r", name, error)
            return
        self.db.sync_fees(name, rates, now_ms)

    def _check_targets(self) -> None:
        targets = self.db.targets(self.assets)
        if not self._ready.is_set():
            if self._refreshed == set(self.platforms):
                if not targets:
                    raise MissingPairError(f"no pair to ingest (assets filter: {self.assets})")
                self._load_targets()
            return
        if targets != self.targets:
            old = sorted({t.asset for t in self.targets})
            new = sorted({t.asset for t in targets})
            log.warning("target pairs changed from %s to %s; exiting to restart", old, new)
            raise TargetsChanged

    async def _instruments_loop(self, name: str) -> None:
        while True:
            delay = INSTRUMENTS_RETRY_START_SECONDS
            while not await self.refresh_instruments(name):
                await self._sleep(delay)
                delay = min(delay * 2, INSTRUMENTS_RETRY_MAX_SECONDS)
            self._refreshed.add(name)
            self._check_targets()
            await self._sleep(INSTRUMENTS_REFRESH_SECONDS)

    async def _sleep_until(self, target_ms: int) -> None:
        while (remaining := target_ms - self._now()) > 0:
            await self._sleep(remaining / 1000)

    def _pending(self, target: Target, kind: str, start_ms: int) -> bool:
        """Close the intervals missed before `start_ms` as gaps; True if `start_ms` is still open.

        Covers a stopped service and a stalled loop the same way: every elapsed interval ends
        with exactly one reading or one gap.
        """
        step = _STEP_MS[kind]
        covered = self.db.covered_until_ms(target.instrument_id, kind)
        if covered is None:
            return True
        missed = [(m, m + step) for m in range(covered, start_ms, step)]
        if missed:
            self.db.insert_gaps(
                target.platform,
                target.instrument_id,
                kind,
                missed,
                "not_collected",
                _GAP_STATUS[kind],
            )
        return covered <= start_ms

    def close_minute(self, minute_ms: int) -> None:
        for target in self.targets:
            with self._guarded(f"{target.platform} {target.asset} snapshot"):
                self._close_target_minute(target, minute_ms)

    def _close_target_minute(self, target: Target, minute_ms: int) -> None:
        if not self._pending(target, "book_snapshot", minute_ms):
            return
        state = self.books[target.instrument_id]
        snapshot = build_snapshot(state.book) if state.book else None
        if snapshot is not None:
            self.db.insert_snapshot(target.instrument_id, minute_ms, snapshot)
            return
        cause = state.invalid_cause if state.book is None else "empty_book"
        self.db.insert_gap(
            target.platform,
            target.instrument_id,
            "book_snapshot",
            minute_ms,
            minute_ms + MINUTE_MS,
            cause,
            _GAP_STATUS["book_snapshot"],
        )
        log.info(
            "%s %s: snapshot gap %s (%s)", target.platform, target.asset, iso(minute_ms), cause
        )

    async def _minute_loop(self) -> None:
        while True:
            boundary = floor_to(self._now(), MINUTE_MS) + MINUTE_MS
            await self._sleep_until(boundary)
            self.close_minute(boundary - MINUTE_MS)

    async def collect_prices(self, minute_ms: int) -> None:
        await asyncio.gather(*(self._collect_prices(name, minute_ms) for name in self.platforms))

    async def _collect_prices(self, name: str, minute_ms: int) -> None:
        targets = [t for t in self.targets if t.platform == name]
        quotes: dict[str, PriceQuote] = {}
        cause = ""
        try:
            quotes = await self.platforms[name].prices()
        except SOURCE_ERRORS as error:
            cause = repr(error)
        received_ms = self._now()
        if not cause and received_ms >= minute_ms + MINUTE_MS:
            cause = "late"
        stored = 0
        for target in targets:
            with self._guarded(f"{name} {target.asset} price"):
                if not self._pending(target, "price", minute_ms):
                    continue
                quote = quotes.get(target.source_id)
                if quote is not None and not cause:
                    self.db.insert_price(
                        target.instrument_id,
                        minute_ms,
                        quote.mark_price,
                        quote.index_price,
                        quote.source_time_ms,
                        received_ms,
                    )
                    stored += 1
                else:
                    self.db.insert_gap(
                        name,
                        target.instrument_id,
                        "price",
                        minute_ms,
                        minute_ms + MINUTE_MS,
                        cause or "missing_in_response",
                        _GAP_STATUS["price"],
                    )
        log.info(
            "%s: price request for %s: %d stored%s",
            name,
            iso(minute_ms),
            stored,
            f", gap ({cause})" if cause else "",
        )

    async def _price_loop(self) -> None:
        while True:
            minute = floor_to(self._now(), MINUTE_MS) + MINUTE_MS
            await self._sleep_until(minute + PRICE_OFFSET_MS)
            await self.collect_prices(minute)

    async def collect_funding(self, name: str, hour_ms: int) -> None:
        """Fetch the payment of `hour_ms` for every target of the platform, or leave an open gap."""
        await self._sleep_until(hour_ms + FUNDING_START_AFTER_HOUR_MS)
        deadline = hour_ms + FUNDING_DEADLINE_AFTER_HOUR_MS
        platform = self.platforms[name]
        pending = []
        for target in self.targets:
            if target.platform != name:
                continue
            with self._guarded(f"{name} {target.asset} funding gaps"):
                if self._pending(target, "funding", hour_ms):
                    pending.append(target)
        causes: dict[int, str] = {}
        while pending:
            for target in list(pending):
                try:
                    payment = await platform.funding(target.source_id, hour_ms)
                except SOURCE_ERRORS as error:
                    causes[target.instrument_id] = repr(error)
                    continue
                if payment is None:
                    causes[target.instrument_id] = "no_payment_at_source"
                    continue
                with self._guarded(f"{name} {target.asset} funding"):
                    self.db.insert_funding(
                        target.instrument_id, payment.source_time_ms, payment.rate, self._now()
                    )
                    log.info("%s %s: funding of %s stored", name, target.asset, iso(hour_ms))
                    pending.remove(target)
            if not pending or self._now() >= deadline:
                break
            await self._sleep(FUNDING_RETRY_SECONDS)
        for target in pending:
            with self._guarded(f"{name} {target.asset} funding gap"):
                self.db.insert_gap(
                    name,
                    target.instrument_id,
                    "funding",
                    hour_ms,
                    hour_ms + HOUR_MS,
                    causes.get(target.instrument_id, "write_failed"),
                    _GAP_STATUS["funding"],
                )
                log.warning("%s %s: funding gap %s", name, target.asset, iso(hour_ms))

    async def _funding_loop(self, name: str) -> None:
        hour = floor_to(self._now(), HOUR_MS)
        while True:
            await self.collect_funding(name, hour)
            hour += HOUR_MS

    async def backfill_funding(self, name: str) -> None:
        """Fetch the history before the earliest stored hour of every target of the platform."""
        for target in self.targets:
            if target.platform != name:
                continue
            earliest = self.db.earliest_funding_ms(target.instrument_id)
            if earliest is not None and earliest <= HISTORY_FLOOR_MS:
                continue
            end = self._now() if earliest is None else earliest
            fetched = await self._fetch_history(target, HISTORY_FLOOR_MS, end)
            if fetched is not None:
                log.info("%s %s: %d historical payments read", name, target.asset, len(fetched))

    async def recover_funding(self, name: str) -> None:
        """Close the open funding gaps of every target of the platform from its history."""
        for target in self.targets:
            if target.platform != name:
                continue
            oldest = self.db.oldest_open_funding_gap_ms(target.instrument_id)
            if oldest is None:
                continue
            fetched = await self._fetch_history(target, oldest - FUNDING_TOLERANCE_MS, self._now())
            if fetched is None:
                continue
            newest = max((p.source_time_ms for p in fetched), default=None)
            with self._guarded(f"{name} {target.asset} gap recovery"):
                settled = self.db.close_funding_gaps(target.instrument_id, newest, self._now())
                log.info("%s %s: %d funding gap(s) settled", name, target.asset, settled)

    async def _fetch_history(
        self, target: Target, start_ms: int, end_ms: int
    ) -> list[FundingPayment] | None:
        fetched: list[FundingPayment] = []
        try:
            async for page in self.platforms[target.platform].funding_history(
                target.source_id, start_ms, end_ms
            ):
                self.db.insert_funding_history(target.instrument_id, page, self._now())
                fetched += page
        except SOURCE_ERRORS as error:
            log.warning("%s %s: funding history failed: %r", target.platform, target.asset, error)
            return None
        except sqlite3.OperationalError as error:
            if not _is_lock_contention(error):
                raise
            log.error("%s %s: history write failed: %r", target.platform, target.asset, error)
            return None
        return fetched

    async def _history_loop(self, name: str) -> None:
        await self.backfill_funding(name)
        await self.recover_funding(name)
        while True:
            now = self._now()
            await self._sleep_until(
                floor_to(now - RECOVERY_MINUTE_MS, HOUR_MS) + HOUR_MS + RECOVERY_MINUTE_MS
            )
            await self.recover_funding(name)
