import unittest

from oracle_arc.spark import SparkMemory
from oracle_arc.types import DataClass, PermissionDenied, Principal, ValidationError

BUD = ("bud",)
FLOW = ("flow",)


def P(user="u1", app="unibud"):
    return Principal(app, user)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class SparkTests(unittest.TestCase):
    def setUp(self):
        self.clk = Clock()
        self.m = SparkMemory(clock=self.clk); self.addCleanup(self.m.close)

    def test_recall_finds_relevant_memory(self):
        self.m.remember(P(), "bud", BUD, "I study civil engineering at Unilag")
        self.m.remember(P(), "bud", BUD, "My favourite food is jollof rice")
        r = self.m.recall(P(), "bud", BUD, "what do I study engineering")
        self.assertIn("civil engineering", r[0].content)

    def test_bud_cannot_read_flow_without_share(self):
        self.m.remember(P(), "flow", FLOW, "Savings balance is 450000 naira", data_class=DataClass.FINANCIAL)
        self.assertEqual(self.m.recall(P(), "bud", BUD, "savings balance"), [])

    def test_agent_cannot_use_namespace_it_is_not_allowed(self):
        with self.assertRaises(PermissionDenied):
            self.m.recall(P(), "flow", BUD, "balance")
        with self.assertRaises(PermissionDenied):
            self.m.remember(P(), "flow", BUD, "x")

    def test_explicit_share_then_revoke(self):
        self.m.remember(P(), "flow", FLOW, "Savings balance is 450000 naira", data_class=DataClass.FINANCIAL)
        self.m.share(P(), "flow", "bud")
        got = self.m.recall(P(), "bud", BUD, "savings balance")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].data_class, DataClass.FINANCIAL)     # sensitivity travels with the memory
        self.m.unshare(P(), "flow", "bud")
        self.assertEqual(self.m.recall(P(), "bud", BUD, "savings balance"), [])

    def test_share_is_per_user(self):
        self.m.remember(P("u1"), "flow", FLOW, "u1 savings balance")
        self.m.remember(P("u2"), "flow", FLOW, "u2 savings balance")
        self.m.share(P("u1"), "flow", "bud")
        texts = [x.content for x in self.m.recall(P("u1"), "bud", BUD, "savings balance")]
        self.assertEqual(texts, ["u1 savings balance"])
        self.assertEqual(self.m.recall(P("u2"), "bud", BUD, "savings balance"), [])

    def test_users_are_isolated(self):
        self.m.remember(P("u1"), "bud", BUD, "private note about exams")
        self.assertEqual(self.m.recall(P("u2"), "bud", BUD, "exams"), [])

    def test_applications_are_isolated(self):
        self.m.remember(P(app="unibud"), "bud", BUD, "private note about exams")
        self.assertEqual(self.m.recall(P(app="other"), "bud", BUD, "exams"), [])

    def test_conversation_memory_is_private_to_conversation(self):
        self.m.remember(P(), "bud", BUD, "draft plan for the trip", scope="conversation", scope_id="c1")
        self.assertEqual(len(self.m.recall(P(), "bud", BUD, "trip plan", scope_ids=["c1"])), 1)
        self.assertEqual(self.m.recall(P(), "bud", BUD, "trip plan", scope_ids=["c2"]), [])
        self.assertEqual(self.m.recall(P(), "bud", BUD, "trip plan"), [])

    def test_task_memory_expires(self):
        self.m.remember(P(), "bud", BUD, "temporary booking context", scope="task", scope_id="t1", ttl_s=60)
        self.assertEqual(len(self.m.recall(P(), "bud", BUD, "booking context", scope_ids=["t1"])), 1)
        self.clk.t += 61
        self.assertEqual(self.m.recall(P(), "bud", BUD, "booking context", scope_ids=["t1"]), [])
        self.assertEqual(self.m.purge_expired(), 1)

    def test_validation_and_forget(self):
        with self.assertRaises(ValidationError):
            self.m.remember(P(), "bud", BUD, "")
        with self.assertRaises(ValidationError):
            self.m.remember(P(), "bud", BUD, "x", scope="nonsense")
        mid = self.m.remember(P("u1"), "bud", BUD, "to be forgotten")
        self.assertFalse(self.m.forget(P("u2"), mid))
        self.assertTrue(self.m.forget(P("u1"), mid))
        self.assertEqual(self.m.recall(P("u1"), "bud", BUD, "forgotten"), [])


if __name__ == "__main__":
    unittest.main()
