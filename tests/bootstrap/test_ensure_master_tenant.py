"""T1B.3 — Tests for autoservice.master_tenant.ensure_master_tenant.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.7
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoservice import master_tenant, soul_generator


@pytest.fixture
def patched_roots(tmp_path, monkeypatch):
    """Redirect PROJECT_ROOT-derived paths into tmp_path for isolation."""
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestEnsureMasterTenant:
    def test_creates_full_sandbox_structure(self, patched_roots):
        created = master_tenant.ensure_master_tenant()
        assert created is True

        root = patched_roots / ".autoservice" / "sandbox" / "_master"
        assert (root / "config.json").exists()
        assert (root / "souls").is_dir()
        assert (root / "kb" / "kb.db").exists()

    def test_config_has_m2_fields(self, patched_roots):
        master_tenant.ensure_master_tenant()
        cfg_path = patched_roots / ".autoservice" / "sandbox" / "_master" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        assert cfg["tenant_id"] == "_master"
        assert cfg["tier"] == 0  # internal tenant (CON-05)
        assert cfg["parent_tenant_id"] is None
        assert cfg["status"] == "active"
        assert cfg["kind"] == "platform"
        assert "dream" in cfg and cfg["dream"]["trigger"] == "idle"
        # Spec §2.7 — master canary is a single-stage 100% (observe_hours=0)
        assert cfg["dream"]["canary"]["stages"] == [100]
        assert cfg["dream"]["canary"]["observe_hours"] == 0

    def test_generates_all_5_soul_roles(self, patched_roots):
        master_tenant.ensure_master_tenant()
        souls = patched_roots / ".autoservice" / "sandbox" / "_master" / "souls"
        expected = {f"{role}_soul.md" for role in soul_generator.AGENT_ROLES}
        actual = {p.name for p in souls.iterdir() if p.suffix == ".md"}
        assert expected <= actual, f"missing: {expected - actual}"

    def test_idempotent_on_second_call(self, patched_roots):
        assert master_tenant.ensure_master_tenant() is True
        cfg_path = patched_roots / ".autoservice" / "sandbox" / "_master" / "config.json"
        first_mtime = cfg_path.stat().st_mtime_ns

        assert master_tenant.ensure_master_tenant() is False
        # Second call must NOT overwrite (mtime unchanged)
        assert cfg_path.stat().st_mtime_ns == first_mtime
