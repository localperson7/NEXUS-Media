import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request

from app.config import settings


class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter per client IP."""

    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, client_key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[client_key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Слишком много запросов. Пожалуйста, подождите минуту перед следующей попыткой.",
                },
            )
        bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.rate_limit_per_minute,
    window_seconds=60,
)


async def enforce_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "local"
    rate_limiter.check(client_ip)
