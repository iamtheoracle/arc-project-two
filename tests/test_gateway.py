import unittest

from oracle_arc import Arc
from oracle_arc.agents import AgentSpec
from oracle_arc.models import ScriptedBackend
from oracle_arc.tools.builtin import calculator_tool
from oracle_arc.types import Risk

KEY = b"k" * 32
SECRET = "host-app-secret-for-tests-12345"


class HostRegistrationTests(unittest.TestCase):
    def test_core_starts_without_product_agents_tools_or_grants(self):
        arc = Arc([ScriptedBackend("local")], server_key=KEY)
        self.addCleanup(arc.close)

        self.assertEqual(arc.agents.names(), [])
        self.assertEqual(arc.tools.names(), [])
        self.assertFalse(arc.grants.allowed("bud", "calculate"))
        self.assertFalse(arc.grants.allowed("concierge", "book_provider"))

    def test_host_registers_its_own_app_agent_tool_and_grant(self):
        agent = AgentSpec("research-assistant", "1.0.0", "host research assistant",
                          "Follow the host's research policy.", Risk.READ, ("research",))
        arc = Arc(
            [ScriptedBackend("local")],
            server_key=KEY,
            app_credentials=(("research-host", SECRET, ("chat",)),),
            agent_specs=(agent,),
            tool_specs=(calculator_tool(),),
            tool_grants=(("research-assistant", "calculate"),),
        )
        self.addCleanup(arc.close)

        token = arc.apps.issue_token("research-host", SECRET, "user-1")
        status, response = arc.handle(
            "POST", "/v1/chat", {"Authorization": "Bearer " + token},
            {"agent": "research-assistant", "message": "what is 6*7"},
        )
        self.assertEqual(status, 200)
        self.assertEqual((response["status"], response["text"]), ("completed", "42"))
        self.assertTrue(arc.grants.allowed("research-assistant", "calculate"))
        self.assertFalse(arc.grants.allowed("research-assistant", "book_provider"))

    def test_chat_and_complete_require_an_explicit_host_agent(self):
        arc = Arc([ScriptedBackend("local")], server_key=KEY)
        self.addCleanup(arc.close)
        arc.apps.register_app("research-host", SECRET, scopes=("chat",))
        token = arc.apps.issue_token("research-host", SECRET, "user-1")
        headers = {"Authorization": "Bearer " + token}

        chat_status, _ = arc.handle("POST", "/v1/chat", headers, {"message": "hello"})
        complete_status, _ = arc.handle(
            "POST", "/v1/complete", headers,
            {"messages": [{"role": "user", "content": "hello"}]},
        )
        self.assertEqual(chat_status, 400)
        self.assertEqual(complete_status, 400)

    def test_unknown_agent_or_tool_grants_are_rejected_at_configuration(self):
        with self.assertRaisesRegex(ValueError, "unregistered agent"):
            Arc([ScriptedBackend("local")], server_key=KEY,
                tool_specs=(calculator_tool(),), tool_grants=(("missing-agent", "calculate"),))

        with self.assertRaisesRegex(ValueError, "unregistered tool"):
            Arc([ScriptedBackend("local")], server_key=KEY,
                agent_specs=(AgentSpec("host-agent", "1.0.0", "host role", "host prompt", Risk.READ),),
                tool_grants=(("host-agent", "missing-tool"),))


if __name__ == "__main__":
    unittest.main()
