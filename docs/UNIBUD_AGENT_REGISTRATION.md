# UNIBUD 51-agent registration in Oracle Arc

## Source and provenance

The founder supplied `unibud-agents-51.zip` for this integration. Its SHA-256 is `77ed05b3595c086f7778588dea132d62bd67f0c4e3d76202093dd117b08fcf79`. The archive's typed registry declares exactly 51 definitions: 16 core, 10 specialist, and 25 service. Its five baseline registry tests passed. TypeScript typecheck passed after the environment's existing `@types/node` definitions were made available; a clean dependency install could not be completed because npm registry access timed out.

Oracle Arc checks in the generated registry snapshot at `oracle_arc/agent_catalogues/unibud-51.json.bz2`. The snapshot SHA-256 is verified by the loader before decompression, and the loader independently validates category counts, unique IDs, required fields, and collaborator references. The TypeScript package remains a separate UNIBUD package; its internal runtime is not imported into Oracle Arc.

## Ownership and boundary

Oracle Arc remains an independent AI core. UNIBUD agents are not built into Oracle Arc by default. A UNIBUD host explicitly supplies the definitions through `oracle_arc.unibud_agents.load_unibud_agent_specs()`.

## Registration

```python
from oracle_arc import Arc
from oracle_arc.unibud_agents import load_unibud_agent_specs

arc = Arc(
    agent_specs=load_unibud_agent_specs(),
    # app_credentials, tool_specs, and tool_grants remain explicit host inputs.
)
```

The bridge namespaces IDs as `unibud:<original-id>` and maps all 51 definitions as read-only `AgentSpec` records. The original IDs and display names remain in the catalogue and system prompts. Namespacing prevents collisions with Oracle Arc's own subsystems.

## Default restrictions

Every mapped `AgentSpec` is capped at `Risk.READ`, has no SPARK memory namespaces, and receives no tools or grants. Catalogue capabilities and collaborator links are metadata only. They do not prove that a provider, external service, integration, or other agent is available. A host must separately supply a real tool, explicit per-agent grant, authorization, consequential-action confirmation, and result verification before an action can occur.

The package's UNIBUD `spark`, `oracle`, and `orbit` entries are registered only as `unibud:spark`, `unibud:oracle`, and `unibud:orbit`. They do not replace Oracle Arc SPARK (user-controlled memory), ORACLE (reasoning and tools), or ORBITS (controlled media). The bridge does not invoke the package's internal orchestration runtime from Oracle Arc.

## Verification

The uploaded package's scripts are `npm run typecheck` and `npm test`. Node.js 22.16 was used for the run. The package's test runner uses `--experimental-strip-types`, so its `engines.node` declaration of `>=20` is too broad; a compatible minimum is Node.js 22.6.0 or later. The archive itself was not modified in this integration. The Oracle Arc adapter tests are in `tests/test_unibud_agents.py`.
