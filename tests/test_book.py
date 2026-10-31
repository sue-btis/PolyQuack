import asyncio
import json
from typing import Any

import pytest

from polyquack.ingestion.book import DEPTH_FRACTION, BookState, build_snapshot
from polyquack.ingestion.feed import BookFeed
from polyquack.ingestion.models import BookLevels, FundingPayment, InstrumentInfo, PriceQuote
from polyquack.ingestion.platforms import Hyperliquid, Platform, PolymarketPerps


def test_snapshot_keeps_levels_within_half_percent_of_mid() -> None:
    book = BookLevels(
        bids=[(99.9, 1.0), (99.6, 2.0), (99.0, 5.0)],
        asks=[(100.1, 1.0), (100.4, 3.0), (101.0, 5.0)],
        source_time_ms=1_000,
    )

    snapshot = build_snapshot(book)

    assert snapshot is not None
    assert (snapshot.best_bid, snapshot.best_ask) == (99.9, 100.1)
    assert json.loads(snapshot.bid_levels) == [[99.9, 1.0], [99.6, 2.0]]
    assert json.loads(snapshot.ask_levels) == [[100.1, 1.0], [100.4, 3.0]]
    assert snapshot.bid_notional_05 == pytest.approx(99.9 + 99.6 * 2)
    assert snapshot.ask_notional_05 == pytest.approx(100.1 + 100.4 * 3)
    assert snapshot.bid_reach == pytest.approx(0.01)
    assert snapshot.ask_reach == pytest.approx(0.01)
    assert snapshot.source_time_ms == 1_000


def test_levels_exactly_at_half_percent_of_the_mid_are_included() -> None:
    bid_edge = 100.0 * (1 - DEPTH_FRACTION)
    ask_edge = 100.0 * (1 + DEPTH_FRACTION)
    book = BookLevels(
        bids=[(99.9, 1.0), (bid_edge, 1.0), (bid_edge - 0.01, 1.0)],
        asks=[(100.1, 1.0), (ask_edge, 1.0), (ask_edge + 0.01, 1.0)],
        source_time_ms=1,
    )

    snapshot = build_snapshot(book)

    assert snapshot is not None
    assert json.loads(snapshot.bid_levels) == [[99.9, 1.0], [bid_edge, 1.0]]
    assert json.loads(snapshot.ask_levels) == [[100.1, 1.0], [ask_edge, 1.0]]


def test_snapshot_marks_truncated_reach_when_platform_levels_stop_short() -> None:
    book = BookLevels(
        bids=[(99.99, 1.0), (99.98, 2.0)], asks=[(100.01, 1.0), (100.02, 3.0)], source_time_ms=1
    )

    snapshot = build_snapshot(book)

    assert snapshot is not None
    assert snapshot.bid_reach == pytest.approx(0.0002)
    assert snapshot.ask_reach == pytest.approx(0.0002)
    assert json.loads(snapshot.bid_levels) == [[99.99, 1.0], [99.98, 2.0]]
    assert snapshot.bid_notional_05 == pytest.approx(99.99 + 99.98 * 2)


def test_snapshot_of_a_book_with_an_empty_side_is_none() -> None:
    assert build_snapshot(BookLevels([], [(100.0, 1.0)], 1)) is None


def test_full_book_replaces_the_previous_state() -> None:
    state = BookState()
    state.replace(BookLevels([(1.0, 1.0)], [(2.0, 1.0)], 1))
    state.replace(BookLevels([(3.0, 1.0)], [(4.0, 1.0)], 2))

    assert state.book is not None
    assert state.book.bids == [(3.0, 1.0)]


class _StubPlatform(Platform):
    name = "stub"
    ws_url = "wss://stub"

    def __init__(self, rest_book: BookLevels) -> None:
        self._rest_book = rest_book

    async def instruments(self) -> list[InstrumentInfo]:
        return []

    async def funding(self, source_id: str, hour_ms: int) -> FundingPayment | None:
        return None

    async def prices(self) -> dict[str, PriceQuote]:
        return {}

    async def book(self, source_id: str) -> BookLevels:
        return self._rest_book

    def subscribe_messages(self, source_ids: list[str]) -> list[dict[str, Any]]:
        return []

    def parse_book_message(self, message: Any) -> tuple[str, BookLevels] | None:
        return None


def test_book_is_invalid_after_reconnection_until_resync_or_first_message() -> None:
    state = BookState()
    state.replace(BookLevels([(1.0, 1.0)], [(2.0, 1.0)], 1))
    state.invalidate("disconnected")
    assert state.book is None
    assert state.invalid_cause == "disconnected"

    rest = BookLevels([(5.0, 1.0)], [(6.0, 1.0)], 9)
    feed = BookFeed(_StubPlatform(rest), {"X": state})
    asyncio.run(feed._resync())

    assert state.book == rest


def test_resync_does_not_overwrite_a_newer_channel_message() -> None:
    state = BookState()
    channel = BookLevels([(1.0, 1.0)], [(2.0, 1.0)], 10)
    state.replace(channel)

    feed = BookFeed(_StubPlatform(BookLevels([(5.0, 1.0)], [(6.0, 1.0)], 9)), {"X": state})
    asyncio.run(feed._resync())

    assert state.book == channel


def test_polymarket_channel_message_is_a_full_book() -> None:
    message = {
        "ch": "book::6::50",
        "ts": 1767225600000,
        "ets": 1767225600000,
        "sq": 1234567890,
        "data": {"b": [["81008.0", "0.5"]], "a": [["81009.0", "0.25"]]},
    }

    parsed = PolymarketPerps.parse_book_message(PolymarketPerps.__new__(PolymarketPerps), message)

    assert parsed == ("6", BookLevels([(81008.0, 0.5)], [(81009.0, 0.25)], 1767225600000))


def test_hyperliquid_channel_message_is_a_full_book() -> None:
    message = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1793223365393,
            "levels": [
                [{"px": "81008.0", "sz": "0.5", "n": 3}],
                [{"px": "81009.0", "sz": "0.25", "n": 1}],
            ],
        },
    }

    parsed = Hyperliquid.parse_book_message(Hyperliquid.__new__(Hyperliquid), message)

    assert parsed == ("BTC", BookLevels([(81008.0, 0.5)], [(81009.0, 0.25)], 1793223365393))


def test_non_book_messages_are_ignored() -> None:
    hl = Hyperliquid.__new__(Hyperliquid)
    pm = PolymarketPerps.__new__(PolymarketPerps)

    assert hl.parse_book_message({"channel": "pong"}) is None
    assert hl.parse_book_message({"channel": "subscriptionResponse", "data": {}}) is None
    assert pm.parse_book_message({"id": 1, "data": [{"status": "ok"}]}) is None
