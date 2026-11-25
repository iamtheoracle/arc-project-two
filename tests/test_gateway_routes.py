import base64
import json
import threading
import unittest
import urllib.error
import urllib.request

from tests.helpers import SECRET, make_arc
from oracle_arc.orbits import EICAR

NS = ("bud",)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class RouteBase(unittest.TestCase):
    def setUp(self):
        self.clk = [1000.0]
        self.arc, _ = make_arc(rate_clock=lambda: self.clk[0])
        self.arc.apps.register_app("scoped", SECRET + "s", scopes=("chat", "memory", "orbits"))
        self.arc.apps.register_app("scoped2", SECRET + "t", scopes=("chat", "memory", "orbits"))

    def tok(self, user="u1", app="scoped", secret=SECRET + "s"):
        # Each call goes through handle() so the real token path and its limiter are exercised.
        st, b = self.arc.handle("POST", "/v1/token", {}, {"app_id": app, "app_secret": secret, "user_id": user},
                                client=f"10.0.0.{len(user)}")
        self.assertEqual(st, 200, b)
        return {"Authorization": "Bearer " + b["token"]}

    def call(self, method, path, headers, body=None):
        return self.arc.handle(method, path, headers, body or {})


class MemoryRoutes(RouteBase):
    def test_scope_is_required(self):
        h = self.tok("u1", "unibud", SECRET)                     # registered with ("chat",) only
        for m, path in (("GET", "/v1/memory"), ("POST", "/v1/memory/forget_all"),
                        ("POST", "/v1/memory/correct"), ("POST", "/v1/memory/forget")):
            st, b = self.call(m, path, h, {"id": "x", "content": "y", "confirm": True})
            self.assertEqual((st, b["error"]), (403, "permission_denied"), path)

    def test_unauthenticated_is_refused(self):
        self.assertEqual(self.call("GET", "/v1/memory", {})[0], 401)

    def test_list_correct_forget_roundtrip_and_isolation(self):
        from oracle_arc.types import Principal
        mid = self.arc.memory.remember(Principal("scoped", "u1"), "bud", NS, "prefers mornings", purpose="planning")
        self.arc.memory.remember(Principal("scoped", "u2"), "bud", NS, "someone else")
        h1, h2 = self.tok("u1"), self.tok("u2")
        st, b = self.call("GET", "/v1/memory", h1)
        self.assertEqual((st, [m["content"] for m in b["memories"]]), (200, ["prefers mornings"]))
        self.assertEqual(b["memories"][0]["purpose"], "planning")
        # another user cannot correct or delete it, and gets the same answer as for a missing id
        self.assertEqual(self.call("POST", "/v1/memory/correct", h2, {"id": mid, "content": "x"})[0], 403)
        self.assertEqual(self.call("POST", "/v1/memory/forget", h2, {"id": mid})[0], 403)
        self.assertEqual(self.call("POST", "/v1/memory/forget", h2, {"id": "nope"})[0], 403)
        self.assertEqual(self.call("POST", "/v1/memory/correct", h1, {"id": mid, "content": "prefers evenings"})[0], 200)
        self.assertEqual(self.call("GET", "/v1/memory", h1)[1]["memories"][0]["version"], 2)
        self.assertEqual(self.call("POST", "/v1/memory/forget", h1, {"id": mid})[0], 200)
        self.assertEqual(self.call("GET", "/v1/memory", h1)[1]["memories"], [])
        self.assertEqual(len(self.call("GET", "/v1/memory", h2)[1]["memories"]), 1)

    def test_other_application_cannot_touch_it(self):
        from oracle_arc.types import Principal
        mid = self.arc.memory.remember(Principal("scoped", "u1"), "bud", NS, "mine")
        h = self.tok("u1", "scoped2", SECRET + "t")
        self.assertEqual(self.call("POST", "/v1/memory/forget", h, {"id": mid})[0], 403)
        self.assertEqual(self.call("GET", "/v1/memory", h)[1]["memories"], [])

    def test_forget_all_requires_explicit_confirmation(self):
        from oracle_arc.types import Principal
        self.arc.memory.remember(Principal("scoped", "u1"), "bud", NS, "a")
        h = self.tok("u1")
        for body in ({}, {"confirm": "true"}, {"confirm": 1}, {"confirm": False}):
            self.assertEqual(self.call("POST", "/v1/memory/forget_all", h, body)[0], 400, body)
        self.assertEqual(len(self.call("GET", "/v1/memory", h)[1]["memories"]), 1)
        self.assertEqual(self.call("POST", "/v1/memory/forget_all", h, {"confirm": True}), (200, {"forgotten": 1}))

    def test_validation(self):
        h = self.tok("u1")
        self.assertEqual(self.call("POST", "/v1/memory/forget", h, {})[0], 400)
        self.assertEqual(self.call("POST", "/v1/memory/correct", h, {"id": "x", "content": ""})[0], 400)
        self.assertEqual(self.call("POST", "/v1/memory/correct", h, {"id": 5, "content": "x"})[0], 400)
        self.assertEqual(self.call("GET", "/v1/memory/unknown", h)[0], 404)

    def test_existing_share_routes_unchanged(self):
        h = self.tok("u1", "unibud", SECRET)
        self.assertEqual(self.call("POST", "/v1/memory/share", h, {"from": "a", "to": "b"}), (200, {"shared": True}))
        self.assertEqual(self.call("POST", "/v1/memory/unshare", h, {"from": "a", "to": "b"}), (200, {"shared": False}))


class OrbitsRoutes(RouteBase):
    def upload(self, h, name="note.txt", data=b"hello world", mime=""):
        return self.call("POST", "/v1/orbits/assets", h, {"name": name, "content_base64": b64(data), "mime": mime})

    def test_scope_is_required(self):
        h = self.tok("u1", "unibud", SECRET)
        self.assertEqual(self.upload(h)[0], 403)
        self.assertEqual(self.call("GET", "/v1/orbits/assets/abc", h)[0], 403)

    def test_upload_metadata_content_text_delete(self):
        h = self.tok()
        st, b = self.upload(h)
        self.assertEqual(st, 201)
        a = b["asset"]
        self.assertEqual((a["kind"], a["size"], a["status"]), ("text", 11, "ready"))
        self.assertNotIn("content_base64", a)
        self.assertEqual(self.call("GET", f"/v1/orbits/assets/{a['id']}", h)[1]["asset"]["sha256"], a["sha256"])
        self.assertEqual(self.call("GET", f"/v1/orbits/assets/{a['id']}/content", h)[1]["content_base64"], b64(b"hello world"))
        self.assertEqual(self.call("GET", f"/v1/orbits/assets/{a['id']}/text", h)[1]["text"], "hello world")
        self.assertEqual(self.call("POST", f"/v1/orbits/assets/{a['id']}/delete", h), (200, {"deleted": True}))
        self.assertEqual(self.call("GET", f"/v1/orbits/assets/{a['id']}", h)[0], 403)

    def test_assets_are_private_to_owner_and_app_with_uniform_errors(self):
        h1, h2 = self.tok("u1"), self.tok("u2")
        h3 = self.tok("u1", "scoped2", SECRET + "t")
        aid = self.upload(h1)[1]["asset"]["id"]
        for h in (h2, h3):
            for path, m in ((f"/v1/orbits/assets/{aid}", "GET"), (f"/v1/orbits/assets/{aid}/content", "GET"),
                            (f"/v1/orbits/assets/{aid}/text", "GET"), (f"/v1/orbits/assets/{aid}/delete", "POST")):
                other = self.call(m, path, h)
                missing = self.call(m, path.replace(aid, "0" * 32), h)
                self.assertEqual(other, missing)                 # not-yours looks exactly like not-found
                self.assertEqual(other[0], 403)
        self.assertEqual(self.call("GET", f"/v1/orbits/assets/{aid}", h1)[0], 200)

    def test_malware_and_executables_are_rejected_with_422_and_audited(self):
        h = self.tok()
        st, b = self.upload(h, "eicar.txt", EICAR)
        self.assertEqual((st, b["error"]), (422, "media_rejected"))
        st, b = self.upload(h, "run.exe", b"MZ\x90\x00" + b"\x00" * 60)
        self.assertEqual((st, b["error"]), (422, "media_rejected"))
        self.assertTrue(self.arc.audit.events("orbits.rejected"))
        self.assertNotIn(EICAR.decode(), json.dumps(self.arc.audit.events()))     # payload never logged

    def test_declared_type_must_match_content(self):
        st, b = self.upload(self.tok(), "pic.png", b"just text", "image/png")
        self.assertEqual(st, 422)

    def test_bad_input_is_400(self):
        h = self.tok()
        for body in ({}, {"name": "a"}, {"name": "", "content_base64": "aGk="}, {"name": "a", "content_base64": "!!!"},
                     {"name": "a", "content_base64": 5}, {"name": "a", "content_base64": "aGk=", "mime": 3}):
            self.assertEqual(self.call("POST", "/v1/orbits/assets", h, body)[0], 400, body)
        self.assertEqual(self.upload(h, data=b"")[0], 422)         # empty upload is rejected by ORBITS

    def test_text_for_media_without_processor_is_honestly_unavailable(self):
        h = self.tok()
        aid = self.upload(h, "pic.png", PNG, "image/png")[1]["asset"]["id"]
        st, b = self.call("GET", f"/v1/orbits/assets/{aid}/text", h)
        self.assertEqual((st, b["error"]), (503, "tool_unavailable"))

    def test_unknown_routes_and_methods(self):
        h = self.tok()
        self.assertEqual(self.call("GET", "/v1/orbits/assets", h)[0], 404)
        self.assertEqual(self.call("GET", "/v1/orbits/assets/a/b/c", h)[0], 404)
        self.assertEqual(self.call("GET", "/v1/orbits/assets/a/unknown", h)[0], 404)
        self.assertEqual(self.call("POST", "/v1/orbits/assets/a", h)[0], 404)


class RateLimits(RouteBase):
    def test_token_endpoint_throttles_secret_guessing_per_client(self):
        codes = []
        for _ in range(14):
            codes.append(self.arc.handle("POST", "/v1/token", {},
                         {"app_id": "scoped", "app_secret": "wrong" * 5, "user_id": "u"}, client="203.0.113.9")[0])
        self.assertIn(429, codes)
        self.assertEqual(codes[:10], [401] * 10)                 # burst of 10 attempts, then throttled
        # other applications are unaffected, even from the throttled client's network
        st, _ = self.arc.handle("POST", "/v1/token", {}, {"app_id": "scoped2", "app_secret": SECRET + "t",
                                                         "user_id": "u"}, client="198.51.100.1")
        self.assertEqual(st, 200)
        # Deliberate trade-off: after 10 failed secrets the targeted app's token issuance pauses for everyone,
        # even with the right secret (otherwise a correct guess would bypass the throttle). It recovers.
        st, b = self.arc.handle("POST", "/v1/token", {}, {"app_id": "scoped", "app_secret": SECRET + "s",
                                                         "user_id": "u"}, client="198.51.100.2")
        self.assertEqual((st, b["error"]), (429, "rate_limited"))
        self.clk[0] += 10
        st, _ = self.arc.handle("POST", "/v1/token", {}, {"app_id": "scoped", "app_secret": SECRET + "s",
                                                         "user_id": "u"}, client="198.51.100.2")
        self.assertEqual(st, 200)

    def test_successful_logins_do_not_consume_the_application_failure_budget(self):
        for i in range(30):
            st, _ = self.arc.handle("POST", "/v1/token", {}, {"app_id": "scoped", "app_secret": SECRET + "s",
                                                             "user_id": f"u{i}"}, client=f"10.9.0.{i}")
            self.assertEqual(st, 200)

    def test_token_throttle_per_application_defeats_ip_rotation(self):
        codes = [self.arc.handle("POST", "/v1/token", {}, {"app_id": "scoped", "app_secret": "x" * 20, "user_id": "u"},
                                 client=f"192.0.2.{i}")[0] for i in range(14)]
        self.assertIn(429, codes)

    def test_429_has_retry_after_and_recovers(self):
        h = self.tok()
        for _ in range(40):
            st, b = self.call("GET", "/v1/memory", h)
            if st == 429:
                break
        self.assertEqual((st, b["error"]), (429, "rate_limited"))
        self.assertGreater(b["retry_after"], 0)
        self.clk[0] += 60
        self.assertEqual(self.call("GET", "/v1/memory", h)[0], 200)

    def test_one_users_flood_does_not_block_another_user(self):
        h1, h2 = self.tok("u1"), self.tok("u2")
        for _ in range(60):
            self.call("GET", "/v1/memory", h1)
        self.assertEqual(self.call("GET", "/v1/memory", h1)[0], 429)
        self.assertEqual(self.call("GET", "/v1/memory", h2)[0], 200)

    def test_app_wide_limit_protects_against_many_users(self):
        arc, _ = make_arc(rate_clock=lambda: 1.0, rate_limits={"app": (1.0, 5), "user": (100.0, 100)})
        arc.apps.register_app("busy", SECRET + "b", scopes=("memory",))
        codes = []
        for i in range(12):
            st, b = arc.handle("POST", "/v1/token", {}, {"app_id": "busy", "app_secret": SECRET + "b",
                                                        "user_id": f"user{i}"}, client=f"10.1.0.{i}")
            h = {"Authorization": "Bearer " + b["token"]}
            codes.append(arc.handle("GET", "/v1/memory", h, {})[0])
        self.assertEqual(codes.count(200), 5)
        self.assertEqual(codes.count(429), 7)

    def test_health_is_not_limited_and_does_not_need_auth(self):
        for _ in range(200):
            self.assertEqual(self.arc.handle("GET", "/v1/health", {}, {})[0], 200)


class HttpLayer(RouteBase):
    def setUp(self):
        super().setUp()
        self.srv = self.arc.make_server("127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def http(self, method, path, body=None, token=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read())

    def test_upload_larger_than_the_json_limit_works_only_on_the_orbits_route(self):
        _, _, b = self.http("POST", "/v1/token", {"app_id": "scoped", "app_secret": SECRET + "s", "user_id": "u1"})
        big = b"A" * 1_500_000                                  # > MAX_BODY, < text kind limit
        st, _, r = self.http("POST", "/v1/orbits/assets", {"name": "big.txt", "content_base64": b64(big)}, b["token"])
        self.assertEqual((st, r["asset"]["size"]), (201, 1_500_000))
        st, _, r = self.http("POST", "/v1/memory/forget", {"id": "x" * 1_100_000}, b["token"])
        self.assertEqual((st, r["error"]), (413, "payload_too_large"))

    def test_retry_after_header_on_429(self):
        for _ in range(12):
            st, hdr, r = self.http("POST", "/v1/token", {"app_id": "scoped", "app_secret": "w" * 20, "user_id": "u"})
        self.assertEqual(st, 429)
        self.assertGreaterEqual(int(hdr["Retry-After"]), 1)


if __name__ == "__main__":
    unittest.main()
