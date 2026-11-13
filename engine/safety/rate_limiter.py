from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable


class RateLimitExceeded(Exception):
    pass


@dataclass
class TokenBucket:
    rate_per_second: float
    clock: Callable[[], float]

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            raise ValueError("Rate limits must be positive.")
        self.capacity = self.rate_per_second
        self.tokens = self.capacity
        self.updated_at = self.clock()

    def consume(self) -> bool:
        now = self.clock()
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
        self.updated_at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class RateLimiter:
    def __init__(
        self,
        global_rate_per_second: float = 5.0,
        endpoint_rate_per_second: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._global = TokenBucket(global_rate_per_second, clock)
        self._endpoint_rate = endpoint_rate_per_second
        self._clock = clock
        self._endpoints: dict[str, TokenBucket] = {}
        self._lock = Lock()

    def check(self, endpoint: str) -> None:
        with self._lock:
            endpoint_bucket = self._endpoints.get(endpoint)
            if endpoint_bucket is None:
                endpoint_bucket = TokenBucket(self._endpoint_rate, self._clock)
                self._endpoints[endpoint] = endpoint_bucket
            if not self._global.consume() or not endpoint_bucket.consume():
                raise RateLimitExceeded("Request rate limit exceeded.")
