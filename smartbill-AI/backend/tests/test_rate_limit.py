import unittest

from fastapi import HTTPException

from app.rate_limit import SlidingWindowRateLimiter


class SlidingWindowRateLimiterTest(unittest.TestCase):
    def test_limit_is_scoped_and_exposes_retry_after(self) -> None:
        limiter = SlidingWindowRateLimiter()
        limiter.check("owner-a", limit=2, window_seconds=60)
        limiter.check("owner-a", limit=2, window_seconds=60)
        limiter.check("owner-b", limit=2, window_seconds=60)

        with self.assertRaises(HTTPException) as raised:
            limiter.check("owner-a", limit=2, window_seconds=60)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("Retry-After", raised.exception.headers or {})


if __name__ == "__main__":
    unittest.main()
