# A8 — PostgreSQL control-plane persistence

**Status:** implementation in progress; not security-approved or production-operational.  
**Migration:** `database/migrations/0001_arc_control_plane.sql`  
**SQL security test:** `database/tests/0001_arc_control_plane.test.sql`  
**Python adapter:** `oracle_arc/postgres_store.py`

## Persisted configuration

The migration creates four tables in the private `oracle_arc_private` schema:

- `applications`: app ID, scrypt salt/hash, scopes, suspension state and token epoch.
- `agents`: versioned agent definition, system prompt, risk ceiling, memory namespaces and lifecycle state.
- `tools`: tool metadata and JSON argument schema. Python executor code is never loaded from PostgreSQL.
- `tool_grants`: explicit agent/tool grant pairs with grant provenance.

The runtime gateway loads agent definitions and tool/grant metadata from PostgreSQL. The host still supplies executable Python tool handlers; each handler must match an enabled persisted tool record. Tool grants are queried from PostgreSQL at permission-check time so revocation is not held in a stale process cache.

Application tokens are verified against the persisted app salt/hash, suspension flag and token epoch. Token revocation increments the stored epoch, and the next token verification reads the current epoch.

## Database roles

- `oracle_arc_owner`: NOLOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE; owns the private schema objects and the narrow application-lookup SECURITY DEFINER function. It does not have BYPASSRLS.
- `oracle_arc_runtime`: NOLOGIN group role. It can read the agent/tool/grant catalogue under RLS and execute the narrow `get_application(text)` function. It has no direct access to application credential rows and no configuration DML.
- `oracle_arc_provisioner`: NOLOGIN group role. It can create/update application, agent, tool and grant configuration under RLS. It is separate from runtime and is not a member of owner.
- Runtime and provisioner must be attached to distinct LOGIN principals by deployment. Do not grant either group role to an end-user, browser, or public-facing client. Do not put a provisioner DSN in the HTTP runtime.

RLS is ENABLED and FORCED on all four tables. Runtime can SELECT only agents/tools/grants. Applications are accessible only through the owner-controlled lookup function. Provisioner has DML policies for controlled configuration. No policy grants runtime write access.

## Provisioning and runtime

Provisioning requires a separate instance of `PostgresControlPlane` with a provisioner DSN. The application server receives only a runtime DSN:

```python
from oracle_arc import Arc
from oracle_arc.postgres_store import PostgresControlPlane

runtime_store = PostgresControlPlane(runtime_dsn="postgresql://...runtime...")
arc = Arc(
    backends=...,
    server_key=...,
    control_plane=runtime_store,
    tool_specs=host_owned_tool_handlers,
)
```

Use the separate provisioner credential to call `provision_application`, `provision_agent`, `provision_tool`, `grant_tool`, `revoke_tool`, `set_agent_state`, and `set_tool_enabled`. Runtime mode rejects app credentials and inline grants; these must be provisioned out-of-band. Agent metadata loaded from PostgreSQL is authoritative. Tool executors remain trusted host code and must match the persisted enabled metadata.

The migration does not create LOGIN roles or database passwords. Deployment must provision separate login principals, set credentials through the secret manager, restrict network access, and grant membership only to the intended group role.

## CI verification

The Oracle Arc workflow starts PostgreSQL 16, applies migration 0001, runs SQL role/RLS assertions, then runs Python integration tests using separate runtime and provisioner login principals. CI tests do not establish a production deployment, secret-manager configuration, backup/restore, TLS, high availability, or operational monitoring.

## Known gaps before A8 can be called complete

1. The runtime application lookup function can return a credential hash for a caller-supplied app ID. The runtime DB credential is server-only, but a compromised runtime process could enumerate app IDs and retrieve hashes; consider a dedicated authentication principal or a stronger database-side credential verification protocol.
2. Agent and tool catalogue rows are global configuration. There is no tenant-specific configuration partition; if per-tenant agents/tools are needed, add an explicit tenant key and policies before enabling that scope.
3. AuditLog and SPARK memory still use SQLite. This A8 slice persists app/agent/tool/grant configuration only; it does not claim PostgreSQL persistence for audit or memory.
4. Confirmation challenges and usage-meter counters remain process-local.
5. Database connection pooling, TLS enforcement, statement timeouts, retry semantics, migrations ledger, backup/restore and concurrent multi-process integration need verification.
6. Runtime role membership, provisioner isolation and RLS must be reviewed on the production-equivalent cluster. CI uses test LOGIN principals only.
7. Production key/secret rotation and migration rollback are not yet proven.

Do not mark A8 complete until the full persistence adapter, PostgreSQL 16 CI, adversarial role tests, multi-process revocation tests and independent security review all pass.
