import unittest

from oracle_arc import Arc
from oracle_arc.agents import AgentSpec
from oracle_arc.models import ScriptedBackend
from oracle_arc.tools.builtin import calculator_tool
from oracle_arc.tools.concierge import make_concierge_tools
from oracle_arc.types import Risk

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
    concierge_tools = make_concierge_tools(providers)
    tools = [calculator_tool(), *concierge_tools]
    grants = [("bud", "calculate"), ("concierge", "calculate")]
    grants.extend(("concierge", tool.name) for tool in concierge_tools)
    agents = [
        AgentSpec("bud", "1.0.0", "test host assistant",
                  "You are the test host's general assistant. Be accurate and concise.",
                  Risk.READ, ("bud",), health_check=lambda: True),
        AgentSpec("concierge", "1.0.0", "test host service coordinator",
                  "You are the test host's service coordinator. Do not invent provider outcomes.",
                  Risk.FINANCIAL, ("concierge",), health_check=lambda: True),
    ]
    arc = Arc([backend], server_key=KEY, step_up=step_up, agent_specs=agents,
              tool_specs=tools, tool_grants=grants, **kw)
    unittest.addModuleCleanup(arc.close)
    arc.apps.register_app("unibud", SECRET, scopes=("chat",))
    arc.apps.register_app("other", SECRET + "x", scopes=("chat",))
    return arc, backend


def principal(arc, user="u1", app="unibud", secret=SECRET):
    return arc.apps.verify_token(arc.apps.issue_token(app, secret, user))
