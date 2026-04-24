"""Resolve + validate the tenant_id for an incoming /ws/customer connection.

Precedence:
  1. URL query `?tenant=<tid>` — explicit per-request assignment. Validated
     against bootstrap (tenant-mode: must equal self) and on-disk registration
     (master-mode: tenant sandbox must exist).
  2. bootstrap.get_tenant_id() — tenant-mode process-level self tenant.
  3. MASTER_TENANT_ID ("_master") — master-mode platform fallback (A ↔ _master
     self-iteration flow per M2 §2.7).

The caller (web_gateway._handle_connection) uses this to either pin
ws.state_customer_tenant_id (success) or close the connection 1008 (reject).
Once pinned, gateway.message_router forwards it into conv.metadata["tenant_id"]
on conversation creation, which feeds triage_config_loader →
_build_customer_prompt (KB pre-fetch) → cc_pool.session_query(tenant_id=...).
"""
from __future__ import annotations

from typing import Mapping

from autoservice import bootstrap

# _master is the only `_`-prefixed id customers may bind to. _local_admin is
# operator/admin-facing per M2 §2.8; anything else is rejected.
_CUSTOMER_FACING_INTERNAL = {bootstrap.MASTER_TENANT_ID}


def resolve_customer_tenant(
    query_params: Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Return (tenant_id, reject_reason).

    On success reject_reason is None and tenant_id is the validated id. On
    rejection tenant_id is None and reject_reason is one of:
      - "tenant_mismatch" — tenant-mode deployment received query ≠ self
      - "unknown_tenant"  — master-mode query specifies an unregistered tenant
    """
    raw = (query_params.get("tenant") or "").strip()

    try:
        mode = bootstrap.get_deployment_mode()
    except (FileNotFoundError, ImportError):
        # Missing config.local.yaml — treat as master-mode dev (matches
        # web_gateway middleware behavior at [web_gateway.py:302-305]).
        mode = "master"

    if mode == "tenant":
        self_tid = bootstrap.get_tenant_id()
        if raw and raw != self_tid:
            return None, "tenant_mismatch"
        return self_tid, None

    # master mode
    if not raw:
        return bootstrap.MASTER_TENANT_ID, None

    if raw.startswith("_"):
        # Customer-facing internal tenants are explicitly whitelisted; anything
        # else (incl. _local_admin and attempted reserved-name abuse) is rejected.
        if raw in _CUSTOMER_FACING_INTERNAL:
            return raw, None
        return None, "unknown_tenant"

    # Regular tenant: accept either registration marker.
    #   - M2 sandbox (wizard/dream-onboarded): .autoservice/sandbox/<tid>/config.json
    #   - Legacy L3 plugin (e.g., cinnox): plugins/<tid>/plugin.yaml
    #   - Tenant-mode colocated config: plugins/<tid>/config.json (future fork layout)
    root = bootstrap.PROJECT_ROOT
    markers = (
        root / ".autoservice" / "sandbox" / raw / "config.json",
        root / "plugins" / raw / "plugin.yaml",
        root / "plugins" / raw / "config.json",
    )
    if not any(m.is_file() for m in markers):
        return None, "unknown_tenant"
    return raw, None
