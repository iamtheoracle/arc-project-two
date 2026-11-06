"""Concierge service coordination tools.

These are *contracts*. Without a real provider adapter they raise ToolUnavailable; they never invent
providers, prices, availability or booking outcomes. Concierge may search and quote, and may book only
after explicit confirmation and verification against the provider.
"""
from __future__ import annotations

from typing import Protocol

from ..types import Risk, ToolUnavailable
from .registry import ToolSpec


class ProviderAdapter(Protocol):
    def search(self, query: str) -> list: ...                       # -> [{"provider_id", "name", ...}]
    def quote(self, provider_id: str, request: str) -> dict: ...    # -> {"quote_id", "amount_minor", "currency", ...}
    def book(self, provider_id: str, quote_id: str, amount_minor: int, currency: str,
             idempotency_key: str) -> dict: ...                      # -> {"booking_ref", "status"}
    def status(self, booking_ref: str) -> str: ...                  # -> "confirmed" | "pending" | "failed"


def _need(adapter):
    if adapter is None:
        raise ToolUnavailable("no service provider is connected", tool="concierge")
    return adapter


def make_concierge_tools(adapter=None) -> list:
    def search(args, ctx):
        return _need(adapter).search(args["query"])

    def quote(args, ctx):
        return _need(adapter).quote(args["provider_id"], args["request"])

    def book(args, ctx):
        return _need(adapter).book(args["provider_id"], args["quote_id"], args["amount_minor"],
                                   args["currency"], ctx.idempotency_key)

    def verify_book(args, result, ctx):
        # Success is only what the provider reports, not what the call returned.
        return bool(result and result.get("booking_ref")) and _need(adapter).status(result["booking_ref"]) == "confirmed"

    def money(args):
        return f"{args['amount_minor'] / 100:,.2f} {args['currency']}"

    return [
        ToolSpec("search_providers", "Search service providers.", Risk.READ,
                 {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}, search),
        ToolSpec("request_quote", "Request a provider quotation.", Risk.READ,
                 {"type": "object", "required": ["provider_id", "request"],
                  "properties": {"provider_id": {"type": "string"}, "request": {"type": "string"}}}, quote),
        ToolSpec("book_provider", "Book a quoted service and pay for it.", Risk.FINANCIAL,
                 {"type": "object", "required": ["provider_id", "quote_id", "amount_minor", "currency"],
                  "properties": {"provider_id": {"type": "string"}, "quote_id": {"type": "string"},
                                 "amount_minor": {"type": "integer", "minimum": 1, "maximum": 10**12},
                                 "currency": {"type": "string", "enum": ["NGN", "USD", "GBP", "EUR"]}}},
                 book, verifier=verify_book,
                 describe=lambda a: f"Book provider {a['provider_id']} (quote {a['quote_id']}) and charge {money(a)}",
                 amount=lambda a: (a["amount_minor"], a["currency"])),
    ]
