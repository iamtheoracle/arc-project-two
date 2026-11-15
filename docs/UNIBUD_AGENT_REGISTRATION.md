# UNIBUD 51-agent registration in Oracle Arc

## Source and provenance
The founder-supplied `unibud-agents-51.zip` archive (SHA-256 `77ed05b3595c086f7778588dea132d62bd67f0c4e3d76202093dd117b08fcf79`) contains exactly 51 definitions: 16 core, 10 specialist and 25 service. Its package tests passed 5/5; typecheck passed after environment-provided Node typings were made available. A clean npm dependency install was not verified because registry access timed out.

## Host-owned configuration
Definitions live outside the `oracle_arc/` package at `config/agents/unibud-51.json.bz2`. The Oracle Arc adapter contains validation and mapping logic only. It has no default manifest path: the embedding host must explicitly supply the configuration path.

```python
from pathlib import Path
from oracle_arc import Arc
from oracle_arc.unibud_agents import load_unibud_agent_specs

agent_specs = load_unibud_agent_specs(Path("config/agents/unibud-51.json.bz2"))
arc = Arc(agent_specs=agent_specs)
```

UNIBUD registrations are opt-in. No product agents are installed by default.

## Identity and authorization boundary
The bridge names agents `unibud:<original-id>`. Every agent receives `Risk.READ`, no SPARK memory namespaces, no tools and no grants. Registry capability labels and collaborator references are metadata only; they are not permissions and do not create tools or delegation. A host must separately register a real tool and grant it to a registered agent through explicit configuration and authorization.

UNIBUD `spark`, `oracle` and `orbit` are distinct from Oracle Arc SPARK (user-controlled memory), ORACLE (reasoning/tools) and ORBITS (controlled media). The adapter does not import the package orchestration runtime.
