import unittest

from oracle_arc.models import ModelGateway, RoutingPolicy, ScriptedBackend, UsageMeter
from oracle_arc.types import ChatRequest, DataClass, ModelUnavailable, QuotaExceeded


def req(text="hi", **kw):
    return ChatRequest([{"role": "user", "content": text}], **kw)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class GatewayTests(unittest.TestCase):
    def test_falls_back_when_primary_fails(self):
        a, b = ScriptedBackend("a", fail=True), ScriptedBackend("b", replies=["from b"])
        res = ModelGateway([a, b]).chat(req())
        self.assertEqual((res.text, res.backend), ("from b", "b"))

    def test_all_failing_raises_with_reasons_not_a_fabricated_answer(self):
        with self.assertRaises(ModelUnavailable) as c:
            ModelGateway([ScriptedBackend("a", fail=True)]).chat(req())
        self.assertIn("a:", c.exception.detail["reasons"][0])

    def test_circuit_opens_then_recovers_after_cooldown(self):
        clk = Clock()
        a, b = ScriptedBackend("a", fail=True), ScriptedBackend("b")
        g = ModelGateway([a, b], RoutingPolicy(failure_threshold=2, cooldown_s=30), clock=clk)
        g.chat(req("1")); g.chat(req("2"))
        n = len(a.calls)
        g.chat(req("3"))
        self.assertEqual(len(a.calls), n, "open circuit must not be called")
        a.fail = False
        clk.t += 31
        self.assertEqual(g.chat(req("4")).backend, "a")

    def test_remote_never_used_by_default(self):
        remote = ScriptedBackend("remote", local=False)
        with self.assertRaises(ModelUnavailable):
            ModelGateway([remote]).chat(req())
        self.assertEqual(remote.calls, [])

    def test_remote_gated_by_data_class(self):
        remote = ScriptedBackend("remote", local=False)
        g = ModelGateway([remote], RoutingPolicy(allow_remote=True, remote_max_data_class=DataClass.INTERNAL))
        self.assertEqual(g.chat(req(data_class=DataClass.INTERNAL)).backend, "remote")
        with self.assertRaises(ModelUnavailable):
            g.chat(req("secret", data_class=DataClass.FINANCIAL))

    def test_local_preferred_over_remote_even_if_remote_listed_first(self):
        remote, local = ScriptedBackend("remote", local=False), ScriptedBackend("local")
        g = ModelGateway([remote, local], RoutingPolicy(allow_remote=True, remote_max_data_class=DataClass.PUBLIC))
        self.assertEqual(g.chat(req(data_class=DataClass.PUBLIC)).backend, "local")

    def test_latency_routing_prefers_faster_of_equals(self):
        slow, fast = ScriptedBackend("slow", delay=0.05), ScriptedBackend("fast")
        g = ModelGateway([slow, fast], RoutingPolicy(cache_size=0))
        g.chat(req("a")); g.chat(req("b"))      # first call goes to slow (priority), seeding its latency
        g._health["fast"].ewma_ms = 1.0
        self.assertEqual(g.chat(req("c")).backend, "fast")

    def test_cache_only_for_deterministic_requests(self):
        b = ScriptedBackend("a")
        g = ModelGateway([b])
        g.chat(req("x", temperature=0)); r = g.chat(req("x", temperature=0))
        self.assertTrue(r.cached); self.assertEqual(len(b.calls), 1)
        g.chat(req("y", temperature=0.7)); g.chat(req("y", temperature=0.7))
        self.assertEqual(len(b.calls), 3)

    def test_token_quota_enforced_per_app(self):
        m = UsageMeter()
        m.set_limit("app1", max_tokens=10)
        g = ModelGateway([ScriptedBackend("a", replies=["x" * 100])], meter=m)
        g.chat(req("hello world" * 5), app_id="app1")
        with self.assertRaises(QuotaExceeded):
            g.chat(req("again"), app_id="app1")
        g.chat(req("other app is unaffected"), app_id="app2")

    def test_cost_quota_enforced(self):
        m = UsageMeter()
        m.set_limit("app1", max_cost=0.0001)
        g = ModelGateway([ScriptedBackend("paid", local=False, cost_per_1k=10.0)],
                         RoutingPolicy(allow_remote=True, remote_max_data_class=DataClass.PUBLIC, cache_size=0), m)
        g.chat(req("one", data_class=DataClass.PUBLIC), app_id="app1")
        with self.assertRaises(QuotaExceeded):
            g.chat(req("two", data_class=DataClass.PUBLIC), app_id="app1")


if __name__ == "__main__":
    unittest.main()
