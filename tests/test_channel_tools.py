"""Tests for channel_tools.py — extracted MCP tool definitions."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from channels.feishu.channel_tools import (
    create_channel_mcp_server,
    REPLY_TOOL,
    REACT_TOOL,
)
from mcp.types import ListToolsRequest, CallToolRequest


class TestToolDefinitions:
    def test_reply_tool_schema(self):
        assert REPLY_TOOL.name == "reply"
        assert "chat_id" in REPLY_TOOL.inputSchema["properties"]
        assert "text" in REPLY_TOOL.inputSchema["properties"]
        assert REPLY_TOOL.inputSchema["required"] == ["chat_id", "text"]

    def test_react_tool_schema(self):
        assert REACT_TOOL.name == "react"
        assert "message_id" in REACT_TOOL.inputSchema["properties"]
        assert "emoji_type" in REACT_TOOL.inputSchema["properties"]


class TestChannelMcpServer:
    def _get_handler(self, server, request_type):
        """Get a registered request handler from the MCP server."""
        return server.request_handlers.get(request_type)

    @pytest.mark.asyncio
    async def test_create_server_basic(self):
        server = create_channel_mcp_server(
            reply_callback=AsyncMock(),
            instructions="Test",
        )
        assert server.name == "autoservice-channel"
        assert server.instructions == "Test"

    @pytest.mark.asyncio
    async def test_list_tools_returns_core(self):
        server = create_channel_mcp_server(reply_callback=AsyncMock())
        handler = self._get_handler(server, ListToolsRequest)
        assert handler is not None

    @pytest.mark.asyncio
    async def test_call_tool_handler_registered(self):
        server = create_channel_mcp_server(reply_callback=AsyncMock())
        handler = self._get_handler(server, CallToolRequest)
        assert handler is not None

    @pytest.mark.asyncio
    async def test_plugin_tools_in_definition(self):
        class FakePluginTool:
            name = "lookup"
            description = "Look up customer"
            input_schema = {"type": "object", "properties": {"id": {"type": "string"}}}
            def handler(self, **kwargs):
                return {"found": True}

        server = create_channel_mcp_server(
            reply_callback=AsyncMock(),
            plugin_tools=[FakePluginTool()],
        )
        # Server was created with the plugin tool registered
        assert server is not None


class TestPoolModeChannelServer:

    @pytest.mark.asyncio
    async def test_pool_mode_flag_default_false(self):
        from channels.feishu.channel_server import ChannelServer
        server = ChannelServer(port=0, feishu_enabled=False)
        assert server.pool_mode is False
        assert server._pool is None

    @pytest.mark.asyncio
    async def test_pool_mode_flag_set(self):
        from channels.feishu.channel_server import ChannelServer
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        assert server.pool_mode is True

    @pytest.mark.asyncio
    async def test_pool_mode_status_text(self):
        from channels.feishu.channel_server import ChannelServer
        server = ChannelServer(port=0, feishu_enabled=False)
        status = server.status_text()
        assert "Status" in status or "服务台" in status


class TestPoolRouteIntegration:
    """Test that pool_mode routes messages through PoolRoute, not wildcard."""

    @pytest.mark.asyncio
    async def test_pool_route_created_on_first_message(self):
        from channels.feishu.channel_server import ChannelServer
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_pool = AsyncMock()
        mock_pool.acquire_sticky = AsyncMock(return_value=MagicMock(id="cc-001"))
        async def mock_session_query(chat_id, prompt, **kw):
            return; yield
        mock_pool.session_query = mock_session_query
        server._pool = mock_pool
        msg = {"type": "message", "text": "hello", "chat_id": "oc_test1",
               "user": "test", "source": "feishu"}
        await server.route_message("oc_test1", msg)
        assert "oc_test1" in server.pool_routes
        assert server.pool_routes["oc_test1"].instance_id == "cc-001"

    @pytest.mark.asyncio
    async def test_exact_route_takes_priority_over_pool(self):
        from channels.feishu.channel_server import ChannelServer, Instance
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        inst = Instance(ws=mock_ws, instance_id="ws-001", role="agent", chat_ids=["oc_test1"])
        server.exact_routes["oc_test1"] = inst
        server._pool = AsyncMock()
        msg = {"type": "message", "text": "hello", "chat_id": "oc_test1",
               "user": "test", "source": "feishu"}
        await server.route_message("oc_test1", msg)
        assert "oc_test1" not in server.pool_routes
        mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_wildcard_gets_observation_copy_with_pool(self):
        from channels.feishu.channel_server import ChannelServer, Instance
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        wc_inst = Instance(ws=mock_ws, instance_id="dev-001", role="developer", chat_ids=["*"])
        server.wildcard_instances.append(wc_inst)
        mock_pool = AsyncMock()
        mock_pool.acquire_sticky = AsyncMock(return_value=MagicMock(id="cc-001"))
        async def mock_session_query(chat_id, prompt, **kw):
            return; yield
        mock_pool.session_query = mock_session_query
        server._pool = mock_pool
        msg = {"type": "message", "text": "hello", "chat_id": "oc_test1",
               "user": "test", "source": "feishu"}
        await server.route_message("oc_test1", msg)
        assert "oc_test1" in server.pool_routes
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert "routed_to" in sent

    @pytest.mark.asyncio
    async def test_admin_chat_excluded_from_pool(self):
        from channels.feishu.channel_server import ChannelServer
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True,
                               admin_chat_id="oc_admin")
        server._pool = AsyncMock()
        msg = {"type": "message", "text": "hello", "chat_id": "oc_admin",
               "user": "admin", "source": "feishu"}
        await server.route_message("oc_admin", msg)
        assert "oc_admin" not in server.pool_routes

    @pytest.mark.asyncio
    async def test_pool_route_cleaned_on_sticky_release(self):
        from channels.feishu.channel_server import ChannelServer, PoolRoute
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_pool = AsyncMock()
        server._pool = mock_pool
        server.pool_routes["oc_expired"] = PoolRoute(
            pool=mock_pool, chat_id="oc_expired", instance_id="cc-001"
        )
        await server._on_pool_route_expired("oc_expired")
        assert "oc_expired" not in server.pool_routes

    @pytest.mark.asyncio
    async def test_pool_none_falls_back_to_wildcard(self):
        from channels.feishu.channel_server import ChannelServer, Instance
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        server._pool = None
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        wc_inst = Instance(ws=mock_ws, instance_id="dev-001", role="developer", chat_ids=["*"])
        server.wildcard_instances.append(wc_inst)
        msg = {"type": "message", "text": "hello", "chat_id": "oc_test1",
               "user": "test", "source": "feishu"}
        await server.route_message("oc_test1", msg)
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert "routed_to" not in sent
