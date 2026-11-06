"""Authenticated API gateway: wires the system together and exposes it over HTTP."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agents import AgentRegistry, AgentSpec
from .audit import AuditLog
from .confirmation import ConfirmationBroker
from .identity import AppRegistry
from .models import ModelGateway, OllamaBackend, OpenAICompatBackend, RoutingPolicy, UsageMeter
from .oracle import ArcRequest, Oracle
from .orbits import Orbits
from .spark import SparkMemory
from .tools import GrantTable, ToolRegistry
from .tools.builtin import calculator_tool
from .tools.concierge import make_concierge_tools
from .types import (ArcError, AuthError, ConfirmationError, DataClass, MediaRejected, ModelUnavailable,
                    PermissionDenied, QuotaExceeded, Risk, ToolUnavailable, ValidationError)

_STATUS = {"unauthenticated": 401, "permission_denied": 403, "invalid_request": 400, "quota_exceeded": 429,
           "model_unavailable": 503, "tool_unavailable": 503, "confirmation_failed": 403, "media_rejected": 422}
MAX_BODY = 1_000_000

BUD_PROMPT = ("You are Bud, UNIBUD's conversational learning companion. Be accurate and concise. Never invent "
              "facts, prices, balances, availability or outcomes.")
CONCIERGE_PROMPT = ("You are Concierge, UNIBUD's service coordinator. You can search providers and request quotes. "
                    "You cannot take payment without the user's explicit confirmation.")


class Arc:
    """Composition root. Everything is injectable so tests and hosts can replace any part."""

    def __init__(self, backends=None, providers=None, server_key=None, audit_path=":memory:", memory_path=":memory:",
                 policy: RoutingPolicy = None, step_up=None, file_roots=(), user_verifier=None):
        self.audit = AuditLog(audit_path)
        self.apps = AppRegistry(server_key=server_key, user_verifier=user_verifier)
        self.meter = UsageMeter()
        self.models = ModelGateway(backends if backends is not None else default_backends(),
                                   policy or RoutingPolicy(), self.meter)
        self.agents = AgentRegistry(self.audit)
        self.tools = ToolRegistry()
        self.grants = GrantTable(self.audit)
        self.memory = SparkMemory(memory_path, self.audit)
        self.broker = ConfirmationBroker(step_up=step_up)
        self.orbits = Orbits(audit=self.audit)
        self.oracle = Oracle(self.models, self.agents, self.tools, self.grants, self.memory, self.broker, self.audit)
        self._install_defaults(providers, file_roots)

    def close(self) -> None:
        self.audit.close()
        self.memory.close()

    def _install_defaults(self, providers, file_roots):
        self.tools.register(calculator_tool())
        for t in make_concierge_tools(providers):
            self.tools.register(t)
        if file_roots:
            from .tools.builtin import read_file_tool
            self.tools.register(read_file_tool(file_roots))
        self.agents.register(AgentSpec("bud", "1.0.0", "general assistant", BUD_PROMPT, Risk.READ, ("bud",),
                                       health_check=lambda: True))
        self.agents.register(AgentSpec("concierge", "1.0.0", "service coordination", CONCIERGE_PROMPT,
                                       Risk.FINANCIAL, ("concierge",), health_check=lambda: True))
        for tool in ("calculate",):
            self.grants.grant("bud", tool)
            self.grants.grant("concierge", tool)
        for tool in ("search_providers", "request_quote", "book_provider"):
            self.grants.grant("concierge", tool)

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
                if not isinstance(body.get("message"), str):
                    raise ValidationError("message is required")
                dc = body.get("data_class", "INTERNAL")
                if dc not in DataClass.__members__:
                    raise ValidationError("unknown data_class")
                r = self.oracle.run(p, ArcRequest(str(body.get("agent", "bud")), body["message"],
                                                  str(body.get("conversation_id", "")), bool(body.get("remember")),
                                                  DataClass[dc]))
                return 200, r.to_dict()
            if method == "POST" and path == "/v1/complete":
                dc = body.get("data_class", "PERSONAL")
                if dc not in DataClass.__members__:
                    raise ValidationError("unknown data_class")
                mt = body.get("max_tokens", 500)
                if not isinstance(mt, int) or isinstance(mt, bool):
                    raise ValidationError("max_tokens must be an integer")
                r = self.oracle.complete(p, str(body.get("agent", "bud")), body.get("messages"), mt,
                                         data_class=DataClass[dc])
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
