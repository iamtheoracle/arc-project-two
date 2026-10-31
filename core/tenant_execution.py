"""Authorization guard for tenant-scoped agent dispatch and background execution."""
from __future__ import annotations
from typing import Any, Callable
from .tenant_identity import RequestIdentity, TenantIdentityStore
from .agent_registry import AgentRegistry, RegistryError


class TenantExecutionGuard:
    def __init__(self, identities: TenantIdentityStore):
        self.identities = identities

    def authorize(self, identity: RequestIdentity, required_capabilities: tuple[str,...]) -> RequestIdentity:
        try:
            return self.identities.validate_identity(identity, required_capabilities)
        except PermissionError as exc:
            raise PermissionError("Tenant execution authorization failed") from exc

    def dispatch_agent(self, registry: AgentRegistry, identity: RequestIdentity,
                       agent_id: str, payload: dict[str,Any],
                       required_capabilities: tuple[str,...] = ()) -> dict[str,Any]:
        self.authorize(identity, ("agent."+agent_id+".dispatch", *required_capabilities))
        return registry.dispatch_scoped(identity,agent_id,payload,required_capabilities)

    def run_background(self, identity: RequestIdentity, required_capabilities: tuple[str,...],
                       handler: Callable[...,Any], *args, **kwargs) -> Any:
        # Revalidation happens immediately before invoking the worker handler. Handlers
        # must repeat this check before any consequential external side effect.
        self.authorize(identity,required_capabilities)
        return handler(identity,*args,**kwargs)
