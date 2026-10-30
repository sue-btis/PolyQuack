from abc import ABC, abstractmethod
from typing import Any

import httpx

from polyquack.ingestion.models import (
    BookLevels,
    FundingPayment,
    InstrumentInfo,
    Levels,
    PriceQuote,
)
from polyquack.ingestion.ratelimit import RateLimiter
from polyquack.times import MINUTE_MS

POLYMARKET = "polymarket_perps"
HYPERLIQUID = "hyperliquid"

# Funding is stamped a few milliseconds after the top of the hour; a minute either way is
# accepted and anything farther away is not that hour's payment.
FUNDING_TOLERANCE_MS = MINUTE_MS


class RestError(Exception):
    pass


# A response that parses badly means the source changed shape; it is a gap, not a crash.
SOURCE_ERRORS = (RestError, KeyError, ValueError, TypeError, IndexError)


class Platform(ABC):
    name: str
    ws_url: str
    heartbeat: dict[str, str] | None = None
    heartbeat_seconds = 30.0

    def __init__(self, http: httpx.AsyncClient, limiter: RateLimiter) -> None:
        self._http = http
        self._limiter = limiter

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        await self._limiter.wait()
        try:
            response = await self._http.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise RestError(type(error).__name__) from error
        throttled = response.status_code == 429 or "ip_rate_limited" in response.text
        if throttled:
            self._limiter.throttled(_retry_after(response))
            raise RestError("429")
        if response.status_code >= 400:
            raise RestError(f"HTTP {response.status_code}")
        self._limiter.succeeded()
        try:
            return response.json()
        except ValueError as error:
            raise RestError("invalid JSON") from error

    @abstractmethod
    async def instruments(self) -> list[InstrumentInfo]: ...

    @abstractmethod
    async def funding(self, source_id: str, hour_ms: int) -> FundingPayment | None:
        """The payment stamped at `hour_ms`, or None if the source does not have it yet."""

    @abstractmethod
    async def prices(self) -> dict[str, PriceQuote]: ...

    @abstractmethod
    async def book(self, source_id: str) -> BookLevels: ...

    @abstractmethod
    def subscribe_messages(self, source_ids: list[str]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def parse_book_message(self, message: Any) -> tuple[str, BookLevels] | None: ...


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def _payment_at(rows: list[FundingPayment], hour_ms: int) -> FundingPayment | None:
    near = [row for row in rows if abs(row.source_time_ms - hour_ms) <= FUNDING_TOLERANCE_MS]
    return min(near, key=lambda row: abs(row.source_time_ms - hour_ms)) if near else None


class PolymarketPerps(Platform):
    name = POLYMARKET
    ws_url = "wss://ws.perpetuals.polymarket.com/v1/ws"
    base_url = "https://api.perpetuals.polymarket.com"
    channel_depth = 50
    # REST accepts only depths 10, 100, 500, 1000; the channel depth is cut from the 100.
    rest_depth = 100

    async def instruments(self) -> list[InstrumentInfo]:
        rows = await self._request("GET", f"{self.base_url}/v1/info/instruments")
        return [
            InstrumentInfo(str(row["instrument_id"]), row["symbol"], row["base_asset"])
            for row in rows
        ]

    async def funding(self, source_id: str, hour_ms: int) -> FundingPayment | None:
        payload = await self._request(
            "GET",
            f"{self.base_url}/v1/info/funding",
            params={
                "instrument_id": source_id,
                "start_timestamp": hour_ms - FUNDING_TOLERANCE_MS,
                "end_timestamp": hour_ms + FUNDING_TOLERANCE_MS,
            },
        )
        rows = [
            FundingPayment(int(r["timestamp"]), float(r["funding_rate"])) for r in payload["data"]
        ]
        return _payment_at(rows, hour_ms)

    async def prices(self) -> dict[str, PriceQuote]:
        rows = await self._request("GET", f"{self.base_url}/v1/info/tickers")
        return {
            str(row["instrument_id"]): PriceQuote(
                float(row["mark_price"]), float(row["index_price"]), int(row["timestamp"])
            )
            for row in rows
        }

    async def book(self, source_id: str) -> BookLevels:
        payload = await self._request(
            "GET",
            f"{self.base_url}/v1/info/book",
            params={"instrument_id": source_id, "depth": self.rest_depth},
        )
        data = payload.get("data", payload)
        return BookLevels(
            _levels(data["bids"][: self.channel_depth]),
            _levels(data["asks"][: self.channel_depth]),
            int(data["timestamp"]),
        )

    def subscribe_messages(self, source_ids: list[str]) -> list[dict[str, Any]]:
        channels = [f"book::{sid}::{self.channel_depth}" for sid in source_ids]
        return [{"id": 1, "req": "sub", "chs": channels}]

    def parse_book_message(self, message: Any) -> tuple[str, BookLevels] | None:
        channel = message.get("ch", "") if isinstance(message, dict) else ""
        if not channel.startswith("book::"):
            return None
        data = message["data"]
        return channel.split("::")[1], BookLevels(
            _levels(data["b"]), _levels(data["a"]), int(message["ts"])
        )


class Hyperliquid(Platform):
    name = HYPERLIQUID
    ws_url = "wss://api.hyperliquid.xyz/ws"
    info_url = "https://api.hyperliquid.xyz/info"
    heartbeat = {"method": "ping"}

    async def instruments(self) -> list[InstrumentInfo]:
        meta = await self._request("POST", self.info_url, json={"type": "meta"})
        return [
            InstrumentInfo(row["name"], row["name"], row["name"])
            for row in meta["universe"]
            if not row.get("isDelisted")
        ]

    async def funding(self, source_id: str, hour_ms: int) -> FundingPayment | None:
        rows = await self._request(
            "POST",
            self.info_url,
            json={
                "type": "fundingHistory",
                "coin": source_id,
                "startTime": hour_ms - FUNDING_TOLERANCE_MS,
                "endTime": hour_ms + FUNDING_TOLERANCE_MS,
            },
        )
        return _payment_at(
            [FundingPayment(int(r["time"]), float(r["fundingRate"])) for r in rows], hour_ms
        )

    async def prices(self) -> dict[str, PriceQuote]:
        meta, contexts = await self._request(
            "POST", self.info_url, json={"type": "metaAndAssetCtxs"}
        )
        return {
            asset["name"]: PriceQuote(float(ctx["markPx"]), float(ctx["oraclePx"]), None)
            for asset, ctx in zip(meta["universe"], contexts, strict=True)
        }

    async def book(self, source_id: str) -> BookLevels:
        data = await self._request(
            "POST", self.info_url, json={"type": "l2Book", "coin": source_id}
        )
        return _hyperliquid_book(data)

    def subscribe_messages(self, source_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}}
            for coin in source_ids
        ]

    def parse_book_message(self, message: Any) -> tuple[str, BookLevels] | None:
        if not isinstance(message, dict) or message.get("channel") != "l2Book":
            return None
        data = message["data"]
        return data["coin"], _hyperliquid_book(data)


def _levels(raw: list[list[str]]) -> Levels:
    return [(float(price), float(quantity)) for price, quantity in raw]


def _hyperliquid_book(data: dict[str, Any]) -> BookLevels:
    bids, asks = data["levels"]
    return BookLevels(
        [(float(lv["px"]), float(lv["sz"])) for lv in bids],
        [(float(lv["px"]), float(lv["sz"])) for lv in asks],
        int(data["time"]),
    )
