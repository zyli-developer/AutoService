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
