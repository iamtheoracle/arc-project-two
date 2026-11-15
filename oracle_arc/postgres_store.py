"""PostgreSQL-backed Oracle Arc configuration store.

The runtime DSN is read-only for application, agent, tool and grant configuration.
Provisioning mutations require a separate, privileged provisioner DSN and are never
performed by the HTTP request path.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Any


class PostgresControlPlane:
    def __init__(self, runtime_dsn: str, provisioner_dsn: str | None = None, connect=None):
        if not isinstance(runtime_dsn, str) or not runtime_dsn.strip():
            raise ValueError("a PostgreSQL runtime DSN is required")
        self.runtime_dsn = runtime_dsn
        self.provisioner_dsn = provisioner_dsn.strip() if provisioner_dsn else None
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("install psycopg to use PostgreSQL persistence") from exc
            connect = psycopg.connect
        self._connect = connect

    @classmethod
    def from_environment(cls) -> "PostgresControlPlane":
        runtime = os.environ.get("ORACLE_ARC_DATABASE_URL", "").strip()
        provisioner = os.environ.get("ORACLE_ARC_PROVISIONER_DATABASE_URL", "").strip() or None
        return cls(runtime, provisioner)

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._connect(self.runtime_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []

    def _provision(self, sql: str, params: tuple = ()) -> None:
        if not self.provisioner_dsn:
            raise PermissionError("configuration changes require a separate provisioner database credential")
        with self._connect(self.provisioner_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()

    def get_application(self, app_id: str) -> dict | None:
        rows = self._query(
            "SELECT app_id,salt,secret_hash,scopes,suspended,token_epoch "
            "FROM oracle_arc_private.get_application(%s)", (app_id,))
        if not rows:
            return None
        row = rows[0]
        return dict(app_id=row[0], salt=bytes(row[1]), secret_hash=bytes(row[2]),
                    scopes=frozenset(row[3] or ()), suspended=bool(row[4]), token_epoch=int(row[5]))

    def get_agent(self, name: str) -> dict[str, Any] | None:
        rows = self._query(
            "SELECT name,version,role,system_prompt,max_risk,memory_namespaces,state "
            "FROM oracle_arc_private.agents WHERE name=%s", (name,))
        if not rows:
            return None
        r = rows[0]
        return dict(name=r[0], version=r[1], role=r[2], system_prompt=r[3], max_risk=int(r[4]),
                    memory_namespaces=tuple(r[5] or ()), state=r[6])

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT name,version,role,system_prompt,max_risk,memory_namespaces,state "
            "FROM oracle_arc_private.agents ORDER BY name")
        return [dict(name=r[0], version=r[1], role=r[2], system_prompt=r[3], max_risk=int(r[4]),
                     memory_namespaces=tuple(r[5] or ()), state=r[6]) for r in rows]

    def list_tools(self) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT name,description,risk,parameters,data_class,enabled "
            "FROM oracle_arc_private.tools ORDER BY name")
        return [dict(name=r[0], description=r[1], risk=int(r[2]), parameters=r[3],
                     data_class=int(r[4]), enabled=bool(r[5])) for r in rows]

    def list_grants(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self._query(
            "SELECT agent_name,tool_name FROM oracle_arc_private.tool_grants ORDER BY agent_name,tool_name")]

    def has_grant(self, agent_name: str, tool_name: str) -> bool:
        rows = self._query(
            "SELECT 1 FROM oracle_arc_private.tool_grants "
            "WHERE agent_name=%s AND tool_name=%s", (agent_name, tool_name))
        return bool(rows)

    def provision_application(self, app_id: str, secret: str, scopes=()) -> None:
        if not isinstance(secret, str) or len(secret) < 16:
            raise ValueError("application secret must contain at least 16 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(secret.encode(), salt=salt, n=2 ** 12, r=8, p=1, dklen=32)
        self._provision(
            "INSERT INTO oracle_arc_private.applications(app_id,salt,secret_hash,scopes) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT(app_id) DO UPDATE SET "
            "salt=EXCLUDED.salt,secret_hash=EXCLUDED.secret_hash,scopes=EXCLUDED.scopes,"
            "suspended=false,token_epoch=oracle_arc_private.applications.token_epoch+1,"
            "updated_at=clock_timestamp()",
            (app_id, salt, digest, list(scopes)))

    def revoke_application_tokens(self, app_id: str) -> None:
        self._provision(
            "UPDATE oracle_arc_private.applications SET token_epoch=token_epoch+1,"
            "updated_at=clock_timestamp() WHERE app_id=%s", (app_id,))

    def set_application_suspended(self, app_id: str, suspended: bool) -> None:
        self._provision(
            "UPDATE oracle_arc_private.applications SET suspended=%s,"
            "token_epoch=token_epoch+1,updated_at=clock_timestamp() WHERE app_id=%s",
            (bool(suspended), app_id))

    def provision_agent(self, spec) -> None:
        self._provision(
            "INSERT INTO oracle_arc_private.agents(name,version,role,system_prompt,max_risk,memory_namespaces,state) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(name) DO UPDATE SET "
            "version=EXCLUDED.version,role=EXCLUDED.role,system_prompt=EXCLUDED.system_prompt,"
            "max_risk=EXCLUDED.max_risk,memory_namespaces=EXCLUDED.memory_namespaces,"
            "state=EXCLUDED.state,updated_at=clock_timestamp()",
            (spec.name, spec.version, spec.role, spec.system_prompt, int(spec.max_risk),
             list(spec.memory_namespaces), spec.state))

    def set_agent_state(self, name: str, state: str) -> None:
        if state not in ("active", "suspended", "retired"):
            raise ValueError("invalid agent state")
        self._provision(
            "UPDATE oracle_arc_private.agents SET state=%s,updated_at=clock_timestamp() WHERE name=%s",
            (state, name))

    def provision_tool(self, spec) -> None:
        self._provision(
            "INSERT INTO oracle_arc_private.tools(name,description,risk,parameters,data_class,enabled) "
            "VALUES (%s,%s,%s,%s::jsonb,%s,true) ON CONFLICT(name) DO UPDATE SET "
            "description=EXCLUDED.description,risk=EXCLUDED.risk,parameters=EXCLUDED.parameters,"
            "data_class=EXCLUDED.data_class,enabled=true,updated_at=clock_timestamp()",
            (spec.name, spec.description, int(spec.risk), json.dumps(spec.parameters), int(spec.data_class)))

    def set_tool_enabled(self, name: str, enabled: bool) -> None:
        self._provision(
            "UPDATE oracle_arc_private.tools SET enabled=%s,updated_at=clock_timestamp() WHERE name=%s",
            (bool(enabled), name))

    def grant_tool(self, agent_name: str, tool_name: str, granted_by: str) -> None:
        self._provision(
            "INSERT INTO oracle_arc_private.tool_grants(agent_name,tool_name,granted_by) "
            "VALUES (%s,%s,%s) ON CONFLICT(agent_name,tool_name) DO UPDATE "
            "SET granted_by=EXCLUDED.granted_by,granted_at=clock_timestamp()",
            (agent_name, tool_name, granted_by))

    def revoke_tool(self, agent_name: str, tool_name: str) -> None:
        self._provision(
            "DELETE FROM oracle_arc_private.tool_grants WHERE agent_name=%s AND tool_name=%s",
            (agent_name, tool_name))
