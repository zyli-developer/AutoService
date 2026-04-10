"""Tests for /discuss command pipeline."""

import asyncio
import json
import time

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from feishu.channel_server import ChannelServer


@pytest.fixture
def server():
    """Create a ChannelServer with Feishu disabled."""
    return ChannelServer(
        port=0,
        feishu_enabled=False,
        admin_chat_id="oc_admin_test",
    )


class TestDiscussCommand:

    @pytest.mark.asyncio
    async def test_discuss_no_topic_returns_usage(self, server):
        """'/discuss' with no arguments should return usage info."""
        server._reply_feishu = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/discuss"}
        await server._handle_admin_message(msg)
        server._reply_feishu.assert_called_once()
        reply_text = server._reply_feishu.call_args[0][1]
        assert "Usage" in reply_text or "/discuss" in reply_text

    @pytest.mark.asyncio
    async def test_discuss_start_routes_with_discuss_mode(self, server):
        """'/discuss "topic"' should route message with runtime_mode=discuss."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": '/discuss "优化登录流程"'}
        await server._handle_admin_message(msg)
        assert server._reply_feishu.call_count == 1
        server.route_message.assert_called_once()
        call_args = server.route_message.call_args
        routed_msg = call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert "优化登录流程" in routed_msg["text"]

    @pytest.mark.asyncio
    async def test_discuss_start_saves_previous_mode(self, server):
        """Starting discuss should save the previous runtime_mode."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "improve"
        msg = {"chat_id": "oc_admin_test", "text": '/discuss "topic"'}
        await server._handle_admin_message(msg)
        assert server._discuss_prev_modes.get("oc_admin_test") == "improve"
        assert server._chat_modes["oc_admin_test"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_end_restores_mode(self, server):
        """'/discuss end' should restore the previous runtime_mode."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "discuss"
        server._discuss_prev_modes["oc_admin_test"] = "production"
        msg = {"chat_id": "oc_admin_test", "text": "/discuss end"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert routed_msg["text"] == "/discuss end"
        assert server._chat_modes["oc_admin_test"] == "production"
        assert "oc_admin_test" not in server._discuss_prev_modes

    @pytest.mark.asyncio
    async def test_discuss_status_routes(self, server):
        """'/discuss status' should route to channel instance."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "discuss"
        msg = {"chat_id": "oc_admin_test", "text": "/discuss status"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_with_file_reference(self, server):
        """'/discuss @docs/prd.md' should include source in routed message."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/discuss @docs/prd.md"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert "@docs/prd.md" in routed_msg["text"]

    @pytest.mark.asyncio
    async def test_help_includes_discuss(self, server):
        """Help text should list the /discuss command."""
        text = server.help_text()
        assert "/discuss" in text


class TestDiscussIdleTimeout:

    @pytest.mark.asyncio
    async def test_discuss_message_updates_timestamp(self, server):
        """Messages with runtime_mode=discuss should update idle timestamp."""
        server._discuss_sessions = {}
        msg = {
            "type": "message",
            "chat_id": "oc_discuss_test",
            "text": "some discussion message",
            "runtime_mode": "discuss",
        }
        await server.route_message("oc_discuss_test", msg)
        assert "oc_discuss_test" in server._discuss_sessions

    @pytest.mark.asyncio
    async def test_idle_check_sends_reminder(self, server):
        """Idle checker should send reminder when timeout exceeded."""
        server._discuss_sessions = {
            "oc_idle_test": time.time() - 1000,
        }
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 0)
        from feishu.channel_server import Instance
        inst = Instance(
            ws=mock_ws,
            instance_id="test-channel",
            role="developer",
            chat_ids=["*"],
        )
        server.wildcard_instances.append(inst)
        server._ws_to_instance[mock_ws] = inst

        await server._check_discuss_idle()

        assert mock_ws.send.call_count >= 1
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["type"] == "discuss_idle_reminder"
        assert sent_msg["chat_id"] == "oc_idle_test"

    @pytest.mark.asyncio
    async def test_idle_check_skips_active_sessions(self, server):
        """Idle checker should not send reminder for recently active sessions."""
        server._discuss_sessions = {
            "oc_active_test": time.time(),
        }
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 0)
        from feishu.channel_server import Instance
        inst = Instance(
            ws=mock_ws,
            instance_id="test-channel",
            role="developer",
            chat_ids=["*"],
        )
        server.wildcard_instances.append(inst)
        server._ws_to_instance[mock_ws] = inst

        await server._check_discuss_idle()

        mock_ws.send.assert_not_called()


class TestDiscussIntegration:

    @pytest.mark.asyncio
    async def test_discuss_lifecycle_mode_switching(self, server):
        """Full lifecycle: start -> messages route as discuss -> end -> mode restored."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()

        chat_id = "oc_lifecycle_test"

        # Ensure clean state
        server._chat_modes.pop(chat_id, None)
        server._discuss_prev_modes.pop(chat_id, None)

        # 1. Start discuss
        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": '/discuss "架构设计讨论"',
        })
        assert server._chat_modes[chat_id] == "discuss"
        assert server._discuss_prev_modes[chat_id] == "production"

        # 2. Verify mode is discuss
        assert server._chat_modes.get(chat_id) == "discuss"

        # 3. End discuss
        server.route_message.reset_mock()
        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": "/discuss end",
        })
        assert server._chat_modes[chat_id] == "production"
        assert chat_id not in server._discuss_prev_modes
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["text"] == "/discuss end"
        assert routed_msg["runtime_mode"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_end_clears_idle_tracking(self, server):
        """Ending a discuss session should remove it from idle tracking."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()

        chat_id = "oc_admin_test"
        server._chat_modes[chat_id] = "discuss"
        server._discuss_prev_modes[chat_id] = "production"
        server._discuss_sessions[chat_id] = time.time()

        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": "/discuss end",
        })

        assert chat_id not in server._discuss_sessions
