import asyncio
import json
from collections import defaultdict
from typing import Any

import httpx

from polyquack.ingestion.platforms import (
    HYPERLIQUID,
    POLYMARKET,
    Hyperliquid,
    Platform,
    PolymarketPerps,
)
from polyquack.ingestion.ratelimit import RateLimiter

PM_PAGE = 100
HL_PAGE = 500


async def _no_sleep(_: float) -> None:
    return None


def pm_row(
    instrument_id: int, asset: str, close_only: bool = False, max_leverage: int = 50
) -> dict[str, Any]:
    return {
        "instrument_id": instrument_id,
        "symbol": f"{asset}-USD",
        "base_asset": asset,
        "close_only": close_only,
        "max_leverage": max_leverage,
        "min_notional": "10",
        "liquidation_fee": "0.005",
    }


def hl_row(asset: str, delisted: bool = False, max_leverage: int = 40) -> dict[str, Any]:
    row: dict[str, Any] = {
        "szDecimals": 1,
        "name": asset,
        "maxLeverage": max_leverage,
        "marginTableId": max_leverage,
    }
    if delisted:
        row["isDelisted"] = True
    return row


class FakeExchange:
    """Both platforms' public endpoints, served from mutable state over a mock transport."""

    def __init__(self) -> None:
        self.pm_rows: dict[int, dict[str, Any]] = {}
        self.hl_rows: list[dict[str, Any]] = []
        self.settled: set[int] = set()
        self.lookup_returns_row_without_settlement = False
        self.pm_fees: list[dict[str, Any]] = []
        self.pm_funding: dict[str, list[tuple[int, str]]] = {}
        self.hl_funding: dict[str, list[tuple[int, str]]] = {}
        self.fail_history = False
        self.requests: list[tuple[str, str]] = []
        self.in_flight: dict[str, int] = defaultdict(int)
        self.max_in_flight: dict[str, int] = defaultdict(int)

    def platforms(self) -> dict[str, Platform]:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))
        return {
            POLYMARKET: PolymarketPerps(http, RateLimiter(0.8, sleep=_no_sleep)),
            HYPERLIQUID: Hyperliquid(http, RateLimiter(0.8, sleep=_no_sleep)),
        }

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.in_flight[host] += 1
        self.max_in_flight[host] = max(self.max_in_flight[host], self.in_flight[host])
        try:
            await asyncio.sleep(0)
            return self._respond(request)
        finally:
            self.in_flight[host] -= 1

    def _respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hyperliquid.xyz":
            return self._respond_hyperliquid(json.loads(request.content))
        path = request.url.path
        params = dict(request.url.params)
        self.requests.append((POLYMARKET, path))
        if path == "/v1/info/instruments":
            if "instrument_id" in params:
                instrument_id = int(params["instrument_id"])
                if instrument_id in self.settled:
                    return httpx.Response(200, json=[{"settlement": {"price": "1"}}])
                if self.lookup_returns_row_without_settlement:
                    return httpx.Response(200, json=[{"instrument_id": instrument_id}])
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=list(self.pm_rows.values()))
        if path == "/v1/info/fees":
            return httpx.Response(200, json={"fee_schedule": self.pm_fees})
        if path == "/v1/info/funding":
            if self.fail_history:
                return httpx.Response(500)
            start, end = int(params["start_timestamp"]), int(params["end_timestamp"])
            rows = sorted(
                (
                    r
                    for r in self.pm_funding.get(params["instrument_id"], [])
                    if start <= r[0] <= end
                ),
                reverse=True,
            )
            data = [{"funding_rate": rate, "timestamp": ts} for ts, rate in rows[:PM_PAGE]]
            return httpx.Response(200, json={"data": data, "more": len(rows) > PM_PAGE})
        raise AssertionError(f"unexpected request {path}")

    def _respond_hyperliquid(self, body: dict[str, Any]) -> httpx.Response:
        self.requests.append((HYPERLIQUID, body["type"]))
        if body["type"] == "meta":
            return httpx.Response(200, json={"universe": self.hl_rows, "marginTables": []})
        if body["type"] == "fundingHistory":
            if self.fail_history:
                return httpx.Response(500)
            start, end = body["startTime"], body["endTime"]
            rows = sorted(r for r in self.hl_funding.get(body["coin"], []) if start <= r[0] <= end)
            data = [
                {"coin": body["coin"], "fundingRate": rate, "premium": "0", "time": ts}
                for ts, rate in rows[:HL_PAGE]
            ]
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected request {body}")
