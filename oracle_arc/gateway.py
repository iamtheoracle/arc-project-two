"""Authenticated API gateway: composes host-registered agents and capabilities."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agents import AgentRegistry
from .audit import AuditLog
from .confirmation import ConfirmationBroker
from .identity import AppRegistry
from .models import ModelGateway, OllamaBackend, OpenAICompatBackend, RoutingPolicy, UsageMeter
from .oracle import ArcRequest, Oracle
from .orbits import Orbits
from .spark import SparkMemory
from .tools import GrantTable, ToolRegistry
from .types import (ArcError, AuthError, ConfirmationError, DataClass, MediaRejected, ModelUnavailable,
                    PermissionDenied, QuotaExceeded, Risk, ToolUnavailable, ValidationError)

_STATUS = {"unauthenticated": 401, "permission_denied": 403, "invalid_request": 400, "quota_exceeded": 429,
           "model_unavailable": 503, "tool_unavailable": 503, "confirmation_failed": 403, "media_rejected": 422}
MAX_BODY = 1_000_000


class Arc:
    """Composition root. Hosts supply their own identities, agents, tools, and grants."""

    def __init__(self, backends=None, server_key=None, audit_path=":memory:", memory_path=":memory:",
                 policy: RoutingPolicy = None, step_up=None, file_roots=(), user_verifier=None,
                 app_credentials=(), agent_specs=(), tool_specs=(), tool_grants=(), control_plane=None):
        self.audit = AuditLog(audit_path)
        if control_plane is not None and app_credentials:
            raise ValueError("PostgreSQL applications must be provisioned out-of-band, not at runtime")
        if control_plane is not None and tool_grants:
            raise ValueError("PostgreSQL tool grants must be provisioned out-of-band, not at runtime")
        self.control_plane = control_plane
        self.apps = AppRegistry(server_key=server_key, user_verifier=user_verifier, store=control_plane)
        for app_id, secret, scopes in app_credentials:
            self.apps.register_app(app_id, secret, scopes=scopes)
        self.meter = UsageMeter()
        self.models = ModelGateway(backends if backends is not None else default_backends(),
                                   policy or RoutingPolicy(), self.meter)
        self.agents = AgentRegistry(self.audit, store=control_plane)
        self.tools = ToolRegistry()
        self.grants = GrantTable(self.audit, store=control_plane)
        self.memory = SparkMemory(memory_path, self.audit)
        self.broker = ConfirmationBroker(step_up=step_up)
        self.orbits = Orbits(audit=self.audit)
        self.oracle = Oracle(self.models, self.agents, self.tools, self.grants, self.memory, self.broker, self.audit)
        try:
            self._register_host_capabilities(agent_specs, tool_specs, tool_grants, file_roots)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.audit.close()
        self.memory.close()

    def _register_host_capabilities(self, agent_specs, tool_specs, tool_grants, file_roots):
        """Register only explicit host executors; PostgreSQL configuration is provisioned separately."""
        if self.control_plane is not None:
            if tool_grants or file_roots:
                raise ValueError("persistent mode accepts only separately provisioned tool grants and tool metadata")
            persisted_agents = {row["name"]: row for row in self.control_plane.list_agents()}
            supplied_agents = {spec.name: spec for spec in agent_specs}
            if set(supplied_agents) - set(persisted_agents):
                raise ValueError("host supplied an agent absent from the PostgreSQL catalogue")
            from .agents import AgentSpec
            from .types import Risk
            for name, row in persisted_agents.items():
                spec = supplied_agents.get(name)
                if spec is None:
                    spec = AgentSpec(name, row["version"], row["role"], row["system_prompt"],
                                     Risk(row["max_risk"]), tuple(row["memory_namespaces"]), state=row["state"])
                elif (spec.version != row["version"] or spec.role != row["role"]
                      or spec.system_prompt != row["system_prompt"] or int(spec.max_risk) != row["max_risk"]
                      or tuple(spec.memory_namespaces) != tuple(row["memory_namespaces"])
                      or spec.state != row["state"]):
                    raise ValueError(f"host agent configuration does not match persisted agent: {name}")
                self.agents.register(spec)

            persisted_tools = {row["name"]: row for row in self.control_plane.list_tools()}
            for spec in tool_specs:
                row = persisted_tools.get(spec.name)
                if (row is None or not row["enabled"] or row["description"] != spec.description
                        or int(row["risk"]) != int(spec.risk) or row["parameters"] != spec.parameters
                        or int(row["data_class"]) != int(spec.data_class)):
                    raise ValueError(f"host tool executor does not match enabled PostgreSQL tool metadata: {spec.name}")
                self.tools.register(spec)
            # Grants are queried from PostgreSQL on every permission check, so revocation is immediate.
            return

        for spec in tool_specs:
            self.tools.register(spec)
        if file_roots:
            from .tools.builtin import read_file_tool
            self.tools.register(read_file_tool(file_roots))
        for spec in agent_specs:
            self.agents.register(spec)
        for agent_name, tool_name in tool_grants:
            if agent_name not in self.agents.names():
                raise ValueError(f"cannot grant a tool to an unregistered agent: {agent_name}")
            if self.tools.get(tool_name) is None:
                raise ValueError(f"cannot grant an unregistered tool: {tool_name}")
            self.grants.grant(agent_name, tool_name, by="host_configuration")

    # ---- request handlers (return (http_status, body)) ------------------------------------------
    def _principal(self, headers) -> object:
        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise AuthError("missing bearer token")
        return self.apps.verify_token(auth[7:].strip())

    def handle(self, method: str, path: str, headers: dict, body: dict) -> tuple:
        try:
            if method == "GET" and path == "/v1/health":
                return 200, {"status": "ok"}
            if method == "POST" and path == "/v1/token":
                tok = self.apps.issue_token(str(body.get("app_id", "")), str(body.get("app_secret", "")),
                                            str(body.get("user_id", "")), int(body.get("ttl", 900)))
                return 200, {"token": tok}
            p = self._principal(headers)
            if method == "POST" and path == "/v1/chat":
                agent = body.get("agent")
                if not isinstance(agent, str) or not agent.strip():
                    raise ValidationError("agent is required")
                if not isinstance(body.get("message"), str):
                    raise ValidationError("message is required")
                dc = body.get("data_class", "INTERNAL")
                if dc not in DataClass.__members__:
                    raise ValidationError("unknown data_class")
                r = self.oracle.run(p, ArcRequest(agent, body["message"],
                                                  str(body.get("conversation_id", "")), bool(body.get("remember")),
                                                  DataClass[dc]))
                return 200, r.to_dict()
            if method == "POST" and path == "/v1/complete":
                agent = body.get("agent")
                if not isinstance(agent, str) or not agent.strip():
                    raise ValidationError("agent is required")
                dc = body.get("data_class", "PERSONAL")
                if dc not in DataClass.__members__:
                    raise ValidationError("unknown data_class")
                mt = body.get("max_tokens", 500)
                if not isinstance(mt, int) or isinstance(mt, bool):
                    raise ValidationError("max_tokens must be an integer")
                r = self.oracle.complete(p, agent, body.get("messages"), mt, data_class=DataClass[dc])
                return 200, r.to_dict()
            if method == "POST" and path == "/v1/confirm":
                r = self.oracle.confirm(p, str(body.get("confirmation_id", "")), str(body.get("action_hash", "")),
                                        body.get("proof") if isinstance(body.get("proof"), dict) else {})
                return 200, r.to_dict()
            if method == "POST" and path == "/v1/memory/share":
                self.memory.share(p, str(body.get("from", "")), str(body.get("to", "")))
                return 200, {"shared": True}
            if method == "POST" and path == "/v1/memory/unshare":
                self.memory.unshare(p, str(body.get("from", "")), str(body.get("to", "")))
                return 200, {"shared": False}
            if method == "GET" and path == "/v1/agents":
                return 200, {"agents": self.agents.health(), "models": self.models.status()}
            return 404, {"error": "not_found"}
        except ArcError as e:
            return _STATUS.get(e.code, 400), {"error": e.code, "message": str(e)}
        except (ValueError, TypeError):
            return 400, {"error": "invalid_request", "message": "malformed request"}
        except Exception as e:                       # never leak internals to the caller
            self.audit.append("gateway.error", error=type(e).__name__)
            return 500, {"error": "internal_error"}

    # ---- HTTP server -----------------------------------------------------------------------------
    def make_server(self, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
        arc = self

        class H(BaseHTTPRequestHandler):
            def _go(self, method):
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > MAX_BODY:
                        return self._send(413, {"error": "payload_too_large"})
                    try:
                        body = json.loads(self.rfile.read(n) or b"{}")
                        if not isinstance(body, dict):
                            raise ValueError
                    except ValueError:
                        return self._send(400, {"error": "invalid_request", "message": "body must be a JSON object"})
                self._send(*arc.handle(method, self.path.split("?")[0], dict(self.headers), body))

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

            def log_message(self, *a):
                pass

        return ThreadingHTTPServer((host, port), H)


def default_backends() -> list:
    backends = [OllamaBackend()]
    if os.environ.get("ARC_REMOTE_URL") and os.environ.get("ARC_REMOTE_MODEL"):
        backends.append(OpenAICompatBackend("remote", os.environ["ARC_REMOTE_URL"], os.environ["ARC_REMOTE_MODEL"],
                                            os.environ.get("ARC_REMOTE_KEY_ENV", "ARC_REMOTE_API_KEY"),
                                            float(os.environ.get("ARC_REMOTE_COST_PER_1K", "0"))))
    return backends
