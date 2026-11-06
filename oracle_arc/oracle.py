"""ORACLE: the reasoning and execution pipeline.

request -> identify caller -> load permitted context -> understand intent (deterministic fast path,
else model) -> policy and risk -> permission check -> confirmation (if consequential) -> execute ->
verify the real result -> audit -> respond. Understanding a request never implies permission to execute
it, and success is only reported for effects that were verified.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .types import (ArcError, ChatRequest, ConfirmationError, DataClass, ModelUnavailable, PermissionDenied,
                    Principal, QuotaExceeded, Risk, ToolUnavailable, ValidationError)
from .tools.registry import validate_args
from .confirmation import action_hash

# Statuses returned to clients
ANSWERED, NEEDS_CONFIRMATION, COMPLETED = "answered", "needs_confirmation", "completed"
UNVERIFIED, FAILED, DENIED, UNAVAILABLE, QUOTA = "unverified", "failed", "denied", "unavailable", "quota_exceeded"

_FIG = re.compile(r"(?:[₦$€£]|NGN|USD|EUR|GBP)\s?\d[\d,]*(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s?(?:naira|dollars|pounds|euros)\b", re.I)


def figures(text: str) -> set:
    out = set()
    for m in _FIG.findall(text or ""):
        digits = re.sub(r"[^\d.]", "", m)
        digits = digits.rstrip(".")
        if digits:
            out.add(digits.lstrip("0") or "0")
    return out


@dataclass
class ArcRequest:
    agent: str
    message: str
    conversation_id: str = ""
    remember: bool = False
    data_class: DataClass = DataClass.INTERNAL


@dataclass
class ArcResponse:
    status: str
    text: str
    trace: list = field(default_factory=list)
    confirmation: Optional[dict] = None
    tool: Optional[str] = None
    result: Any = None
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "text": self.text, "confirmation": self.confirmation, "tool": self.tool,
                "result": self.result, "flags": self.flags}


@dataclass
class ToolContext:
    principal: Principal
    agent: str
    idempotency_key: str
    audit: Any = None


class Oracle:
    def __init__(self, gateway, agents, tools, grants, memory, broker, audit, confirm_at: Risk = Risk.WRITE,
                 max_model_calls: int = 2):
        self.gateway, self.agents, self.tools, self.grants = gateway, agents, tools, grants
        self.memory, self.broker, self.audit = memory, broker, audit
        self.confirm_at = confirm_at

    # ------------------------------------------------------------------ helpers
    def _log(self, event, p: Principal, agent: str, **detail):
        self.audit.append(event, app_id=p.app_id, user_id=p.user_id, agent=agent, **detail)

    def _available_tools(self, agent_spec) -> list:
        out = []
        for name in self.grants.tools_for(agent_spec.name):
            t = self.tools.get(name)
            if t and t.risk <= agent_spec.max_risk:
                out.append(t)
        return out

    # ------------------------------------------------------------------ main pipeline
    def run(self, p: Principal, req: ArcRequest) -> ArcResponse:
        trace = ["identified caller"]
        if not req.message or not req.message.strip() or len(req.message) > 8000:
            return ArcResponse(FAILED, "Message must be between 1 and 8000 characters.", trace)
        try:
            agent = self.agents.get_active(req.agent)
        except PermissionDenied as e:
            self._log("request.denied", p, req.agent, reason=str(e))
            return ArcResponse(DENIED, "That assistant is not available.", trace)
        self._log("request.received", p, agent.name, chars=len(req.message))

        # 1. permitted context only
        context, dclass = [], req.data_class
        for ns in agent.memory_namespaces[:1]:
            for m in self.memory.recall(p, ns, agent.memory_namespaces, req.message, k=4,
                                        scope_ids=[req.conversation_id] if req.conversation_id else []):
                context.append(m)
                dclass = max(dclass, m.data_class)
        trace.append(f"loaded {len(context)} memories")
        tools = self._available_tools(agent)

        # 2. understand: deterministic fast path first (no model call), else the model plans
        plan = self._fast_plan(req.message, tools)
        if plan:
            trace.append("fast path: " + plan["tool"])
        elif tools:
            try:
                plan = self._model_plan(p, agent, req, tools, context, dclass)
            except ModelUnavailable as e:
                return ArcResponse(UNAVAILABLE, "I can't reach a language model right now, so I can't work out "
                                                "that request. Nothing was done.", trace, flags=["model_unavailable"])
            except QuotaExceeded:
                return ArcResponse(QUOTA, "This application has used its AI allowance for now.", trace)
            if plan and plan["action"] == "tool":
                trace.append("model planned: " + str(plan.get("tool")))
        if plan and plan["action"] == "tool":
            resp = self._tool_path(p, agent, plan["tool"], plan.get("args", {}), req, trace, tools)
        else:
            resp = self._respond(p, agent, req, context, dclass, trace)
        if req.remember and resp.status in (ANSWERED, COMPLETED) and agent.memory_namespaces:
            self.memory.remember(p, agent.memory_namespaces[0], agent.memory_namespaces, req.message,
                                 scope="personal", data_class=max(dclass, DataClass.PERSONAL))
        return resp

    # ------------------------------------------------------------------ planning
    def _fast_plan(self, message: str, tools: list):
        for t in tools:
            if t.match:
                args = t.match(message)
                if args is not None:
                    return {"action": "tool", "tool": t.name, "args": args}
        return None

    def _model_plan(self, p, agent, req, tools, context, dclass):
        catalogue = [{"tool": t.name, "description": t.description, "parameters": t.parameters} for t in tools]
        system = (f"{agent.system_prompt}\nDecide whether the user's request needs one of these tools. "
                  'Reply with JSON only: {"action":"respond"} or {"action":"tool","tool":"<name>","args":{...}}. '
                  "Use a tool only when the request clearly needs it. Never invent argument values the user did "
                  "not give; if a required value is missing, reply with {\"action\":\"respond\"}.\n"
                  f"Tools: {json.dumps(catalogue)}")
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": req.message}]
        for attempt in range(2):                                   # one bounded repair attempt
            res = self.gateway.chat(ChatRequest(msgs, temperature=0.0, max_tokens=300, json_mode=True,
                                                data_class=dclass, purpose="plan"), app_id=p.app_id)
            try:
                plan = json.loads(res.text)
                if plan.get("action") == "respond":
                    return {"action": "respond"}
                if plan.get("action") == "tool" and isinstance(plan.get("tool"), str):
                    return {"action": "tool", "tool": plan["tool"], "args": plan.get("args") or {}}
            except (ValueError, AttributeError):
                pass
            msgs.append({"role": "assistant", "content": res.text})
            msgs.append({"role": "user", "content": 'That was not valid. Reply with JSON only.'})
        return {"action": "respond"}

    # ------------------------------------------------------------------ plain response
    def _respond(self, p, agent, req, context, dclass, trace):
        facts = "\n".join(f"- {m.content}" for m in context)
        system = agent.system_prompt + ("\nKnown about this user (from memory):\n" + facts if facts else "") + (
            "\nNever state prices, balances, availability, order status or payment outcomes unless they appear "
            "in the conversation or memory above. If you do not know, say so.")
        try:
            res = self.gateway.chat(ChatRequest([{"role": "system", "content": system},
                                                 {"role": "user", "content": req.message}],
                                                data_class=dclass), app_id=p.app_id)
        except ModelUnavailable:
            return ArcResponse(UNAVAILABLE, "I can't reach a language model right now. Nothing was done.", trace,
                               flags=["model_unavailable"])
        except QuotaExceeded:
            return ArcResponse(QUOTA, "This application has used its AI allowance for now.", trace)
        evidence = req.message + " " + facts
        return self._grounded(res.text, evidence, trace)

    def _grounded(self, text: str, evidence: str, trace: list, status: str = ANSWERED) -> ArcResponse:
        bad = figures(text) - figures(evidence)
        if bad:
            trace.append("blocked ungrounded figures")
            return ArcResponse(status, "I can't state specific amounts that I haven't been given by a verified "
                                       "source, so I've left them out. Ask a connected service for a quote.",
                               trace, flags=["ungrounded_figures"])
        return ArcResponse(status, text, trace)

    # ------------------------------------------------------------------ tool path
    def _tool_path(self, p, agent, tool_name, args, req, trace, available) -> ArcResponse:
        spec = self.tools.get(tool_name)
        if not spec or tool_name not in {t.name for t in available} or not self.grants.allowed(agent.name, tool_name):
            self._log("tool.denied", p, agent.name, tool=tool_name, reason="not granted")
            return ArcResponse(DENIED, "I'm not permitted to do that.", trace, tool=tool_name)
        try:
            validate_args(spec.parameters, args)
        except ValidationError as e:
            self._log("tool.invalid_args", p, agent.name, tool=tool_name, reason=str(e))
            return ArcResponse(FAILED, f"I couldn't use {tool_name}: {e}.", trace, tool=tool_name)
        if spec.risk >= self.confirm_at:
            summary = spec.describe(args) if spec.describe else f"Run {tool_name} with {json.dumps(args)}"
            ch = self.broker.create(p, agent.name, tool_name, args, summary, spec.risk)
            self._log("confirmation.requested", p, agent.name, tool=tool_name, id=ch.id, risk=int(spec.risk))
            trace.append("awaiting confirmation")
            return ArcResponse(NEEDS_CONFIRMATION, f"Please confirm: {summary}.", trace, tool=tool_name,
                               confirmation={"id": ch.id, "action_hash": ch.action_hash, "summary": summary,
                                             "risk": spec.risk.name, "expires": ch.expires,
                                             "amount": list(spec.amount(args)) if spec.amount else None})
        return self._execute(p, agent, spec, args, trace, idem=uuid.uuid4().hex)

    def _execute(self, p, agent, spec, args, trace, idem: str) -> ArcResponse:
        ctx = ToolContext(p, agent.name, idem, self.audit)
        try:
            result = spec.executor(args, ctx)
        except ToolUnavailable as e:
            self._log("tool.unavailable", p, agent.name, tool=spec.name)
            return ArcResponse(UNAVAILABLE, f"{spec.name} isn't available because no connected service supports it "
                                            "yet. Nothing was done.", trace, tool=spec.name)
        except ValidationError as e:
            self._log("tool.rejected", p, agent.name, tool=spec.name, reason=str(e))
            return ArcResponse(FAILED, f"I couldn't complete that: {e}.", trace, tool=spec.name)
        except Exception as e:
            self._log("tool.error", p, agent.name, tool=spec.name, error=type(e).__name__)
            return ArcResponse(FAILED, "That action failed. Nothing was confirmed.", trace, tool=spec.name,
                               flags=["execution_error"])
        trace.append("executed")
        try:
            verified = bool(spec.verifier(args, result, ctx)) if spec.verifier else spec.risk == Risk.READ
        except Exception:
            verified = False
        self._log("tool.executed", p, agent.name, tool=spec.name, verified=verified, risk=int(spec.risk))
        if not verified:
            trace.append("could not verify")
            return ArcResponse(UNVERIFIED, "I attempted that, but I couldn't verify that it actually completed. "
                                           "Please check before relying on it.", trace, tool=spec.name,
                               result=None, flags=["unverified"])
        trace.append("verified")
        text = f"{result}" if not isinstance(result, (dict, list)) else json.dumps(result, ensure_ascii=False)
        return ArcResponse(COMPLETED, text, trace, tool=spec.name, result=result)

    # ------------------------------------------------------------------ raw completion
    def complete(self, p: Principal, agent_name: str, messages: list, max_tokens: int = 500,
                 temperature: float = 0.4, data_class: DataClass = DataClass.PERSONAL) -> ArcResponse:
        """Governed text completion for hosts that build their own prompts (e.g. Bud in UNIBUD).

        No tools are executed and nothing is remembered; the call is still authenticated, quota-metered,
        privacy-routed (data class decides whether a remote model may see it) and audited (sizes only,
        never content).
        """
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 60 or
                not all(isinstance(m, dict) and m.get("role") in ("system", "user", "assistant") and
                        isinstance(m.get("content"), str) for m in messages)):
            return ArcResponse(FAILED, "messages must be 1-60 items with role system|user|assistant.")
        if sum(len(m["content"]) for m in messages) > 120_000 or not 1 <= max_tokens <= 4000:
            return ArcResponse(FAILED, "request too large.")
        try:
            agent = self.agents.get_active(agent_name)
        except PermissionDenied as e:
            self._log("complete.denied", p, agent_name, reason=str(e))
            return ArcResponse(DENIED, "That assistant is not available.")
        self._log("complete.requested", p, agent.name, messages=len(messages), data_class=int(data_class))
        try:
            res = self.gateway.chat(ChatRequest([{"role": m["role"], "content": m["content"]} for m in messages],
                                                temperature=temperature, max_tokens=max_tokens,
                                                data_class=data_class, purpose="complete"), app_id=p.app_id)
        except ModelUnavailable:
            return ArcResponse(UNAVAILABLE, "No language model is reachable right now.", flags=["model_unavailable"])
        except QuotaExceeded:
            return ArcResponse(QUOTA, "This application has used its AI allowance for now.")
        if not res.text.strip():
            return ArcResponse(FAILED, "The model returned an empty reply.", flags=["empty_reply"])
        return ArcResponse(ANSWERED, res.text, result={"backend": res.backend, "model": res.model,
                                                         "tokens": res.prompt_tokens + res.completion_tokens,
                                                         "cached": res.cached})

    # ------------------------------------------------------------------ confirmation path
    def confirm(self, p: Principal, challenge_id: str, echoed_hash: str, proof: dict = None) -> ArcResponse:
        trace = ["confirmation received"]
        try:
            ch = self.broker.consume(p, challenge_id, echoed_hash, proof)
        except ConfirmationError as e:
            self.audit.append("confirmation.rejected", app_id=p.app_id, user_id=p.user_id, id=challenge_id,
                              reason=str(e))
            return ArcResponse(DENIED, f"Confirmation failed: {e}.", trace)
        # Re-check everything at execution time: grants, agent state, arguments may have changed since the prompt.
        try:
            agent = self.agents.get_active(ch.agent)
        except PermissionDenied:
            self._log("confirmation.blocked", p, ch.agent, tool=ch.tool, reason="agent not active")
            return ArcResponse(DENIED, "That assistant is no longer available. Nothing was done.", trace)
        spec = self.tools.get(ch.tool)
        if not spec or not self.grants.allowed(agent.name, ch.tool) or spec.risk > agent.max_risk:
            self._log("confirmation.blocked", p, agent.name, tool=ch.tool, reason="permission revoked")
            return ArcResponse(DENIED, "That action is no longer permitted. Nothing was done.", trace)
        try:
            validate_args(spec.parameters, ch.args)
        except ValidationError as e:
            return ArcResponse(FAILED, f"Invalid action: {e}.", trace)
        self._log("confirmation.accepted", p, agent.name, tool=ch.tool, id=ch.id)
        return self._execute(p, agent, spec, ch.args, trace, idem=ch.id)
