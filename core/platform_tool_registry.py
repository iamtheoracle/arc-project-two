"""Trusted, server-registered tools exposed to the platform worker.

Handlers are installed by platform code. Developer manifests can reference only
these reviewed IDs and must separately hold application, owner and worker grants.
"""
from __future__ import annotations

from core.document_retrieval import DocumentRetrievalStore
from core.plugins import PluginRegistry
from core.scoped_tool_broker import ScopedToolBroker, ToolContext, ToolDefinition
from core.tenant_security import TenantSecurityStore

PLATFORM_TOOL_IDS = frozenset({"tool.calculate", "tool.document_search"})


def build_platform_tool_broker(
    plugin_registry: PluginRegistry | None = None,
    database_path: str | None = None,
) -> ScopedToolBroker:
    plugins = plugin_registry or PluginRegistry()

    def calculate(_context: ToolContext, arguments):
        result = plugins.execute("calculate", arguments)
        return {"result": result}

    tools = [
        ToolDefinition(
            tool_id="tool.calculate",
            capability="tool.calculate",
            description="Safely evaluate a bounded mathematical expression in the isolated plugin worker.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "maxLength": 512},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            handler=calculate,
            function_name="tool_calculate",
        ),
    ]

    if database_path is not None:
        documents = DocumentRetrievalStore(database_path)
        security = TenantSecurityStore(database_path)

        def document_search(context: ToolContext, arguments):
            if not context.credential_id or context.policy_version is None:
                raise PermissionError("Document search requires the authenticated submitting credential")
            identity = security.identity_for_execution(
                context.credential_id, context.tenant_id, context.application_id,
                context.principal_id, context.policy_version,
            )
            results = documents.search(identity, arguments["query"], limit=5)
            return {
                "results": results,
                "untrusted_context": documents.format_untrusted_context(results),
            }

        tools.append(ToolDefinition(
            tool_id="tool.document_search",
            capability="tool.document_search",
            description="Search the authenticated user's permitted indexed documents and return source-attributed excerpts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 500},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=document_search,
            function_name="tool_document_search",
        ))

    return ScopedToolBroker(tools)
