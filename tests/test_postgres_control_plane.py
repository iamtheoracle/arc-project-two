import os
import unittest

from oracle_arc import Arc, Risk
from oracle_arc.agents import AgentSpec
from oracle_arc.identity import AppRegistry
from oracle_arc.models import ScriptedBackend
from oracle_arc.postgres_store import PostgresControlPlane
from oracle_arc.tools.registry import ToolSpec
from oracle_arc.types import AuthError, DataClass, PermissionDenied


RUNTIME_DSN = os.environ.get("ORACLE_ARC_TEST_DATABASE_URL")
PROVISIONER_DSN = os.environ.get("ORACLE_ARC_TEST_PROVISIONER_DATABASE_URL")
KEY = b"p" * 32


@unittest.skipUnless(RUNTIME_DSN and PROVISIONER_DSN, "PostgreSQL control-plane integration DSNs are not configured")
class PostgresControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.provisioner = PostgresControlPlane(PROVISIONER_DSN, PROVISIONER_DSN)
        self.runtime = PostgresControlPlane(RUNTIME_DSN)
        self.app_id = "persisted-app"
        self.secret = "persisted-app-secret-123456"
        self.agent = AgentSpec(
            "research-assistant", "1.0.0", "Host research assistant",
            "Use only explicitly granted tools.", Risk.READ, ("research",))
        self.tool = ToolSpec(
            "read_profile", "Read an approved profile", Risk.READ,
            {"type": "object", "properties": {}},
            lambda args, ctx: {"ok": True}, data_class=DataClass.PERSONAL)

        self.provisioner.provision_application(self.app_id, self.secret, ("chat",))
        self.provisioner.provision_agent(self.agent)
        self.provisioner.provision_agent(AgentSpec(
            "ungranted-assistant", "1.0.0", "No-tool assistant",
            "Answer without tools.", Risk.READ, ()))
        self.provisioner.provision_tool(self.tool)
        self.provisioner.grant_tool(self.agent.name, self.tool.name, "founder-approved")

    def test_app_agent_tool_and_grant_configuration_survives_runtime_restart(self):
        apps = AppRegistry(server_key=KEY, store=self.runtime)
        token = apps.issue_token(self.app_id, self.secret, "user-1")
        principal = apps.verify_token(token)
        self.assertEqual((principal.app_id, principal.user_id), (self.app_id, "user-1"))

        arc = Arc([ScriptedBackend("local")], server_key=KEY,
                  control_plane=self.runtime, tool_specs=(self.tool,))
        self.addCleanup(arc.close)
        self.assertEqual(set(arc.agents.names()), {"research-assistant", "ungranted-assistant"})
        self.assertTrue(arc.grants.allowed("research-assistant", "read_profile"))
        self.assertFalse(arc.grants.allowed("ungranted-assistant", "read_profile"))
        self.assertEqual(arc.tools.names(), ["read_profile"])

    def test_app_token_epoch_revocation_is_read_from_postgres_on_each_verification(self):
        apps = AppRegistry(server_key=KEY, store=self.runtime)
        token = apps.issue_token(self.app_id, self.secret, "user-1")
        self.provisioner.revoke_application_tokens(self.app_id)
        with self.assertRaises(AuthError):
            apps.verify_token(token)

    def test_runtime_cannot_provision_or_change_tool_grants(self):
        with self.assertRaises(RuntimeError):
            AppRegistry(server_key=KEY, store=self.runtime).register_app(
                "other-app", "other-app-secret-123456", ("chat",))
        with self.assertRaises(PermissionError):
            self.runtime.grant_tool("research-assistant", "read_profile", "runtime")
        with self.assertRaises(PermissionError):
            self.runtime.provision_agent(self.agent)

    def test_runtime_arc_rejects_unpersisted_host_configuration(self):
        extra = AgentSpec("unpersisted", "1.0.0", "Extra", "Not in DB.", Risk.READ, ())
        with self.assertRaisesRegex(ValueError, "absent from the PostgreSQL catalogue"):
            Arc([ScriptedBackend("local")], server_key=KEY, control_plane=self.runtime,
                agent_specs=(extra,), tool_specs=(self.tool,))

    def test_grant_revocation_and_agent_suspension_are_visible_without_restart(self):
        arc = Arc([ScriptedBackend("local")], server_key=KEY,
                  control_plane=self.runtime, tool_specs=(self.tool,))
        self.addCleanup(arc.close)
        self.assertTrue(arc.grants.allowed("research-assistant", "read_profile"))
        self.provisioner.revoke_tool("research-assistant", "read_profile")
        self.assertFalse(arc.grants.allowed("research-assistant", "read_profile"))
        self.provisioner.set_agent_state("research-assistant", "suspended")
        with self.assertRaises(PermissionDenied):
            arc.agents.get_active("research-assistant")


if __name__ == "__main__":
    unittest.main()
