import unittest

from oracle_arc.ratelimit import RateLimiter
from oracle_arc.types import RateLimited


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.c = Clock()

    def test_burst_then_refuse_then_refill(self):
        rl = RateLimiter(rate_per_s=2, burst=3, clock=self.c)
        for _ in range(3):
            rl.check("k")
        with self.assertRaises(RateLimited) as cm:
            rl.check("k")
        self.assertAlmostEqual(cm.exception.retry_after, 0.5, places=3)
        self.c.t += 0.5
        rl.check("k")
        with self.assertRaises(RateLimited):
            rl.check("k")

    def test_keys_are_independent(self):
        rl = RateLimiter(1, 1, clock=self.c)
        rl.check("a")
        rl.check("b")
        with self.assertRaises(RateLimited):
            rl.check("a")

    def test_refill_is_capped_at_burst(self):
        rl = RateLimiter(10, 2, clock=self.c)
        self.c.t += 1000
        rl.check("k"); rl.check("k")
        with self.assertRaises(RateLimited):
            rl.check("k")

    def test_memory_is_bounded(self):
        rl = RateLimiter(1, 1, max_keys=50, clock=self.c)
        for i in range(500):
            rl.check(f"k{i}")
        self.assertLessEqual(len(rl), 50)

    def test_refused_request_does_not_consume_or_extend_the_wait(self):
        rl = RateLimiter(1, 1, clock=self.c)
        rl.check("k")
        for _ in range(20):
            with self.assertRaises(RateLimited):
                rl.check("k")
        self.c.t += 1.0
        rl.check("k")                    # hammering while limited must not push recovery out

    def test_invalid_configuration_rejected(self):
        for args in ((0, 1), (1, 0), (-1, 5)):
            with self.assertRaises(ValueError):
                RateLimiter(*args)
        with self.assertRaises(ValueError):
            RateLimiter(1, 1, max_keys=0)

    def test_concurrent_callers_never_exceed_burst(self):
        import threading
        rl = RateLimiter(0.0001, 25, clock=self.c)
        ok = []

        def go():
            for _ in range(20):
                try:
                    rl.check("shared"); ok.append(1)
                except RateLimited:
                    pass
        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(ok), 25)


if __name__ == "__main__":
    unittest.main()
