"""T7B.2 — Tests for autoservice.bootstrap.tenant_root.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.3

Resolution rules exercised here:
  1. Internal tenants (_master, _local_admin) are mode-agnostic.
  2. Regular tenants branch on deployment mode (master → sandbox, tenant → plugins).
  3. tenant_root(None) falls back to _master (master) or get_tenant_id() (tenant).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoservice import bootstrap


@pytest.fixture(autouse=True)
def clear_bootstrap_caches():
    """Reset functools.cache between tests so config changes take effect."""
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


@pytest.fixture
def master_mode(tmp_path, monkeypatch):
    _write_local_cfg(tmp_path, "deployment_mode: master\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def tenant_mode(tmp_path, monkeypatch):
    _write_local_cfg(
        tmp_path,
        "deployment_mode: tenant\ntenant_id: acme\n",
    )
    plugins = tmp_path / "plugins" / "acme"
    plugins.mkdir(parents=True)
    (plugins / "config.json").write_text(json.dumps({"tenant_id": "acme"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestInternalTenantsModeAgnostic:
    """Rule 1 — `_master` and `_local_admin` resolve to fixed paths in both modes."""

    def test_master_in_master_mode(self, master_mode):
        assert bootstrap.tenant_root("_master") == (
            master_mode / ".autoservice" / "sandbox" / "_master"
        )

    def test_master_in_tenant_mode(self, tenant_mode):
        assert bootstrap.tenant_root("_master") == (
            tenant_mode / ".autoservice" / "sandbox" / "_master"
        )

    def test_local_admin_in_master_mode(self, master_mode):
        assert bootstrap.tenant_root("_local_admin") == (
            master_mode / "plugins" / "_local_admin"
        )

    def test_local_admin_in_tenant_mode(self, tenant_mode):
        assert bootstrap.tenant_root("_local_admin") == (
            tenant_mode / "plugins" / "_local_admin"
        )

    def test_unknown_internal_tenant_raises(self, master_mode):
        """Defensive: only _master and _local_admin are valid internal IDs."""
        with pytest.raises(ValueError, match="unknown internal tenant"):
            bootstrap.tenant_root("_phantom")


class TestRegularTenantsFollowMode:
    """Rule 2 — regular tenants branch on get_deployment_mode()."""

    def test_regular_in_master_mode_goes_to_sandbox(self, master_mode):
        assert bootstrap.tenant_root("acme") == (
            master_mode / ".autoservice" / "sandbox" / "acme"
        )

    def test_regular_in_tenant_mode_goes_to_plugins(self, tenant_mode):
        assert bootstrap.tenant_root("acme") == (
            tenant_mode / "plugins" / "acme"
        )


class TestNoneFallback:
    """Rule 3 — tenant_root(None) resolves per mode."""

    def test_none_in_master_mode_falls_back_to_master_tenant(self, master_mode):
        """Documented in eval-doc-015: master-mode None → _master platform default."""
        assert bootstrap.tenant_root(None) == (
            master_mode / ".autoservice" / "sandbox" / "_master"
        )
        # Call with no arg should match explicit None.
        assert bootstrap.tenant_root() == bootstrap.tenant_root(None)

    def test_none_in_tenant_mode_uses_self_tenant_id(self, tenant_mode):
        assert bootstrap.tenant_root(None) == (
            tenant_mode / "plugins" / "acme"
        )


class TestEmptyStringRejected:
    def test_empty_string_raises(self, master_mode):
        with pytest.raises(ValueError):
            bootstrap.tenant_root("")
