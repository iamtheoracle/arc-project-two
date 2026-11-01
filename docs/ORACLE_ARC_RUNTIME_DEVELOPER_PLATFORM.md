# Oracle Arc Runtime and Developer Platform

## Product contract

Oracle Arc is the shared runtime and control plane for independently developed
applications and agents. A developer should be able to register an agent, bind it
to approved models and tools, publish immutable versions, submit work, inspect
usage, and recover interrupted executions without gaining access to another
application's data.

The platform separates four trust domains:

1. **Developer/application identity** — application credentials identify the tenant,
   application, principal and server-granted capabilities.
2. **Agent package** — an immutable, digest-checked manifest declares capabilities,
   tool IDs, model route IDs and a runtime ID. A manifest cannot grant itself
   permissions.
3. **Worker identity** — a separately issued, revocable worker credential is bound
   to exactly one tenant/application and a server-approved runtime set.
4. **Trusted runtime implementation** — executable code is installed and reviewed
   by the platform operator. Agent manifests do not upload, import or execute
   arbitrary developer code.

## Current API surface

All endpoints are mounted below `/v1/platform`. Application endpoints use
`Authorization: Bearer <application-credential>`.

| Operation | Endpoint | Required capability |
|---|---|---|
| Configure model route | `PUT /model-routes/{route_id}` | `model.route.manage` |
| Set application quota | `PUT /quotas` | `quota.manage` |
| Publish agent version | `POST /agents/versions` | `agent.register` |
| Read agent version | `GET /agents/{agent_id}/versions/{version}` | `agent.read` |
| Disable agent version | `DELETE /agents/{agent_id}/versions/{version}` | `agent.manage` |
| Submit execution | `POST /executions` | `agent.execute` |
| Read execution | `GET /executions/{execution_id}` | `agent.execution.read` |
| Cancel execution | `POST /executions/{execution_id}/cancel` | `agent.execution.cancel` |
| Read usage | `GET /usage?since={unix_timestamp}` | `usage.read` |
| Register worker | `POST /workers` | `worker.register` |
| Revoke worker | `DELETE /workers/{worker_id}` | `worker.manage` |

Worker endpoints use a different, one-time-issued credential:
`Authorization: Bearer arcw1.<worker-id>.<secret>`.

| Worker operation | Endpoint |
|---|---|
| Claim a compatible execution | `POST /worker/claim` |
| Extend a live lease | `POST /worker/executions/{execution_id}/heartbeat` |
| Record idempotent usage | `POST /worker/executions/{execution_id}/usage` |
| Complete a live execution | `POST /worker/executions/{execution_id}/complete` |
| Fail/retry/dead-letter a live execution | `POST /worker/executions/{execution_id}/fail` |

## Agent manifest

A published manifest has exactly these fields:

```json
{
  "display_name": "Research assistant",
  "description": "A scoped research agent",
  "required_capabilities": ["reasoning"],
  "allowed_tools": ["tool.search"],
  "model_routes": ["research-default"],
  "runtime": "oracle-arc-agent-v1"
}
```

The application identity must already possess every required capability and
tool grant. Every model route must already exist and be enabled in the same
tenant/application. Runtime IDs must be in the server-side
`ORACLE_ARC_TRUSTED_RUNTIME_IDS` allowlist (default:
`oracle-arc-agent-v1`). Developers cannot register a new executable runtime by
putting its name in a manifest.

## Worker security model

- Worker secrets are random, returned once, and stored as SHA-256 verifiers.
- A worker belongs to one tenant/application and cannot claim another application's
  tasks, even if it guesses an execution ID.
- Worker operations re-check worker revocation, expiry, tenant/application status,
  provisioning principal and active application membership.
- Immediately before execution, and again during heartbeat, metering and completion,
  the worker revalidates the exact submitting application credential, principal,
  membership, policy version, required capabilities, tool grants and model-route
  snapshot. Revocation or policy drift fences the task.
- A worker can claim only an active agent version whose runtime ID is both
  server-allowlisted and backed by a platform-installed handler.
- Heartbeats, usage writes, completion and failure require the current unexpired
  lease and exact worker ownership.
- Usage events have stable event IDs; identical retries are idempotent and
  conflicting reuse is rejected.
- Retry attempts are bounded and use capped exponential backoff. Expired leases
  are recovered only within the worker's tenant/application scope; exhausted work
  moves to the dead-letter state.
- Cancelling a running task clears its lease, fencing a late worker completion.

## Example developer sequence

1. Obtain an application credential with only the capabilities needed by the
   application (for example `agent.register`, `agent.execute`, `model.route.manage`,
   `model.route.use`, `quota.manage`, `agent.execution.read`, `usage.read`,
   `worker.register` and the specific tool grants).
2. Configure a route with an explicit provider, model ID, data classifications
   and execution regions.
3. Configure quotas before queueing any workload.
4. Publish a semantic-versioned manifest.
5. Register a worker for the approved runtime. Store its returned secret in a
   secret manager; never put it in source control or a browser client.
6. Submit work with an idempotency key.
7. The trusted worker claims only compatible work, renews its lease, reports
   idempotent usage and completes or fails it.
8. Read execution state and aggregate usage using the application credential.

## Trusted runtime execution

The repository includes a supervised polling runner:

```bash
ORACLE_ARC_DB_PATH=data/oracle_arc.sqlite3 \\
ORACLE_ARC_WORKER_TOKEN='arcw1....' \\
python -m core.platform_worker_runner
```

The installed `oracle-arc-agent-v1` runtime executes text-only workloads through
the configured local Ollama model route. It validates the message payload through
the shared model gateway, renews the lease while inference is running, records
provider token counts where available, and completes or fails the execution.
The first runtime refuses remote Ollama hosts and manifests that declare tools
until reviewed tool adapters exist. Agent publication is also restricted to
model routes supported by the installed runtime.

## Deliberate implementation boundary

This is a working **first-party local text runtime**, not a general-purpose code
hosting service or full third-party agent sandbox. Remote OpenRouter, Groq and
Gemini execution is not yet wired into this runtime. Declared tool IDs and their
permissions are validated and persisted, but the runtime refuses to invoke them
until server-installed, sandboxed adapters and per-call authorization are
implemented. There is no arbitrary developer code upload/import/execute path.
Production worker isolation, supervised deployment manifests, distributed quota
enforcement, database migration/restore drills, adversarial integration tests
and CI verification remain separate engineering gates.

No customer workload, remote provider egress, arbitrary code execution, production
deployment or external side effect is enabled.
