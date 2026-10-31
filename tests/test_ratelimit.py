import asyncio

import httpx
import pytest

from polyquack.ingestion.platforms import PolymarketPerps, RestError
from polyquack.ingestion.ratelimit import RateLimiter


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _limiter(clock: _Clock, min_interval: float = 0.8) -> RateLimiter:
    return RateLimiter(min_interval, clock=clock, sleep=clock.sleep)


def test_requests_are_spaced_by_the_minimum_interval() -> None:
    clock = _Clock()
    limiter = _limiter(clock)

    async def run() -> None:
        await limiter.wait()
        await limiter.wait()

    asyncio.run(run())

    assert clock.slept == [pytest.approx(0.8)]


def test_retry_after_is_respected() -> None:
    clock = _Clock()
    limiter = _limiter(clock)

    async def run() -> None:
        await limiter.wait()
        limiter.throttled(7.0)
        await limiter.wait()

    asyncio.run(run())

    assert clock.slept == [pytest.approx(7.0)]


def test_retry_after_below_the_minimum_interval_does_not_speed_up_the_pace() -> None:
    clock = _Clock()
    limiter = _limiter(clock)

    async def run() -> None:
        await limiter.wait()
        limiter.throttled(0.1)
        await limiter.wait()

    asyncio.run(run())

    assert clock.slept == [pytest.approx(0.8)]


def test_without_retry_after_the_wait_grows_exponentially_and_resets_on_success() -> None:
    clock = _Clock()
    limiter = _limiter(clock)

    async def run() -> None:
        await limiter.wait()
        for _ in range(3):
            limiter.throttled(None)
            await limiter.wait()
        limiter.succeeded()
        limiter.throttled(None)
        await limiter.wait()

    asyncio.run(run())

    assert clock.slept == [
        pytest.approx(1.6),
        pytest.approx(3.2),
        pytest.approx(6.4),
        pytest.approx(1.6),
    ]


@pytest.mark.parametrize("headers", [{"Retry-After": "7"}, {}])
def test_a_429_response_throttles_the_platform_and_fails_the_request(
    headers: dict[str, str],
) -> None:
    clock = _Clock()
    limiter = _limiter(clock)
    transport = httpx.MockTransport(lambda request: httpx.Response(429, headers=headers))
    platform = PolymarketPerps(httpx.AsyncClient(transport=transport), limiter)

    async def run() -> None:
        with pytest.raises(RestError, match="429"):
            await platform.prices()
        await limiter.wait()

    asyncio.run(run())

    expected = 7.0 if headers else 1.6
    assert clock.slept == [pytest.approx(expected)]


def test_ip_rate_limited_body_counts_as_throttling() -> None:
    clock = _Clock()
    limiter = _limiter(clock)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "err", "error": "ip_rate_limited"})
    )
    platform = PolymarketPerps(httpx.AsyncClient(transport=transport), limiter)

    async def run() -> None:
        with pytest.raises(RestError, match="429"):
            await platform.prices()

    asyncio.run(run())
