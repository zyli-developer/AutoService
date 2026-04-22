"""Unit tests for gateway.tenant_resolver.resolve_customer_tenant.

Resolves a customer /ws/customer connection's tenant_id from URL query +
deployment mode + on-disk sandbox. See docs discussion in conversation
"customer KB 不起作用" (2026-04-22).

Precedence:
  1. URL `?tenant=<tid>` — explicit per-request; validated against bootstrap
     (tenant-mode: must equal self) and on-disk registration (master-mode).
  2. bootstrap.get_tenant_id() — tenant-mode process-level self tenant.
  3. MASTER_TENANT_ID ("_master") — master-mode platform fallback.

Rejection reasons (returned as second tuple element):
  - "tenant_mismatch": tenant-mode + query differs from self (snooping defense)
  - "unknown_tenant":  master-mode + query tenant not registered on disk, or
                        `_local_admin` / other internal ids requested
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoservice import bootstrap
from autoservice.gateway import tenant_resolver


@pytest.fixture(autouse=True)
def _clear_bootstrap_caches():
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


def _write_local_cfg(tmp_path: Path, content: str) -> None:
    (tmp_path / ".autoservice").mkdir(exist_ok=True)
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(content, encoding="utf-8")


def _seed_sandbox_tenant(tmp_path: Path, tid: str) -> None:
    """Master-mode: .autoservice/sandbox/<tid>/config.json = registration marker."""
    d = tmp_path / ".autoservice" / "sandbox" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"tenant_id": tid}), encoding="utf-8")


def _seed_legacy_plugin_tenant(tmp_path: Path, tid: str) -> None:
    """Legacy L3 plugin tenant: plugins/<tid>/plugin.yaml (e.g., cinnox)."""
    d = tmp_path / "plugins" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.yaml").write_text(f"name: {tid}\nversion: 1.0.0\n", encoding="utf-8")


def _seed_plugin_tenant(tmp_path: Path, tid: str) -> None:
    """Tenant-mode: plugins/<tid>/config.json = registration marker (matches
    bootstrap.get_deployment_mode strict check)."""
    d = tmp_path / "plugins" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"tenant_id": tid}), encoding="utf-8")


# ─── Master mode ─────────────────────────────────────────────────────────────


class TestMasterMode:
    def test_no_query_falls_back_to_master_tenant(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({})

        assert tid == "_master"
        assert reason is None

    def test_empty_query_value_falls_back_to_master(self, tmp_path, monkeypatch):
        """`?tenant=` (empty value) must not trip unknown_tenant — treat as missing."""
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": ""})

        assert tid == "_master"
        assert reason is None

    def test_registered_tenant_in_query_accepted(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        _seed_sandbox_tenant(tmp_path, "mystore")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "mystore"})

        assert tid == "mystore"
        assert reason is None

    def test_unregistered_tenant_in_query_rejected(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "acme"})

        assert tid is None
        assert reason == "unknown_tenant"

    def test_master_tenant_explicitly_in_query_accepted(self, tmp_path, monkeypatch):
        """`?tenant=_master` is a legitimate customer-facing tenant (A ↔ _master
        self-iteration flow per M2 §2.7)."""
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "_master"})

        assert tid == "_master"
        assert reason is None

    def test_local_admin_in_query_rejected(self, tmp_path, monkeypatch):
        """`_local_admin` is operator/admin-facing only — customers must not bind to it."""
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "_local_admin"})

        assert tid is None
        assert reason == "unknown_tenant"

    def test_unknown_underscore_prefix_rejected(self, tmp_path, monkeypatch):
        """Other `_`-prefixed ids (attempted reserved-name abuse) must be rejected."""
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "_hax"})

        assert tid is None
        assert reason == "unknown_tenant"

    def test_legacy_plugin_tenant_accepted(self, tmp_path, monkeypatch):
        """plugins/<tid>/plugin.yaml is a valid tenant marker too (e.g., cinnox)."""
        _write_local_cfg(tmp_path, "deployment_mode: master\n")
        _seed_legacy_plugin_tenant(tmp_path, "cinnox")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "cinnox"})

        assert tid == "cinnox"
        assert reason is None


# ─── Tenant mode ─────────────────────────────────────────────────────────────


class TestTenantMode:
    def test_no_query_uses_bootstrap_self_tenant(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: tenant\ntenant_id: mystore\n")
        _seed_plugin_tenant(tmp_path, "mystore")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({})

        assert tid == "mystore"
        assert reason is None

    def test_query_matches_self_accepted(self, tmp_path, monkeypatch):
        _write_local_cfg(tmp_path, "deployment_mode: tenant\ntenant_id: mystore\n")
        _seed_plugin_tenant(tmp_path, "mystore")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "mystore"})

        assert tid == "mystore"
        assert reason is None

    def test_query_mismatch_rejected_as_snooping(self, tmp_path, monkeypatch):
        """Cross-tenant snooping defense: tenant-mode only serves its own tenant."""
        _write_local_cfg(tmp_path, "deployment_mode: tenant\ntenant_id: mystore\n")
        _seed_plugin_tenant(tmp_path, "mystore")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

        tid, reason = tenant_resolver.resolve_customer_tenant({"tenant": "acme"})

        assert tid is None
        assert reason == "tenant_mismatch"
