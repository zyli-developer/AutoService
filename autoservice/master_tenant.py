"""Internal tenant bootstrap — _master and _local_admin (spec §2.7 + §2.8).

Provides the idempotent provisioning functions for the two bootstrap tenants
that host the M2 self-iteration loops:

- ``_master`` (master side, ``.autoservice/sandbox/_master/``) — ManagementChat
  talks to this tenant; ``_master`` dream proposes platform-level improvements
  to ``_master/souls/customer_soul.md``.
- ``_local_admin`` (fork side, ``plugins/_local_admin/``) — TenantLayout
  ChatTab talks to this tenant; ``_local_admin`` dream proposes fork-scoped
  admin-assistant improvements.

Both are ``tier=0`` internal tenants per CON-05; they are invisible to the
platform's tenant-list views and exempt from cross-tenant auth checks.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from autoservice import soul_generator
from autoservice.onboarding import (
    DEFAULT_COMPLIANCE,
    DEFAULT_DREAM_CFG,
    DEFAULT_SOUL_CFG,
    _init_sandbox_kb,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

MASTER_TENANT_ID = "_master"
LOCAL_ADMIN_TENANT_ID = "_local_admin"

Kind = Literal["platform", "fork"]


def _master_root() -> Path:
    return PROJECT_ROOT / ".autoservice" / "sandbox" / MASTER_TENANT_ID


def _local_admin_root() -> Path:
    return PROJECT_ROOT / "plugins" / LOCAL_ADMIN_TENANT_ID


def _write_internal_tenant_config(
    root: Path, *, tenant_id: str, brand_name: str, kind: Kind
) -> None:
    """Write config.json for an internal tier=0 tenant."""
    cfg: dict = {
        "tenant_id": tenant_id,
        "brand_name": brand_name,
        "industry": "platform-ops",
        "tier": 0,
        "parent_tenant_id": None,
        "kind": kind,
        "status": "active",
        "channels": ["web"],
        "compliance": dict(DEFAULT_COMPLIANCE),
        "soul": dict(DEFAULT_SOUL_CFG),
        # Deep-copy dream defaults via json round-trip so nested canary dict
        # is not aliased across internal tenants.
        "dream": json.loads(json.dumps(DEFAULT_DREAM_CFG)),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Spec §2.7 — _master skips canary staging (platform-level is all-at-once).
    if tenant_id == MASTER_TENANT_ID:
        cfg["dream"]["canary"] = {"stages": [100], "observe_hours": 0}

    (root / "config.json").write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _generate_internal_souls(*, tenant_id: str, brand_name: str, souls_dir: Path) -> None:
    """Generate all 5 agent souls for an internal tenant.

    Uses ``dry_run=True`` so the bootstrap path never calls Anthropic at startup
    (no network, no cost). All 5 roles use their template / constant fallback:

    - customer/translate/lead/triage → agents/<role>/soul.md
    - dream → _FALLBACK_DREAM_SOUL constant (spec §2.3)

    Post-bootstrap an admin can regenerate with LLM via the admin-portal.
    """
    config = soul_generator.TenantConfig(
        tenant_id=tenant_id,
        brand_name=brand_name,
        industry="platform-ops",
        languages=["zh", "en"],
        primary_language="zh",
    )
    result = soul_generator.generate_souls(config, dry_run=True)
    souls_dir.mkdir(parents=True, exist_ok=True)
    soul_generator.save_drafts(result, output_dir=souls_dir)


def _ensure_internal_tenant(
    *,
    root: Path,
    tenant_id: str,
    brand_name: str,
    kind: Kind,
) -> bool:
    """Shared idempotent provisioning. Returns True if newly created."""
    if (root / "config.json").exists():
        return False
    root.mkdir(parents=True, exist_ok=True)
    _write_internal_tenant_config(
        root, tenant_id=tenant_id, brand_name=brand_name, kind=kind
    )
    _generate_internal_souls(
        tenant_id=tenant_id, brand_name=brand_name, souls_dir=root / "souls"
    )
    kb_dir = root / "kb"
    kb_dir.mkdir(exist_ok=True)
    conn = _init_sandbox_kb(kb_dir / "kb.db")
    conn.close()
    return True


def ensure_master_tenant() -> bool:
    """Idempotently provision the ``_master`` platform tenant (spec §2.7).

    Run at master-mode startup only. Returns ``True`` on first provisioning,
    ``False`` if already present.
    """
    return _ensure_internal_tenant(
        root=_master_root(),
        tenant_id=MASTER_TENANT_ID,
        brand_name="AutoService Platform",
        kind="platform",
    )


def ensure_local_admin() -> bool:
    """Idempotently provision the ``_local_admin`` fork-side tenant (spec §2.8).

    Run at tenant-mode startup only. Returns ``True`` on first provisioning,
    ``False`` if already present.
    """
    return _ensure_internal_tenant(
        root=_local_admin_root(),
        tenant_id=LOCAL_ADMIN_TENANT_ID,
        brand_name="Local Admin",
        kind="fork",
    )
