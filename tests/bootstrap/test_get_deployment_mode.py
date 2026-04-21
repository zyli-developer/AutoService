"""T1B.1 — Tests for autoservice.bootstrap.get_deployment_mode / get_tenant_id.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §1.3 + §3.1
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Import under test
from autoservice import bootstrap


@pytest.fixture(autouse=True)
def clear_bootstrap_caches():
    """Reset functools.lru_cache between tests so config changes take effect."""
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


def _write_local_cfg(tmp_path: Path, content: str) -> Path:
    autoservice_dir = tmp_path / ".autoservice"
    autoservice_dir.mkdir(exist_ok=True)
    cfg_path = autoservice_dir / "config.local.yaml"
    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


class TestGetDeploymentMode:
    def test_master_mode_default_when_missing(self, tmp_path, monkeypatch):
        """Absent deployment_mode field → defaults to 'master'."""
        _write_local_cfg(tmp_path, "cc_pool:\n  min_size: 1\n")
        monkeypatch.chdir(tmp_path)

        assert bootstrap.get_deployment_mode() == "master"

    def test_master_mode_explicit(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)

        assert bootstrap.get_deployment_mode() == "master"

    def test_tenant_mode_with_matching_tenant_id(self, tmp_path, monkeypatch):
        """Tenant mode requires tenant_id and plugins/<tid>/config.json consistency."""
        _write_local_cfg(
            tmp_path,
            "deployment_mode: tenant\ntenant_id: acme\n",
        )
        plugins = tmp_path / "plugins" / "acme"
        plugins.mkdir(parents=True)
        (plugins / "config.json").write_text(json.dumps({"tenant_id": "acme"}))
        monkeypatch.chdir(tmp_path)

        assert bootstrap.get_deployment_mode() == "tenant"

    def test_tenant_mode_mismatched_tenant_id_raises(self, tmp_path, monkeypatch):
        """config.local.yaml.tenant_id != plugins/<tid>/config.json.tenant_id must raise."""
        _write_local_cfg(
            tmp_path,
            "deployment_mode: tenant\ntenant_id: acme\n",
        )
        plugins = tmp_path / "plugins" / "acme"
        plugins.mkdir(parents=True)
        (plugins / "config.json").write_text(json.dumps({"tenant_id": "wrong"}))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError):
            bootstrap.get_deployment_mode()

    def test_invalid_mode_raises(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: bogus\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError):
            bootstrap.get_deployment_mode()


class TestGetTenantId:
    def test_returns_none_for_master(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)

        assert bootstrap.get_tenant_id() is None

    def test_returns_tenant_id_for_tenant_mode(self, tmp_path, monkeypatch):
        _write_local_cfg(
            tmp_path,
            "deployment_mode: tenant\ntenant_id: acme\n",
        )
        monkeypatch.chdir(tmp_path)

        assert bootstrap.get_tenant_id() == "acme"


class TestDreamConfigSchema:
    """T1B.1 requires config.local.yaml schema expectations for dream.* fields.

    The loader must accept (but doesn't enforce) these optional top-level fields;
    their semantics are applied by later tasks (T4B.*).
    """

    def test_dream_config_block_is_loadable(self, tmp_path, monkeypatch):
        cfg = (
            "deployment_mode: master\n"
            "dream:\n"
            "  idle_threshold_min: 45\n"
            "  cool_down_min: 60\n"
            "  max_tool_turns: 10\n"
        )
        _write_local_cfg(tmp_path, cfg)
        monkeypatch.chdir(tmp_path)

        loaded = bootstrap._load_local_config()
        assert loaded["deployment_mode"] == "master"
        assert loaded["dream"]["idle_threshold_min"] == 45
        assert loaded["dream"]["max_tool_turns"] == 10
