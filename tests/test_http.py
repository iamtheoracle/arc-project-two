import json
import threading
import unittest
import urllib.error
import urllib.request

from tests.helpers import FakeProviders, SECRET, make_arc

PLAN_BOOK = json.dumps({"action": "tool", "tool": "book_provider", "args": {
    "provider_id": "p1", "quote_id": "q1", "amount_minor": 1500000, "currency": "NGN"}})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.prov = FakeProviders()
        self.arc, _ = make_arc(replies=[PLAN_BOOK], providers=self.prov)
        self.srv = self.arc.make_server("127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, body=None, token=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def token(self, user="u1"):
        s, b = self.call("POST", "/v1/token", {"app_id": "unibud", "app_secret": SECRET, "user_id": user})
        self.assertEqual(s, 200)
        return b["token"]

    def test_complete_endpoint_is_authenticated_governed_and_audited(self):
        self.arc.models.backends[0].replies.clear()
        msgs = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "my balance is ₦450,000"}]
        self.assertEqual(self.call("POST", "/v1/complete", {"messages": msgs})[0], 401)
        s, b = self.call("POST", "/v1/complete", {"messages": msgs, "max_tokens": 50}, self.token())
        self.assertEqual((s, b["status"], b["text"]), (200, "answered", "ok"))
        events = self.arc.audit.events("complete.requested")
        self.assertEqual(events[-1]["detail"], {"data_class": 2, "messages": 2})
        self.assertNotIn("450,000", json.dumps(self.arc.audit.events()))      # content is never audited

    def test_complete_rejects_malformed_input(self):
        t = self.token()
        for body in ({"messages": []}, {"messages": "hi"}, {"messages": [{"role": "root", "content": "x"}]},
                     {"messages": [{"role": "user", "content": 5}]}, {"messages": [{"role": "user", "content": "x"}], "max_tokens": "9"},
                     {"messages": [{"role": "user", "content": "x"}], "max_tokens": 10**6}):
            s, b = self.call("POST", "/v1/complete", body, t)
            self.assertTrue(s == 400 or (s == 200 and b["status"] == "failed"), body)

    def test_complete_never_sends_financial_data_to_remote_by_default(self):
        from oracle_arc.models import ScriptedBackend
        remote = ScriptedBackend("remote", local=False)
        self.arc.models.backends = [remote]
        self.arc.models._health["remote"] = type(self.arc.models._health["local"])()
        s, b = self.call("POST", "/v1/complete", {"messages": [{"role": "user", "content": "x"}],
                                                  "data_class": "FINANCIAL"}, self.token())
        self.assertEqual(b["status"], "unavailable")
        self.assertEqual(remote.calls, [])

    def test_health_is_public_and_minimal(self):
        self.assertEqual(self.call("GET", "/v1/health"), (200, {"status": "ok"}))

    def test_chat_requires_token(self):
        self.assertEqual(self.call("POST", "/v1/chat", {"message": "hi"})[0], 401)
        self.assertEqual(self.call("POST", "/v1/chat", {"message": "hi"}, token="v1.bad.sig")[0], 401)

    def test_bad_credentials_rejected(self):
        s, b = self.call("POST", "/v1/token", {"app_id": "unibud", "app_secret": "nope" * 6, "user_id": "u1"})
        self.assertEqual((s, b["error"]), (401, "unauthenticated"))

    def test_calculator_over_http(self):
        s, b = self.call("POST", "/v1/chat", {"agent": "bud", "message": "what is 6*7"}, self.token())
        self.assertEqual((s, b["status"], b["text"]), (200, "completed", "42"))

    def test_full_booking_flow_over_http(self):
        t = self.token()
        s, b = self.call("POST", "/v1/chat", {"agent": "concierge", "message": "Book the ₦15,000 vehicle"}, t)
        self.assertEqual(b["status"], "needs_confirmation")
        self.assertEqual(self.prov.booked, [])
        c = b["confirmation"]
        s, done = self.call("POST", "/v1/confirm", {"confirmation_id": c["id"], "action_hash": c["action_hash"],
                                                    "proof": {"pin": "1234"}}, t)
        self.assertEqual((s, done["status"]), (200, "completed"))
        self.assertEqual(len(self.prov.booked), 1)

    def test_another_user_cannot_confirm_over_http(self):
        t1, t2 = self.token("u1"), self.token("u2")
        _, b = self.call("POST", "/v1/chat", {"agent": "concierge", "message": "book it"}, t1)
        c = b["confirmation"]
        _, r = self.call("POST", "/v1/confirm", {"confirmation_id": c["id"], "action_hash": c["action_hash"],
                                                 "proof": {"pin": "1234"}}, t2)
        self.assertEqual(r["status"], "denied")
        self.assertEqual(self.prov.booked, [])

    def test_validation_errors_are_400_not_500(self):
        t = self.token()
        self.assertEqual(self.call("POST", "/v1/chat", {"agent": "bud"}, t)[0], 400)
        self.assertEqual(self.call("POST", "/v1/chat", {"message": "x", "data_class": "SECRET"}, t)[0], 400)
        self.assertEqual(self.call("POST", "/v1/chat", raw=b"[1,2]", token=t)[0], 400)
        self.assertEqual(self.call("POST", "/v1/chat", raw=b"{not json", token=t)[0], 400)

    def test_oversized_body_rejected(self):
        req = urllib.request.Request(self.base + "/v1/chat", data=b"{}", method="POST",
                                     headers={"Content-Length": "5000000", "Authorization": "Bearer x"})
        with self.assertRaises((urllib.error.HTTPError, urllib.error.URLError, ConnectionError)):
            urllib.request.urlopen(req, timeout=5)

    def test_unknown_route_404_and_suspended_app_locked_out(self):
        t = self.token()
        self.assertEqual(self.call("GET", "/v1/nope", token=t)[0], 404)
        self.arc.apps.suspend_app("unibud")
        self.assertEqual(self.call("POST", "/v1/chat", {"message": "hi"}, t)[0], 401)

    def test_memory_share_endpoint_is_user_scoped(self):
        t = self.token()
        self.assertEqual(self.call("POST", "/v1/memory/share", {"from": "flow", "to": "bud"}, t)[0], 200)
        self.assertEqual(self.call("POST", "/v1/memory/share", {"from": "flow", "to": "bud"})[0], 401)

    def test_internal_errors_do_not_leak(self):
        self.arc.oracle.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret path /etc/x"))
        s, b = self.call("POST", "/v1/chat", {"message": "hi"}, self.token())
        self.assertEqual((s, b), (500, {"error": "internal_error"}))


if __name__ == "__main__":
    unittest.main()
