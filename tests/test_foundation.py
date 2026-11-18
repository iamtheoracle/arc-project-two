import sqlite3
import time
import unittest

from oracle_arc.audit import AuditLog
from oracle_arc.identity import AppRegistry
from oracle_arc.types import AuthError


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.r = AppRegistry(server_key=b"k" * 32)
        self.r.register_app("a", "a" * 20)
        self.r.register_app("b", "b" * 20)

    def test_token_roundtrip_binds_app_and_user(self):
        p = self.r.verify_token(self.r.issue_token("a", "a" * 20, "u1"))
        self.assertEqual((p.app_id, p.user_id), ("a", "u1"))

    def test_wrong_secret_and_unknown_app_rejected_identically(self):
        for app, sec in (("a", "wrong" * 5), ("nope", "a" * 20)):
            with self.assertRaises(AuthError) as c:
                self.r.issue_token(app, sec, "u1")
            self.assertEqual(str(c.exception), "invalid application credentials")

    def test_app_cannot_mint_token_for_another_app(self):
        with self.assertRaises(AuthError):
            self.r.issue_token("b", "a" * 20, "u1")      # a's secret, b's identity

    def test_tampered_token_rejected(self):
        t = self.r.issue_token("a", "a" * 20, "u1")
        v, body, sig = t.split(".")
        forged = ".".join([v, body[:-2] + ("AA" if body[-2:] != "AA" else "BB"), sig])
        with self.assertRaises(AuthError):
            self.r.verify_token(forged)

    def test_token_signed_with_other_key_rejected(self):
        other = AppRegistry(server_key=b"z" * 32)
        other.register_app("a", "a" * 20)
        with self.assertRaises(AuthError):
            self.r.verify_token(other.issue_token("a", "a" * 20, "u1"))

    def test_expiry_suspension_and_revocation(self):
        with self.assertRaises(AuthError):
            self.r.verify_token(self.r.issue_token("a", "a" * 20, "u1", ttl=-1))
        t = self.r.issue_token("a", "a" * 20, "u1")
        self.r.revoke_tokens("a")
        with self.assertRaises(AuthError):
            self.r.verify_token(t)
        t2 = self.r.issue_token("a", "a" * 20, "u1")
        self.r.suspend_app("a")
        with self.assertRaises(AuthError):
            self.r.verify_token(t2)

    def test_short_secret_refused(self):
        with self.assertRaises(ValueError):
            self.r.register_app("c", "short")


class AuditTests(unittest.TestCase):
    def test_chain_verifies_and_detects_tampering(self):
        a = AuditLog(); self.addCleanup(a.close)
        a.append("x", app_id="a", n=1)
        a.append("y", app_id="a", n=2)
        a.append("z", app_id="a", n=3)
        self.assertTrue(a.verify())
        a._db.execute("UPDATE audit SET detail='{\"n\":99}' WHERE seq=2")
        self.assertFalse(a.verify())

    def test_deleting_a_row_is_detected(self):
        a = AuditLog(); self.addCleanup(a.close)
        for i in range(4):
            a.append("e", i=i)
        a._db.execute("DELETE FROM audit WHERE seq=2")
        self.assertFalse(a.verify())

    def test_secrets_are_redacted(self):
        a = AuditLog(); self.addCleanup(a.close)
        a.append("login", password="hunter2", nested={"api_key": "abc", "ok": 1})
        d = a.events("login")[0]["detail"]
        self.assertEqual(d["password"], "[redacted]")
        self.assertEqual(d["nested"], {"api_key": "[redacted]", "ok": 1})


if __name__ == "__main__":
    unittest.main()
