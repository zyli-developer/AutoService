"""KB MCP server for tenant-scoped kb_search tool exposure.

Task 2 stub — real implementation lands in Task 3.
"""
from __future__ import annotations

from typing import Any


def build_kb_mcp_server(tenant_id: str) -> dict[str, Any]:
    """Return an SDK-type MCP server config exposing kb_search to a tenant.

    See docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md §2.8.
    """
    raise NotImplementedError("build_kb_mcp_server is implemented in Task 3")
