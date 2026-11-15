import unittest
from pathlib import Path

from oracle_arc import Arc
from oracle_arc.models import ScriptedBackend
from oracle_arc.oracle import ArcRequest
from oracle_arc.tools.registry import ToolSpec
from oracle_arc.types import Risk
from oracle_arc.unibud_agents import load_unibud_agent_specs

MANIFEST = Path(__file__).parents[1] / "config" / "agents" / "unibud-51.json.bz2"


class UnibudAgentGatewayIntegrationTests(unittest.TestCase):
    def test_host_can_explicitly_register_all_51_agents_without_tools_or_memory_grants(self):
        arc = Arc([ScriptedBackend("local")], server_key=b"k" * 32,
                  agent_specs=load_unibud_agent_specs(MANIFEST))
        self.addCleanup(arc.close)
        names = arc.agents.names()
        self.assertEqual(len(names), 51)
        self.assertEqual(names[0], "unibud:academic_service")
        self.assertEqual(arc.tools.names(), [])
        self.assertFalse(arc.grants.allowed("unibud:payment_service", "payments"))
        self.assertTrue(all(arc.agents.get_active(name).max_risk == Risk.READ for name in names))
        self.assertTrue(all(arc.agents.get_active(name).memory_namespaces == () for name in names))

    def test_agent_without_grant_cannot_execute_registered_tool(self):
        calls = []
        tool = ToolSpec(name="host_probe", description="test-only probe", risk=Risk.READ,
                        parameters={"type": "object", "properties": {}},
                        executor=lambda args, ctx: calls.append("executed") or "unexpected")
        spec = load_unibud_agent_specs(MANIFEST)[0]
        arc = Arc([ScriptedBackend("local")], server_key=b"k" * 32,
                  app_credentials=(("test-host", "test-secret-123456789", ("chat",)),),
                  agent_specs=(spec,), tool_specs=(tool,), tool_grants=())
        self.addCleanup(arc.close)
        token = arc.apps.issue_token("test-host", "test-secret-123456789", "user-1")
        principal = arc.apps.verify_token(token)
        response = arc.oracle._tool_path(principal, arc.agents.get_active(spec.name), "host_probe", {},
                                         ArcRequest(spec.name, "run the probe"), [], [])
        self.assertEqual(response.status, "denied")
        self.assertEqual(calls, [])

    def test_unknown_agent_id_is_rejected(self):
        spec = load_unibud_agent_specs(MANIFEST)[0]
        arc = Arc([ScriptedBackend("local")], server_key=b"k" * 32,
                  app_credentials=(("test-host", "test-secret-123456789", ("chat",)),),
                  agent_specs=(spec,))
        self.addCleanup(arc.close)
        token = arc.apps.issue_token("test-host", "test-secret-123456789", "user-1")
        principal = arc.apps.verify_token(token)
        response = arc.oracle.run(principal, ArcRequest("unibud:unknown_agent", "hello"))
        self.assertEqual(response.status, "denied")
        self.assertIn("not available", response.text)

    def test_grant_to_unregistered_agent_is_rejected(self):
        tool = ToolSpec(name="host_probe", description="test-only probe", risk=Risk.READ,
                        parameters={"type": "object", "properties": {}},
                        executor=lambda args, ctx: "unexpected")
        with self.assertRaisesRegex(ValueError, "unregistered agent"):
            Arc([ScriptedBackend("local")], server_key=b"k" * 32,
                tool_specs=(tool,), tool_grants=(("unibud:not_registered", "host_probe"),))


if __name__ == "__main__":
    unittest.main()
