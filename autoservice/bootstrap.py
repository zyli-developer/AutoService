"""M2 deployment-mode detection + tenant bootstrap scaffolding.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §1.3 + §3.1

T1B.1 introduces the mode-detection helpers (get_deployment_mode / get_tenant_id
plus a private config loader). Subsequent tasks (T1B.3 ensure_master_tenant,
T1B.4 ensure_local_admin, T1B.5 lifespan wire) extend this module.
"""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


LOCAL_CONFIG_PATH = Path(".autoservice/config.local.yaml")
VALID_MODES = ("master", "tenant")

# Module-level anchor so callers (and tests via monkeypatch.setattr) can
# resolve on-disk paths independent of the current working directory.
# Mirrors the CON-07 convention used by master_tenant/cc_pool/etc.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Internal/system tenant identifiers — mode-agnostic (spec §2.7 + §2.8).
MASTER_TENANT_ID = "_master"
LOCAL_ADMIN_TENANT_ID = "_local_admin"


def _load_local_config() -> dict[str, Any]:
    """Load .autoservice/config.local.yaml from the current working directory.

    Raises:
        FileNotFoundError: if the file is missing.
        ImportError: if PyYAML is not installed.
    """
    if yaml is None:
        raise ImportError(
            "PyYAML is required to read config.local.yaml. Install with: pip install pyyaml"
        )
    with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{LOCAL_CONFIG_PATH} must be a YAML mapping at the top level"
        )
    return data


@cache
def get_deployment_mode() -> Literal["master", "tenant"]:
    """Resolve deployment mode from .autoservice/config.local.yaml.

    Defaults to 'master' when the field is absent (back-compat with M1 setups).
    In 'tenant' mode, cross-checks that ``plugins/<tenant_id>/config.json``
    matches the declared tenant_id — a mismatch indicates a misprovisioned fork.
    """
    cfg = _load_local_config()
    mode = cfg.get("deployment_mode", "master")
    assert mode in VALID_MODES, (
        f"deployment_mode must be one of {VALID_MODES}, got {mode!r}"
    )

    if mode == "tenant":
        tid = cfg.get("tenant_id")
        assert tid, "deployment_mode=tenant requires tenant_id in config.local.yaml"
        tenant_cfg_path = Path(f"plugins/{tid}/config.json")
        if tenant_cfg_path.exists():
            with open(tenant_cfg_path, "r", encoding="utf-8") as f:
                tenant_cfg = json.load(f)
            assert tenant_cfg.get("tenant_id") == tid, (
                f"tenant_id mismatch: config.local.yaml says {tid!r}, "
                f"{tenant_cfg_path} says {tenant_cfg.get('tenant_id')!r}"
            )
    return mode  # type: ignore[return-value]


@cache
def get_tenant_id() -> str | None:
    """Return the active tenant_id when running in tenant mode, else None.

    In master mode returns None even if the field is present.
    """
    cfg = _load_local_config()
    mode = cfg.get("deployment_mode", "master")
    if mode != "tenant":
        return None
    return cfg.get("tenant_id")


def tenant_root(tenant_id: str | None = None) -> Path:
    """Return the on-disk root for a tenant's sandbox/fork data (spec §3.3).

    Resolution rules:

    1. Internal/system tenants (``_master`` / ``_local_admin``) are
       mode-agnostic — they always live at the same relative path:

       * ``_master`` → ``PROJECT_ROOT / ".autoservice/sandbox/_master/"``
       * ``_local_admin`` → ``PROJECT_ROOT / "plugins/_local_admin/"``

       Any other ``_``-prefixed identifier raises :class:`ValueError`
       (defensive: only two internal tenants exist today).

    2. Regular tenants follow the deployment-mode convention:

       * master mode → ``PROJECT_ROOT / ".autoservice/sandbox/<tid>/"``
       * tenant mode → ``PROJECT_ROOT / "plugins/<tid>/"``

    3. ``tenant_id=None`` resolves the request-less default:

       * tenant mode → uses :func:`get_tenant_id` (the self tenant)
       * master mode → falls back to ``_master`` (platform-ops default,
         see eval-doc-015 for rationale)

    Args:
        tenant_id: Target tenant identifier. When ``None``, resolves per
            deployment mode (see rule 3).

    Returns:
        Absolute path to the tenant's root directory. The directory is
        NOT guaranteed to exist — callers that need the directory
        materialised should create it (e.g. via ``master_tenant.ensure_*``).

    Raises:
        ValueError: for unknown internal identifiers (``_``-prefixed but
            not ``_master`` / ``_local_admin``) or an empty string.
    """
    # Rule 3: fallback to mode-appropriate default.
    if tenant_id is None:
        mode = get_deployment_mode()
        if mode == "tenant":
            self_tid = get_tenant_id()
            # get_tenant_id() returns None only in master mode, so if we hit
            # this in tenant mode the config is malformed.
            assert self_tid is not None, (
                "tenant mode requires tenant_id in config.local.yaml"
            )
            return tenant_root(self_tid)
        # master mode → platform-ops default
        return tenant_root(MASTER_TENANT_ID)

    if not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    # Rule 1: internal tenants are mode-agnostic.
    if tenant_id.startswith("_"):
        if tenant_id == MASTER_TENANT_ID:
            return PROJECT_ROOT / ".autoservice" / "sandbox" / MASTER_TENANT_ID
        if tenant_id == LOCAL_ADMIN_TENANT_ID:
            return PROJECT_ROOT / "plugins" / LOCAL_ADMIN_TENANT_ID
        raise ValueError(
            f"unknown internal tenant identifier: {tenant_id!r} "
            f"(valid: {MASTER_TENANT_ID!r}, {LOCAL_ADMIN_TENANT_ID!r})"
        )

    # Rule 2: regular tenants branch on deployment mode.
    mode = get_deployment_mode()
    if mode == "tenant":
        return PROJECT_ROOT / "plugins" / tenant_id
    return PROJECT_ROOT / ".autoservice" / "sandbox" / tenant_id
