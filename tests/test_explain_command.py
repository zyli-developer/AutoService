"""Tests for /explain command pipeline."""

import asyncio
import json

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from channels.feishu.channel_server import ChannelServer


@pytest.fixture
def server():
    """Create a ChannelServer with Feishu disabled."""
    return ChannelServer(
        port=0,
        feishu_enabled=False,
        admin_chat_id="oc_admin_test",
    )


class TestExplainCommand:

    @pytest.mark.asyncio
    async def test_explain_no_query_returns_usage(self, server):
        server._reply_feishu = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/explain"}
        await server._handle_admin_message(msg)
        server._reply_feishu.assert_called_once()
        reply_text = server._reply_feishu.call_args[0][1]
        assert "Usage" in reply_text

    @pytest.mark.asyncio
    async def test_explain_routes_to_wildcard(self, server):
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/explain 用户问DID价格"}
        await server._handle_admin_message(msg)
        # Should reply with "analyzing" first
        assert server._reply_feishu.call_count == 1
        assert "正在分析" in server._reply_feishu.call_args[0][1]
        # Should route to wildcard
        server.route_message.assert_called_once()
        call_args = server.route_message.call_args
        assert call_args[0][0] == "admin_explain"
        routed_msg = call_args[0][1]
        assert routed_msg["runtime_mode"] == "explain"
        assert routed_msg["text"] == "用户问DID价格"
        assert routed_msg["admin_chat_id"] == "oc_admin_test"

    @pytest.mark.asyncio
    async def test_help_includes_explain(self, server):
        text = server.help_text()
        assert "/explain" in text


class TestFlowYAML:

    def test_index_has_all_flows(self):
        import yaml

        flows_dir = Path(__file__).parent.parent / ".autoservice" / "flows"
        if not flows_dir.exists():
            pytest.skip("flows/ not yet created")
        index = yaml.safe_load((flows_dir / "_index.yaml").read_text(encoding="utf-8"))
        indexed_ids = {f["id"] for f in index["flows"]}
        flow_files = [f.stem for f in flows_dir.glob("*.yaml") if f.name != "_index.yaml"]
        for fid in flow_files:
            assert fid in indexed_ids, f"Flow file {fid}.yaml not in _index.yaml"

    def test_flow_has_required_fields(self):
        import yaml

        flows_dir = Path(__file__).parent.parent / ".autoservice" / "flows"
        if not flows_dir.exists():
            pytest.skip("flows/ not yet created")
        required = {"id", "name", "description", "tags", "entry", "exits", "nodes", "edges"}
        for f in flows_dir.glob("*.yaml"):
            if f.name == "_index.yaml":
                continue
            flow = yaml.safe_load(f.read_text(encoding="utf-8"))
            missing = required - set(flow.keys())
            assert not missing, f"{f.name} missing fields: {missing}"

    def test_flow_entry_node_exists(self):
        import yaml

        flows_dir = Path(__file__).parent.parent / ".autoservice" / "flows"
        if not flows_dir.exists():
            pytest.skip("flows/ not yet created")
        for f in flows_dir.glob("*.yaml"):
            if f.name == "_index.yaml":
                continue
            flow = yaml.safe_load(f.read_text(encoding="utf-8"))
            node_ids = {n["id"] for n in flow["nodes"]}
            assert flow["entry"] in node_ids, f"{f.name}: entry '{flow['entry']}' not in nodes"

    def test_flow_edges_reference_valid_nodes(self):
        import yaml

        flows_dir = Path(__file__).parent.parent / ".autoservice" / "flows"
        if not flows_dir.exists():
            pytest.skip("flows/ not yet created")
        for f in flows_dir.glob("*.yaml"):
            if f.name == "_index.yaml":
                continue
            flow = yaml.safe_load(f.read_text(encoding="utf-8"))
            node_ids = {n["id"] for n in flow["nodes"]}
            for edge in flow["edges"]:
                assert edge["from"] in node_ids, f"{f.name}: edge from '{edge['from']}' not in nodes"
                assert edge["to"] in node_ids, f"{f.name}: edge to '{edge['to']}' not in nodes"


class TestExplainRoute:

    def test_explain_serves_existing_file(self):
        from fastapi.testclient import TestClient
        from channels.web.app import app

        explain_dir = Path(__file__).parent.parent / ".autoservice" / "explain"
        explain_dir.mkdir(parents=True, exist_ok=True)
        test_file = explain_dir / "test-flow.html"
        test_file.write_text("<html><body>test</body></html>")
        try:
            client = TestClient(app)
            resp = client.get("/explain/test-flow.html")
            assert resp.status_code == 200
            assert "test" in resp.text
        finally:
            test_file.unlink(missing_ok=True)

    def test_explain_404_for_missing(self):
        from fastapi.testclient import TestClient
        from channels.web.app import app

        client = TestClient(app)
        resp = client.get("/explain/nonexistent.html")
        assert resp.status_code == 404
