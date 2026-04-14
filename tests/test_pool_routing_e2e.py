"""Integration test: pool routing end-to-end (mocked SDK, real routing logic)."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from channels.feishu.channel_server import ChannelServer, Instance, PoolRoute


class TestPoolRoutingE2E:

    @pytest.mark.asyncio
    async def test_full_flow_two_customers(self):
        """Two customers get different pool instances via sticky sessions."""
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        dispatched = []
        mock_pool = AsyncMock()
        instance_a = MagicMock(id="cc-001", is_healthy=True)
        instance_b = MagicMock(id="cc-002", is_healthy=True)
        sticky_map = {}

        async def mock_acquire_sticky(key):
            if key not in sticky_map:
                sticky_map[key] = instance_a if len(sticky_map) == 0 else instance_b
            return sticky_map[key]

        mock_pool.acquire_sticky = mock_acquire_sticky

        async def mock_session_query(chat_id, prompt, **kw):
            dispatched.append(chat_id)
            return
            yield

        mock_pool.session_query = mock_session_query
        server._pool = mock_pool

        await server.route_message("oc_cust_a", {
            "type": "message", "text": "hi", "chat_id": "oc_cust_a",
            "user": "Alice", "source": "feishu"
        })
        await server.route_message("oc_cust_b", {
            "type": "message", "text": "hello", "chat_id": "oc_cust_b",
            "user": "Bob", "source": "feishu"
        })

        assert "oc_cust_a" in server.pool_routes
        assert "oc_cust_b" in server.pool_routes
        assert server.pool_routes["oc_cust_a"].instance_id == "cc-001"
        assert server.pool_routes["oc_cust_b"].instance_id == "cc-002"

        # Customer A sends second message — reuses existing route
        await server.route_message("oc_cust_a", {
            "type": "message", "text": "follow up", "chat_id": "oc_cust_a",
            "user": "Alice", "source": "feishu"
        })
        await asyncio.sleep(0.1)  # let async tasks complete

    @pytest.mark.asyncio
    async def test_exact_route_overrides_pool(self):
        """Dedicated CLI instance takes priority even when pool is active."""
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_pool = AsyncMock()
        server._pool = mock_pool

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        server.exact_routes["oc_cust_a"] = Instance(
            ws=mock_ws, instance_id="ws-001", role="agent", chat_ids=["oc_cust_a"]
        )

        await server.route_message("oc_cust_a", {
            "type": "message", "text": "hi", "chat_id": "oc_cust_a",
            "user": "Alice", "source": "feishu"
        })

        mock_ws.send.assert_called_once()
        assert "oc_cust_a" not in server.pool_routes

    @pytest.mark.asyncio
    async def test_pool_route_expires_and_reassigns(self):
        """After sticky expiry, new message creates fresh pool route."""
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_pool = AsyncMock()
        mock_pool.acquire_sticky = AsyncMock(return_value=MagicMock(id="cc-003"))

        async def mock_session_query(chat_id, prompt, **kw):
            return
            yield

        mock_pool.session_query = mock_session_query
        server._pool = mock_pool

        # Simulate existing route that expired
        server.pool_routes["oc_old"] = PoolRoute(
            pool=mock_pool, chat_id="oc_old", instance_id="cc-001"
        )
        await server._on_pool_route_expired("oc_old")
        assert "oc_old" not in server.pool_routes

        # New message triggers fresh assignment
        await server.route_message("oc_old", {
            "type": "message", "text": "back again", "chat_id": "oc_old",
            "user": "Alice", "source": "feishu"
        })
        assert "oc_old" in server.pool_routes
        assert server.pool_routes["oc_old"].instance_id == "cc-003"

    @pytest.mark.asyncio
    async def test_wildcard_observes_while_pool_handles(self):
        """Wildcard dev instance sees all messages but with routed_to tag."""
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)

        # Add wildcard observer
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        server.wildcard_instances.append(Instance(
            ws=mock_ws, instance_id="dev-001", role="developer", chat_ids=["*"]
        ))

        # Add pool
        mock_pool = AsyncMock()
        mock_pool.acquire_sticky = AsyncMock(return_value=MagicMock(id="cc-001"))
        async def mock_session_query(chat_id, prompt, **kw):
            return; yield
        mock_pool.session_query = mock_session_query
        server._pool = mock_pool

        # Three different customers
        for i, name in enumerate(["Alice", "Bob", "Carol"]):
            cid = f"oc_cust_{i}"
            await server.route_message(cid, {
                "type": "message", "text": f"hi from {name}",
                "chat_id": cid, "user": name, "source": "feishu"
            })

        # Wildcard got 3 observation copies, all with routed_to
        assert mock_ws.send.call_count == 3
        for call in mock_ws.send.call_args_list:
            sent = json.loads(call[0][0])
            assert "routed_to" in sent

    @pytest.mark.asyncio
    async def test_prefix_route_overrides_pool(self):
        """Prefix route (e.g. web_*) takes priority over pool."""
        server = ChannelServer(port=0, feishu_enabled=False, pool_mode=True)
        mock_pool = AsyncMock()
        server._pool = mock_pool

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        server.prefix_routes["web_"] = Instance(
            ws=mock_ws, instance_id="web-001", role="web", chat_ids=["web_*"]
        )

        await server.route_message("web_session1", {
            "type": "message", "text": "hi", "chat_id": "web_session1",
            "user": "WebUser", "source": "web"
        })

        mock_ws.send.assert_called_once()
        assert "web_session1" not in server.pool_routes
