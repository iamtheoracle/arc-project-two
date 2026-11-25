import unittest

from oracle_arc.spark import SparkMemory
from oracle_arc.types import PermissionDenied, Principal, ValidationError

NS = ("study",)


def P(user="u1", app="appa"):
    return Principal(app, user)


class UserControlTests(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.m = SparkMemory(clock=lambda: self.t[0]); self.addCleanup(self.m.close)

    # --- regression: LIKE wildcards in user ids must never cross users --------------------------------
    def test_underscore_user_id_cannot_delete_other_users_memory(self):
        mid = self.m.remember(P("johnXdoe"), "study", NS, "private", scope="conversation", scope_id="c1")
        self.assertFalse(self.m.forget(P("john_doe"), mid))
        self.assertEqual(len(self.m.list_memories(P("johnXdoe"))), 1)

    def test_percent_user_id_cannot_wipe_other_users(self):
        self.m.remember(P("alice"), "study", NS, "a", scope="conversation", scope_id="c1")
        self.assertEqual(self.m.forget_all(P("%")), 0)
        self.assertEqual(self.m.list_memories(P("%")), [])
        self.assertEqual(len(self.m.list_memories(P("alice"))), 1)

    # --- list ------------------------------------------------------------------------------------------
    def test_list_returns_only_own_memories_with_purpose_and_version(self):
        self.m.remember(P("u1"), "study", NS, "likes mornings", purpose="study planning")
        self.m.remember(P("u2"), "study", NS, "likes nights")
        self.m.remember(P("u1", "appb"), "study", NS, "other app")
        rows = self.m.list_memories(P("u1"))
        self.assertEqual([r["content"] for r in rows], ["likes mornings"])
        self.assertEqual(rows[0]["purpose"], "study planning")
        self.assertEqual(rows[0]["version"], 1)

    def test_list_hides_expired_and_application_owned(self):
        self.m.remember(P("u1"), "study", NS, "temp", ttl_s=10)
        self.m.remember(P("u1"), "study", NS, "app wide", scope="application")
        self.t[0] += 20
        self.assertEqual(self.m.list_memories(P("u1")), [])

    def test_list_limit_is_bounded(self):
        for i in range(5):
            self.m.remember(P(), "study", NS, f"m{i}")
        self.assertEqual(len(self.m.list_memories(P(), limit=2)), 2)
        self.assertEqual(len(self.m.list_memories(P(), limit=10 ** 9)), 5)

    # --- correct ---------------------------------------------------------------------------------------
    def test_correct_updates_content_and_bumps_version(self):
        mid = self.m.remember(P(), "study", NS, "prefers mornings")
        self.assertTrue(self.m.correct(P(), mid, "prefers evenings"))
        row = self.m.list_memories(P())[0]
        self.assertEqual((row["content"], row["version"]), ("prefers evenings", 2))
        self.assertEqual(self.m.recall(P(), "study", NS, "evenings")[0].content, "prefers evenings")

    def test_correct_refuses_other_user_other_app_and_bad_content(self):
        mid = self.m.remember(P("u1"), "study", NS, "mine")
        self.assertFalse(self.m.correct(P("u2"), mid, "hijacked"))
        self.assertFalse(self.m.correct(P("u1", "appb"), mid, "hijacked"))
        with self.assertRaises(ValidationError):
            self.m.correct(P("u1"), mid, "")
        with self.assertRaises(ValidationError):
            self.m.correct(P("u1"), mid, "x" * 8001)
        self.assertEqual(self.m.list_memories(P("u1"))[0]["content"], "mine")

    # --- forget / forget_all ---------------------------------------------------------------------------
    def test_forget_all_removes_only_that_users_memories_and_shares(self):
        self.m.remember(P("u1"), "study", NS, "a")
        self.m.remember(P("u1"), "study", NS, "b", scope="conversation", scope_id="c1")
        self.m.remember(P("u2"), "study", NS, "keep")
        self.m.share(P("u1"), "study", "flow")
        self.assertEqual(self.m.forget_all(P("u1")), 2)
        self.assertEqual(self.m.list_memories(P("u1")), [])
        self.assertEqual(len(self.m.list_memories(P("u2"))), 1)
        self.assertEqual(self.m._db.execute("SELECT count(*) FROM share").fetchone()[0], 0)

    def test_forget_all_does_not_touch_application_memory_or_other_apps(self):
        self.m.remember(P("u1"), "study", NS, "app wide", scope="application")
        self.m.remember(P("u1", "appb"), "study", NS, "other app")
        self.m.forget_all(P("u1"))
        self.assertEqual(len(self.m.recall(P("u2"), "study", NS, "wide")), 1)
        self.assertEqual(len(self.m.list_memories(P("u1", "appb"))), 1)

    def test_every_user_control_is_audited_without_content(self):
        from oracle_arc.audit import AuditLog
        a = AuditLog(); self.addCleanup(a.close)
        m = SparkMemory(audit=a); self.addCleanup(m.close)
        mid = m.remember(P(), "study", NS, "secret thing")
        m.list_memories(P()); m.correct(P(), mid, "new secret"); m.forget(P(), mid); m.forget_all(P())
        events = {e["event"] for e in a.events()}
        self.assertTrue({"memory.list", "memory.correct", "memory.forget", "memory.forget_all"} <= events)
        self.assertNotIn("secret", str(a.events()))
        self.assertTrue(a.verify())

    # --- schema upgrade --------------------------------------------------------------------------------
    def test_existing_database_without_new_columns_is_upgraded(self):
        import os, sqlite3, tempfile
        d = tempfile.mkdtemp(); path = os.path.join(d, "m.db")
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE mem (id TEXT PRIMARY KEY, space TEXT, scope TEXT, owner TEXT, content TEXT,"
                   " dclass INTEGER, created REAL, expires REAL)")
        db.execute("INSERT INTO mem VALUES ('old','appa/study','personal','u1','legacy note',1,1.0,NULL)")
        db.commit(); db.close()
        m = SparkMemory(path); self.addCleanup(m.close)
        row = m.list_memories(P("u1"))[0]
        self.assertEqual((row["content"], row["purpose"], row["version"]), ("legacy note", "", 1))


if __name__ == "__main__":
    unittest.main()
