import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from polyquack.ingestion.models import FundingPayment, InstrumentInfo
from polyquack.ingestion.platforms import HYPERLIQUID, POLYMARKET, Platform
from polyquack.storage.db import Database
from polyquack.times import HOUR_MS

from .conftest import T0, platforms_over

FIXTURES = Path(__file__).parent / "fixtures"
# The funding fixtures hold the payments of four consecutive hours; this one is the last.
PAYMENT_HOUR = 1_793_224_800_000


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def serve_fixture(name: str, requests: list[httpx.Request]) -> Platform:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=fixture(name))

    platforms = platforms_over(handler)
    return platforms[POLYMARKET if name.startswith("pm_") else HYPERLIQUID]


def test_polymarket_instruments_are_read_from_the_real_list() -> None:
    platform = serve_fixture("pm_instruments.json", [])

    infos = asyncio.run(platform.instruments())

    assert infos == [
        InstrumentInfo("1", "SP500-USD", "SP500", "active", 50.0, 0.01, 10.0, 0.005),
        InstrumentInfo("6", "BTC-USD", "BTC", "active", 50.0, 0.01, 10.0, 0.005),
        InstrumentInfo("7", "ETH-USD", "ETH", "active", 50.0, 0.01, 10.0, 0.005),
    ]


def test_hyperliquid_instruments_keep_delisted_coins_with_their_status() -> None:
    platform = serve_fixture("hl_meta.json", [])

    infos = asyncio.run(platform.instruments())

    assert [(i.asset, i.status) for i in infos] == [
        ("BTC", "active"),
        ("ETH", "active"),
        ("MATIC", "delisted"),
        ("kPEPE", "active"),
        ("RNDR", "delisted"),
        ("FTM", "delisted"),
    ]


def test_hyperliquid_base_tier_parameters_come_from_the_margin_table() -> None:
    platform = serve_fixture("hl_meta.json", [])

    by_asset = {i.asset: i for i in asyncio.run(platform.instruments())}

    assert by_asset["BTC"].max_leverage == 40.0
    assert by_asset["BTC"].maintenance_margin == 0.5 / 40
    assert by_asset["BTC"].min_notional == 10.0
    assert by_asset["BTC"].liquidation_fee is None
    # Delisted coins have no listed table: the table id is their single tier's leverage.
    assert by_asset["FTM"].max_leverage == 10.0


def test_pairing_the_real_lists_pairs_by_asset_and_does_not_duplicate_on_repeat(
    db: Database,
) -> None:
    pm = serve_fixture("pm_instruments.json", [])
    hl = serve_fixture("hl_meta.json", [])
    pm_infos = asyncio.run(pm.instruments())
    hl_infos = asyncio.run(hl.instruments())

    for _ in range(2):
        db.upsert_instruments(POLYMARKET, pm_infos, T0)
        db.upsert_instruments(HYPERLIQUID, hl_infos, T0)
        db.record_lifecycle(POLYMARKET, pm_infos, T0)
        db.record_lifecycle(HYPERLIQUID, hl_infos, T0)
        db.pair_instruments(T0)

    paired = db.conn.execute(
        "SELECT a.symbol FROM pair JOIN asset a ON a.id = pair.asset_id ORDER BY a.symbol"
    ).fetchall()
    assert paired == [("BTC",), ("ETH",)]
    assert db.unpaired_instruments() == [(POLYMARKET, "SP500-USD"), (HYPERLIQUID, "kPEPE")]
    assert db.conn.execute("SELECT count(*) FROM instrument").fetchone()[0] == 9


def test_polymarket_funding_reads_the_payment_of_the_requested_hour() -> None:
    requests: list[httpx.Request] = []
    platform = serve_fixture("pm_funding.json", requests)

    payment = asyncio.run(platform.funding("6", PAYMENT_HOUR))

    assert payment == FundingPayment(1_793_224_800_024, 0.0000125)
    params = dict(requests[0].url.params)
    assert params == {
        "instrument_id": "6",
        "start_timestamp": str(PAYMENT_HOUR - 60_000),
        "end_timestamp": str(PAYMENT_HOUR + 60_000),
    }


def test_polymarket_funding_ignores_payments_of_other_hours() -> None:
    platform = serve_fixture("pm_funding.json", [])

    assert asyncio.run(platform.funding("6", PAYMENT_HOUR + 2 * HOUR_MS)) is None


def test_polymarket_funding_takes_the_payment_closest_to_the_hour() -> None:
    rows = {
        "data": [
            {"funding_rate": "0.1", "timestamp": PAYMENT_HOUR + 30_000},
            {"funding_rate": "0.2", "timestamp": PAYMENT_HOUR + 10_000},
        ],
        "more": False,
    }
    platform = platforms_over(lambda request: httpx.Response(200, json=rows))[POLYMARKET]

    assert asyncio.run(platform.funding("6", PAYMENT_HOUR)) == FundingPayment(
        PAYMENT_HOUR + 10_000, 0.2
    )


def test_hyperliquid_funding_reads_the_payment_of_the_requested_hour() -> None:
    requests: list[httpx.Request] = []
    platform = serve_fixture("hl_funding.json", requests)

    payment = asyncio.run(platform.funding("BTC", PAYMENT_HOUR))

    assert payment == FundingPayment(1_793_224_800_025, 0.0000125)
    assert json.loads(requests[0].content) == {
        "type": "fundingHistory",
        "coin": "BTC",
        "startTime": PAYMENT_HOUR - 60_000,
        "endTime": PAYMENT_HOUR + 60_000,
    }
    assert asyncio.run(platform.funding("BTC", PAYMENT_HOUR + 2 * HOUR_MS)) is None


def test_polymarket_rest_book_asks_for_depth_100_and_keeps_the_channel_depth() -> None:
    requests: list[httpx.Request] = []
    platform = serve_fixture("pm_book_depth100.json", requests)

    book = asyncio.run(platform.book("6"))

    assert dict(requests[0].url.params) == {"instrument_id": "6", "depth": "100"}
    raw = fixture("pm_book_depth100.json")
    assert len(raw["bids"]) == len(raw["asks"]) == 100
    assert len(book.bids) == len(book.asks) == 50
    assert book.bids[0] == (float(raw["bids"][0][0]), float(raw["bids"][0][1]))
    assert book.bids[-1][0] == float(raw["bids"][49][0])
    assert book.asks[-1][0] == float(raw["asks"][49][0])
    assert book.source_time_ms == raw["timestamp"]


def test_hyperliquid_rest_book_reads_bids_then_asks() -> None:
    requests: list[httpx.Request] = []
    platform = serve_fixture("hl_book.json", requests)

    book = asyncio.run(platform.book("BTC"))

    assert json.loads(requests[0].content) == {"type": "l2Book", "coin": "BTC"}
    raw = fixture("hl_book.json")
    assert len(book.bids) == len(book.asks) == 20
    assert book.bids[0][0] < book.asks[0][0]
    assert book.bids[0] == (float(raw["levels"][0][0]["px"]), float(raw["levels"][0][0]["sz"]))
    assert book.asks[0] == (float(raw["levels"][1][0]["px"]), float(raw["levels"][1][0]["sz"]))
    assert book.source_time_ms == raw["time"]
