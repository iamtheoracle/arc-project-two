import unittest

from oracle_arc import Arc
from oracle_arc.models import ScriptedBackend, RoutingPolicy

SECRET = "s3cret-value-for-tests-1234"
KEY = b"k" * 32


class FakeProviders:
    def __init__(self, final_status="confirmed"):
        self.final_status, self.booked, self.search_calls = final_status, [], 0

    def search(self, query):
        self.search_calls += 1
        return [{"provider_id": "p1", "name": "Campus Cabs"}]

    def quote(self, provider_id, request):
        return {"quote_id": "q1", "amount_minor": 1500000, "currency": "NGN"}

    def book(self, provider_id, quote_id, amount_minor, currency, idempotency_key):
        self.booked.append((provider_id, quote_id, amount_minor, currency, idempotency_key))
        return {"booking_ref": "B-1", "status": "pending"}

    def status(self, booking_ref):
        return self.final_status


def make_arc(replies=None, providers=None, step_up=lambda p, proof: proof.get("pin") == "1234", **kw):
    backend = ScriptedBackend("local", replies=replies or [])
    arc = Arc([backend], providers=providers, server_key=KEY, step_up=step_up, **kw)
    unittest.addModuleCleanup(arc.close)
    arc.apps.register_app("unibud", SECRET, scopes=("chat",))
    arc.apps.register_app("other", SECRET + "x", scopes=("chat",))
    return arc, backend


def principal(arc, user="u1", app="unibud", secret=SECRET):
    return arc.apps.verify_token(arc.apps.issue_token(app, secret, user))
