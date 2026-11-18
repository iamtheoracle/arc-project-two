import json
import unittest

from oracle_arc import ArcRequest, DataClass, Risk
from oracle_arc.oracle import figures
from tests.helpers import FakeProviders, make_arc, principal

PLAN_SEARCH = json.dumps({"action": "tool", "tool": "search_providers", "args": {"query": "transport"}})
PLAN_BOOK = json.dumps({"action": "tool", "tool": "book_provider", "args": {
    "provider_id": "p1", "quote_id": "q1", "amount_minor": 1500000, "currency": "NGN"}})


def run(arc, p, msg, agent="concierge", **kw):
    return arc.oracle.run(p, ArcRequest(agent, msg, **kw))


class FastPathTests(unittest.TestCase):
    def test_calculator_needs_no_model_call_and_is_verified(self):
        arc, model = make_arc()
        r = run(arc, principal(arc), "what is 12 * 7", agent="bud")
        self.assertEqual((r.status, r.text), ("completed", "84"))
        self.assertEqual(model.calls, [], "deterministic operations must not require an LLM")

    def test_exponent_bomb_rejected_quickly(self):
        arc, _ = make_arc()
        r = run(arc, principal(arc), "9**9**9", agent="bud")
        self.assertEqual(r.status, "failed")

    def test_division_by_zero_is_failure_not_crash(self):
        arc, _ = make_arc()
        self.assertEqual(run(arc, principal(arc), "1/0", agent="bud").status, "failed")


class PermissionTests(unittest.TestCase):
    def test_bud_cannot_use_concierge_tools_even_if_model_asks(self):
        prov = FakeProviders()
        arc, _ = make_arc(replies=[PLAN_SEARCH], providers=prov)
        r = run(arc, principal(arc), "find me transport", agent="bud")
        self.assertEqual(r.status, "denied")
        self.assertEqual(prov.search_calls, 0)

    def test_model_requesting_ungranted_tool_is_denied(self):
        arc, _ = make_arc(replies=[PLAN_BOOK], providers=FakeProviders())
        arc.grants.revoke("concierge", "book_provider")
        arc.grants.grant("concierge", "request_quote")             # keep a tool so the planner runs
        r = run(arc, principal(arc), "book the cab")
        self.assertEqual(r.status, "denied")

    def test_concierge_can_search_without_confirmation(self):
        prov = FakeProviders()
        arc, _ = make_arc(replies=[PLAN_SEARCH], providers=prov)
        r = run(arc, principal(arc), "find me transport for the event")
        self.assertEqual(r.status, "completed")
        self.assertEqual(prov.search_calls, 1)

    def test_invalid_model_arguments_rejected(self):
        bad = json.dumps({"action": "tool", "tool": "book_provider", "args": {
            "provider_id": "p1", "quote_id": "q1", "amount_minor": -5, "currency": "NGN"}})
        prov = FakeProviders()
        arc, _ = make_arc(replies=[bad], providers=prov)
        self.assertEqual(run(arc, principal(arc), "book it").status, "failed")
        self.assertEqual(prov.booked, [])

    def test_extra_arguments_rejected(self):
        bad = json.dumps({"action": "tool", "tool": "search_providers", "args": {"query": "x", "admin": True}})
        arc, _ = make_arc(replies=[bad], providers=FakeProviders())
        self.assertEqual(run(arc, principal(arc), "find x").status, "failed")

    def test_suspended_agent_is_denied(self):
        arc, _ = make_arc()
        arc.agents.set_state("bud", "suspended")
        self.assertEqual(run(arc, principal(arc), "hello", agent="bud").status, "denied")


class ConfirmationFlowTests(unittest.TestCase):
    def setUp(self):
        self.prov = FakeProviders()
        self.arc, _ = make_arc(replies=[PLAN_BOOK], providers=self.prov)
        self.p = principal(self.arc)

    def ask(self):
        r = run(self.arc, self.p, "Book the ₦15,000 vehicle")
        self.assertEqual(r.status, "needs_confirmation")
        return r

    def test_booking_requires_confirmation_and_does_not_execute(self):
        r = self.ask()
        self.assertEqual(self.prov.booked, [])
        self.assertEqual(r.confirmation["amount"], [1500000, "NGN"])
        self.assertIn("15,000.00 NGN", r.confirmation["summary"])

    def test_confirm_executes_and_verifies_with_provider(self):
        r = self.ask()
        c = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "completed")
        self.assertEqual(len(self.prov.booked), 1)
        self.assertEqual(self.prov.booked[0][4], r.confirmation["id"], "idempotency key is the confirmation id")

    def test_wrong_step_up_does_not_execute_and_can_retry(self):
        r = self.ask()
        bad = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "0000"})
        self.assertEqual(bad.status, "denied")
        self.assertEqual(self.prov.booked, [])
        ok = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(ok.status, "completed")

    def test_no_step_up_configured_fails_closed(self):
        arc, _ = make_arc(replies=[PLAN_BOOK], providers=self.prov, step_up=None)
        p = principal(arc)
        r = run(arc, p, "book it")
        c = arc.oracle.confirm(p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "denied")
        self.assertEqual(self.prov.booked, [])

    def test_confirmation_is_single_use(self):
        r = self.ask()
        args = (self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(self.arc.oracle.confirm(*args).status, "completed")
        self.assertEqual(self.arc.oracle.confirm(*args).status, "denied")
        self.assertEqual(len(self.prov.booked), 1, "double submit must not double charge")

    def test_swapped_or_wrong_hash_rejected(self):
        r = self.ask()
        c = self.arc.oracle.confirm(self.p, r.confirmation["id"], "0" * 64, {"pin": "1234"})
        self.assertEqual(c.status, "denied")
        self.assertEqual(self.prov.booked, [])

    def test_other_user_or_app_cannot_confirm(self):
        r = self.ask()
        for other in (principal(self.arc, user="u2"), principal(self.arc, app="other", secret="s3cret-value-for-tests-1234x")):
            c = self.arc.oracle.confirm(other, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
            self.assertEqual(c.status, "denied")
        self.assertEqual(self.prov.booked, [])

    def test_revocation_between_prompt_and_confirm_blocks_execution(self):
        r = self.ask()
        self.arc.grants.revoke("concierge", "book_provider")
        c = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "denied")
        self.assertEqual(self.prov.booked, [])

    def test_agent_suspended_between_prompt_and_confirm_blocks_execution(self):
        r = self.ask()
        self.arc.agents.set_state("concierge", "suspended")
        c = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "denied")
        self.assertEqual(self.prov.booked, [])

    def test_expired_confirmation_rejected(self):
        r = self.ask()
        self.arc.broker._clock = lambda: r.confirmation["expires"] + 1
        c = self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "denied")

    def test_pending_provider_status_is_not_reported_as_success(self):
        prov = FakeProviders(final_status="pending")
        arc, _ = make_arc(replies=[PLAN_BOOK], providers=prov)
        p = principal(arc)
        r = run(arc, p, "book it")
        c = arc.oracle.confirm(p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "unverified")
        self.assertIn("couldn't verify", c.text)

    def test_provider_exception_reported_as_failed_without_leaking_details(self):
        class Broken(FakeProviders):
            def book(self, *a):
                raise RuntimeError("db password=hunter2 at 10.0.0.5")
        arc, _ = make_arc(replies=[PLAN_BOOK], providers=Broken())
        p = principal(arc)
        r = run(arc, p, "book it")
        c = arc.oracle.confirm(p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        self.assertEqual(c.status, "failed")
        self.assertNotIn("hunter2", c.text)

    def test_audit_chain_records_the_whole_story_and_verifies(self):
        r = self.ask()
        self.arc.oracle.confirm(self.p, r.confirmation["id"], r.confirmation["action_hash"], {"pin": "1234"})
        events = [e["event"] for e in self.arc.audit.events()]
        for expected in ("request.received", "confirmation.requested", "confirmation.accepted", "tool.executed"):
            self.assertIn(expected, events)
        self.assertTrue(self.arc.audit.verify())


class HonestyTests(unittest.TestCase):
    def test_without_providers_tools_are_unavailable_not_invented(self):
        arc, _ = make_arc(replies=[PLAN_SEARCH], providers=None)
        r = run(arc, principal(arc), "find transport")
        self.assertEqual(r.status, "unavailable")
        self.assertIn("Nothing was done", r.text)

    def test_model_down_is_reported_honestly(self):
        arc, model = make_arc()
        model.fail = True
        r = run(arc, principal(arc), "tell me about photosynthesis", agent="bud")
        self.assertEqual(r.status, "unavailable")
        self.assertIn("model_unavailable", r.flags)

    def test_invented_price_is_blocked(self):
        arc, _ = make_arc(replies={"chat": ["A taxi to the airport costs ₦12,500 and is available now."]})
        r = run(arc, principal(arc), "how much is a taxi to the airport?", agent="bud")
        self.assertIn("ungrounded_figures", r.flags)
        self.assertNotIn("12,500", r.text)

    def test_figure_the_user_supplied_is_allowed(self):
        arc, _ = make_arc(replies={"chat": ["You said the fee is ₦15,000, so that is what I will work with."]})
        r = run(arc, principal(arc), "the fee is ₦15,000, summarise", agent="bud")
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.flags, [])
        self.assertIn("₦15,000", r.text)

    def test_figures_helper(self):
        self.assertEqual(figures("₦15,000 and $20.50 and 3 items"), {"15000", "20.50"})

    def test_malformed_plan_falls_back_to_plain_answer(self):
        arc, _ = make_arc(replies=["not json at all", "still not json", "A normal answer."], providers=FakeProviders())
        r = run(arc, principal(arc), "tell me a joke")
        self.assertEqual(r.text, "A normal answer.")

    def test_empty_and_oversized_messages_rejected(self):
        arc, _ = make_arc()
        self.assertEqual(run(arc, principal(arc), "   ", agent="bud").status, "failed")
        self.assertEqual(run(arc, principal(arc), "x" * 9000, agent="bud").status, "failed")


class MemoryIntegrationTests(unittest.TestCase):
    def test_remembered_fact_is_used_in_context_and_sensitivity_blocks_remote(self):
        arc, model = make_arc(replies={"chat": ["Noted.", "You study civil engineering."]})
        p = principal(arc)
        arc.oracle.run(p, ArcRequest("bud", "I study civil engineering", remember=True))
        arc.oracle.run(p, ArcRequest("bud", "what do I study"))
        last = [c for c in model.calls if c.purpose == "chat"][-1]
        self.assertIn("civil engineering", last.messages[0]["content"])
        self.assertGreaterEqual(last.data_class, DataClass.PERSONAL)

    def test_other_user_does_not_see_memory(self):
        arc, model = make_arc(replies={"chat": ["Noted.", "I don't know."]})
        arc.oracle.run(principal(arc), ArcRequest("bud", "my secret code word is pelican", remember=True))
        arc.oracle.run(principal(arc, user="u2"), ArcRequest("bud", "what is the code word pelican"))
        chat_calls = [c for c in model.calls if c.purpose == "chat"]
        self.assertEqual(len(chat_calls), 2)
        self.assertNotIn("pelican", chat_calls[-1].messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
