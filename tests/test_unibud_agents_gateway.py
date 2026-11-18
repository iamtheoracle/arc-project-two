import unittest

from oracle_arc import Arc
from oracle_arc.models import ScriptedBackend
from oracle_arc.types import Risk
from oracle_arc.unibud_agents import load_unibud_agent_specs


class UnibudAgentGatewayIntegrationTests(unittest.TestCase):
    def test_host_can_explicitly_register_all_51_agents_without_tools_or_memory_grants(self):
        arc = Arc(
            [ScriptedBackend("local")],
            server_key=b"k" * 32,
            agent_specs=load_unibud_agent_specs(),
        )
        self.addCleanup(arc.close)

        names = arc.agents.names()
        self.assertEqual(len(names), 51)
        self.assertEqual(names[0], "unibud:academic_service")
        self.assertEqual(arc.tools.names(), [])
        self.assertFalse(arc.grants.allowed("unibud:payment_service", "payments"))
        self.assertTrue(all(arc.agents.get_active(name).max_risk == Risk.READ for name in names))
        self.assertTrue(all(arc.agents.get_active(name).memory_namespaces == () for name in names))


if __name__ == "__main__":
    unittest.main()
