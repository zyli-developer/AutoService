"""Tests for build_kb_mcp_server — tenant-scoped KB MCP server factory."""
from __future__ import annotations

from unittest.mock import patch

import mcp.types as mcp_types
import pytest

from autoservice.kb_mcp_server import (
    build_kb_mcp_server,
    _run_kb_search,
    _MAX_TOP_K,
)


def test_server_has_correct_name():
    """Factory returns an MCP server config named 'autoservice_kb'."""
    server = build_kb_mcp_server("acme")
    # McpSdkServerConfig may expose name as attribute or via __getitem__; tolerate both
    name = getattr(server, "name", None) or (
        server.get("name") if hasattr(server, "get") else None
    )
    assert name == "autoservice_kb"


@pytest.mark.asyncio
async def test_server_exposes_kb_search_tool():
    """Server has a single tool named kb_search."""
    server = build_kb_mcp_server("acme")
    instance = server["instance"]
    list_handler = instance.request_handlers[mcp_types.ListToolsRequest]
    result = await list_handler(mcp_types.ListToolsRequest(method="tools/list"))
    tools = list(result.root.tools)
    assert len(tools) == 1
    assert tools[0].name == "kb_search"


@pytest.mark.asyncio
async def test_run_kb_search_uses_closure_tenant_id():
    """_run_kb_search must forward the closure tenant_id to dream_agent.kb_search.

    Even if the agent tries to smuggle a tenant_id arg, it's ignored —
    _run_kb_search signature takes tenant_id as a positional param from
    the closure, not from args.
    """
    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = [
            {"content": "DID info", "source_name": "faq", "section": "DID"},
        ]
        result = await _run_kb_search(
            "acme", {"query": "DID", "top_k": 3, "tenant_id": "evil"},
        )

    kb.assert_called_once_with(tenant_id="acme", query="DID", top_k=3)
    # Result is MCP-shaped with content list
    assert "content" in result
    assert isinstance(result["content"], list)
    assert result["content"][0]["type"] == "text"
    # The KB hit content ends up in the text
    assert "DID info" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_run_kb_search_clamps_top_k():
    """top_k > _MAX_TOP_K must be clamped."""
    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = []
        await _run_kb_search("acme", {"query": "test", "top_k": 99})

    kb.assert_called_once()
    assert kb.call_args.kwargs["top_k"] == _MAX_TOP_K


@pytest.mark.asyncio
async def test_run_kb_search_empty_query_short_circuits():
    """Empty or whitespace query returns the no-results message without
    calling kb_search."""
    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        result = await _run_kb_search("acme", {"query": ""})

    kb.assert_not_called()
    assert "content" in result
    assert result["content"][0]["type"] == "text"


@pytest.mark.asyncio
async def test_run_kb_search_no_hits_returns_informative_text():
    """When kb_search returns empty list, the tool reports no matches
    (so the agent knows to escalate rather than stay silent)."""
    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = []
        result = await _run_kb_search("acme", {"query": "unknown thing"})

    text = result["content"][0]["text"].lower()
    # Some "no match / no results / empty" phrasing — don't over-specify
    assert any(kw in text for kw in ("no ", "match", "empty", "not found"))


@pytest.mark.asyncio
async def test_build_server_handler_delegates_to_run_kb_search():
    """Invoking the kb_search tool via the SDK's CallToolRequest handler
    must delegate to _run_kb_search with the closure tenant_id and ignore
    any tenant_id the agent tries to pass in the tool args."""
    server = build_kb_mcp_server("acme")
    instance = server["instance"]
    call_handler = instance.request_handlers[mcp_types.CallToolRequest]

    with patch("autoservice.kb_mcp_server._run_kb_search") as run:
        async def _fake(*args, **kwargs):
            return {"content": [{"type": "text", "text": "ok"}]}

        run.side_effect = _fake
        params = mcp_types.CallToolRequestParams(
            name="kb_search",
            arguments={"query": "x", "top_k": 1, "tenant_id": "evil"},
        )
        req = mcp_types.CallToolRequest(method="tools/call", params=params)
        await call_handler(req)

    run.assert_called_once()
    # First positional arg is the tenant_id captured at build time
    args = run.call_args.args
    assert args[0] == "acme"
    # Second positional arg is the args dict from the agent
    assert args[1].get("query") == "x"
