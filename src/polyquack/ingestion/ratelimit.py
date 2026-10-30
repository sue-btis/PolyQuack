import asyncio
import time
from collections.abc import Awaitable, Callable

MAX_BACKOFF_SECONDS = 60.0


class RateLimiter:
    """One pace for every REST request to a platform.

    Requests are at least `min_interval` apart; after a throttling response the next one is
    pushed back by `Retry-After` when given, otherwise by an exponentially growing wait.
    """

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_allowed = 0.0
        self._backoff = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delay = self._next_allowed - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next_allowed = self._clock() + self.min_interval

    def throttled(self, retry_after: float | None) -> None:
        if retry_after is not None:
            wait = retry_after
        else:
            self._backoff = min(MAX_BACKOFF_SECONDS, max(self._backoff * 2, self.min_interval * 2))
            wait = self._backoff
        self._next_allowed = max(self._next_allowed, self._clock() + max(wait, self.min_interval))

    def succeeded(self) -> None:
        self._backoff = 0.0
