"""Load per-tenant triage config for a conversation.

Reads plugins/<tenant_id>/config.yaml or .autoservice/sandbox/<tenant_id>/config.json
and returns an object with the triage-relevant attrs. Falls back to module defaults.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("triage.config")


@dataclass
class TenantTriageConfig:
    tenant_id: str | None = None
    supported_languages: list[str] = field(default_factory=lambda: ["zh", "en"])
    pool_size_per_role: int = 2
    history_reseed_token_limit: int = 2000
    triage_mode: str = "drift"
    triage_agent_timeout_ms: int = 2000
    triage_dispatch_enabled: bool = True


def _load_tenant_file(tenant_id: str) -> dict[str, Any]:
    cwd = Path.cwd()
    for candidate in (
        cwd / ".autoservice" / "sandbox" / tenant_id / "config.json",
        cwd / "plugins" / tenant_id / "config.yaml",
    ):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
            if candidate.suffix == ".json":
                return json.loads(text) or {}
            return yaml.safe_load(text) or {}
        except Exception as exc:
            log.warning("triage config read failed %s: %s", candidate, exc)
    return {}


async def load_tenant_config_for_conv(engine: Any, conv_id: str) -> TenantTriageConfig:
    conv = await engine.get_conversation(conv_id)
    tenant_id = conv.metadata.get("tenant_id")
    data = _load_tenant_file(tenant_id) if tenant_id else {}
    tenant_block = data.get("tenant", {}) if isinstance(data, dict) else {}
    return TenantTriageConfig(
        tenant_id=tenant_id,
        supported_languages=tenant_block.get("supported_languages") or ["zh", "en"],
        pool_size_per_role=int(tenant_block.get("pool_size_per_role", 2)),
        history_reseed_token_limit=int(tenant_block.get("history_reseed_token_limit", 2000)),
        triage_mode=tenant_block.get("triage_mode", "drift"),
        triage_agent_timeout_ms=int(tenant_block.get("triage_agent_timeout_ms", 2000)),
        triage_dispatch_enabled=bool(tenant_block.get("triage_dispatch_enabled", True)),
    )
