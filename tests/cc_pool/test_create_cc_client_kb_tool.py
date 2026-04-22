from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import create_cc_client, PoolConfig


@pytest.mark.asyncio
async def test_create_cc_client_injects_kb_server_when_enabled_and_tenant_known():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        mk.return_value = {"type": "sdk", "name": "autoservice_kb", "tools": []}
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id="acme", enable_kb_tool=True,
        )

    mk.assert_called_once_with("acme")
    # The SDK client options should carry the autoservice_kb server
    options = sdk_cls.call_args.args[0] if sdk_cls.call_args.args else sdk_cls.call_args.kwargs["options"]
    assert "autoservice_kb" in options.mcp_servers


@pytest.mark.asyncio
async def test_create_cc_client_skips_kb_server_when_disabled():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id="acme", enable_kb_tool=False,
        )

    mk.assert_not_called()


@pytest.mark.asyncio
async def test_create_cc_client_skips_kb_server_when_no_tenant():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id=None, enable_kb_tool=True,
        )

    mk.assert_not_called()
