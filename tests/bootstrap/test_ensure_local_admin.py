"""T1B.4 — Tests for autoservice.master_tenant.ensure_local_admin.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.8
"""
from __future__ import annotations

import json

import pytest

from autoservice import master_tenant, soul_generator


@pytest.fixture
def patched_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestEnsureLocalAdmin:
    def test_creates_in_plugins_tree_not_sandbox(self, patched_roots):
        """_local_admin lives at plugins/_local_admin/ (NOT .autoservice/sandbox/)
        because fork repos do not have a sandbox concept (spec §2.8)."""
        created = master_tenant.ensure_local_admin()
        assert created is True

        plugin_root = patched_roots / "plugins" / "_local_admin"
        assert (plugin_root / "config.json").exists()
        assert (plugin_root / "souls").is_dir()
        assert (plugin_root / "kb" / "kb.db").exists()

        # Sandbox path MUST NOT be used for _local_admin
        sandbox_path = patched_roots / ".autoservice" / "sandbox" / "_local_admin"
        assert not sandbox_path.exists()

    def test_config_kind_is_fork(self, patched_roots):
        master_tenant.ensure_local_admin()
        cfg_path = patched_roots / "plugins" / "_local_admin" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        assert cfg["tenant_id"] == "_local_admin"
        assert cfg["tier"] == 0
        assert cfg["kind"] == "fork"
        assert cfg["parent_tenant_id"] is None

    def test_generates_all_5_souls(self, patched_roots):
        master_tenant.ensure_local_admin()
        souls = patched_roots / "plugins" / "_local_admin" / "souls"
        expected = {f"{role}_soul.md" for role in soul_generator.AGENT_ROLES}
        actual = {p.name for p in souls.iterdir() if p.suffix == ".md"}
        assert expected <= actual

    def test_idempotent(self, patched_roots):
        assert master_tenant.ensure_local_admin() is True
        assert master_tenant.ensure_local_admin() is False
