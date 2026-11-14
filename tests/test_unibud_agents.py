import bz2
import json
import tempfile
import unittest
from pathlib import Path

from oracle_arc.agents import AgentRegistry
from oracle_arc.types import Risk
from oracle_arc.unibud_agents import load_unibud_agent_specs


class UnibudAgentHostRegistrationTests(unittest.TestCase):
    def test_all_51_definitions_map_to_namespaced_read_only_agents(self):
        specs = load_unibud_agent_specs()
        self.assertEqual(len(specs), 51)
        self.assertEqual(len({spec.name for spec in specs}), 51)
        self.assertTrue(all(spec.name.startswith("unibud:") for spec in specs))
        self.assertTrue(all(spec.max_risk == Risk.READ for spec in specs))
        self.assertTrue(all(spec.memory_namespaces == () for spec in specs))
        self.assertIn("Declared catalogue capabilities (not connected", specs[0].system_prompt)

    def test_spark_oracle_and_orbit_names_are_scoped_away_from_arc_subsystems(self):
        specs = {spec.name: spec for spec in load_unibud_agent_specs()}
        self.assertIn("not Oracle Arc SPARK", specs["unibud:spark"].system_prompt)
        self.assertIn("not Oracle Arc ORACLE", specs["unibud:oracle"].system_prompt)
        self.assertIn("not Oracle Arc ORBITS", specs["unibud:orbit"].system_prompt)

    def test_arc_agent_registry_accepts_all_51_host_supplied_specs(self):
        registry = AgentRegistry()
        for spec in load_unibud_agent_specs():
            registry.register(spec)
        names = registry.names()
        self.assertEqual(len(names), 51)
        self.assertEqual(names[0], "unibud:academic_service")
        self.assertEqual(registry.get_active("unibud:payment_service").max_risk, Risk.READ)

    def test_invalid_manifest_fails_closed(self):
        manifest = Path(__file__).parents[1] / "oracle_arc/agent_catalogues/unibud-51.json.bz2"
        valid = json.loads(bz2.decompress(manifest.read_bytes()))
        valid.pop()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.json"
            path.write_text(json.dumps(valid))
            with self.assertRaisesRegex(ValueError, "exactly 51"):
                load_unibud_agent_specs(path)


if __name__ == "__main__":
    unittest.main()
