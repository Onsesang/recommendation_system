from __future__ import annotations

import unittest

from shopping_agent.v1.rate_limit import RateLimited, RateLimiter, client_ip


class RateLimiterTests(unittest.TestCase):
    def test_sliding_window_blocks_then_recovers(self) -> None:
        now = [100.0]
        limiter = RateLimiter({"login": {"limit": 2, "window_seconds": 60}}, clock=lambda: now[0])
        limiter.check("login", "1.2.3.4")
        limiter.check("login", "1.2.3.4")
        with self.assertRaises(RateLimited) as blocked:
            limiter.check("login", "1.2.3.4")
        self.assertEqual(blocked.exception.retry_after, 60)
        limiter.check("login", "5.6.7.8")  # other clients are unaffected
        now[0] = 160.5
        limiter.check("login", "1.2.3.4")  # the first hit has left the window
        limiter.check("unknown_rule", "anyone")  # rules not configured never block

    def test_client_ip_trusts_forwarded_headers_only_from_the_local_tunnel(self) -> None:
        trusted = {"127.0.0.1"}
        self.assertEqual(client_ip("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"}, trusted), "203.0.113.9")
        self.assertEqual(client_ip("127.0.0.1", {"X-Forwarded-For": "198.51.100.1, 10.0.0.1"}, trusted), "198.51.100.1")
        self.assertEqual(client_ip("127.0.0.1", {}, trusted), "127.0.0.1")
        self.assertEqual(client_ip("192.0.2.5", {"CF-Connecting-IP": "203.0.113.9"}, trusted), "192.0.2.5")


if __name__ == "__main__":
    unittest.main()
