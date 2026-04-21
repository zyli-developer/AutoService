"""In-process SDK-type MCP server exposing kb_search to tenant-scoped CC instances.

Design rationale and tenant isolation guarantees: see
docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md §2.8.

Tenant isolation: build_kb_mcp_server(tenant_id) returns a fresh server
instance whose kb_search handler closes over the given tenant_id. The
agent can only query that tenant's KB — any tenant_id it tries to pass
in the tool args is discarded by _run_kb_search.
"""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from autoservice.dream_agent import kb_search as _kb_search


_MAX_TOP_K = 5
_DEFAULT_TOP_K = 3


async def _run_kb_search(tenant_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a tenant-scoped KB search and format the result as MCP content.

    tenant_id comes from the caller (closure in build_kb_mcp_server); args
    comes from the agent. Any tenant_id the agent tries to smuggle via
    args is deliberately ignored.
    """
    query = (args.get("query") or "").strip()
    top_k = min(int(args.get("top_k", _DEFAULT_TOP_K)), _MAX_TOP_K)

    if not query:
        return {"content": [{"type": "text", "text": "No results (empty query)."}]}

    rows = _kb_search(tenant_id=tenant_id, query=query, top_k=top_k)
    if not rows:
        return {
            "content": [{
                "type": "text",
                "text": "No KB matches. Escalate if this is essential.",
            }],
        }

    lines: list[str] = []
    for i, row in enumerate(rows, 1):
        source = row.get("source_name") or ""
        section = row.get("section") or ""
        header = f"[{i}]"
        if source:
            header += f" {source}"
        if section:
            header += f" \u00b7 {section}"
        lines.append(header)
        lines.append((row.get("content") or "").strip())
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines).strip()}]}


def build_kb_mcp_server(tenant_id: str) -> Any:
    """Build an in-process MCP server scoped to *tenant_id*.

    Returns the McpSdkServerConfig to plug into ClaudeAgentOptions.mcp_servers.
    """

    @tool(
        "kb_search",
        (
            "Search this tenant's knowledge base. Use when the pre-fetched "
            "<kb_context> block is insufficient to answer the customer."
        ),
        {"query": str, "top_k": int},
    )
    async def kb_search_tool(args: dict[str, Any]) -> dict[str, Any]:
        return await _run_kb_search(tenant_id, args)

    return create_sdk_mcp_server(
        name="autoservice_kb",
        version="1.0.0",
        tools=[kb_search_tool],
    )
