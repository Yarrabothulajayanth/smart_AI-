from collections import deque
import threading
import time

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            for existing_key, events in list(self._events.items()):
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    del self._events[existing_key]

            events = self._events.setdefault(key, deque())
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)


_limiter = SlidingWindowRateLimiter()


def _client_key(request: Request, scope: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{scope}:{client_host}"


def limit_business_api(request: Request) -> None:
    _limiter.check(_client_key(request, "business"), 600, 60)


def limit_assistant_chat(request: Request) -> None:
    _limiter.check(_client_key(request, "assistant-chat"), 60, 60)


def limit_document_ingestion(request: Request) -> None:
    _limiter.check(_client_key(request, "assistant-document"), 5, 60 * 60)
