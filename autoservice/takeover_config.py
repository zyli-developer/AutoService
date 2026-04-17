"""Takeover/release configuration loading.

Resolves from .autoservice/config.local.yaml 'takeover' section, falling
back to hardcoded defaults so dev environments work without a config file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from socialware.config import load_config


@dataclass(frozen=True)
class TakeoverConfig:
    idle_timeout_ms: int = 30_000
    warning_ms: int = 5_000
    offline_grace_ms: int = 30_000


DEFAULT_TAKEOVER_CONFIG = TakeoverConfig()


def load_takeover_config(source: Path | Mapping[str, Any] | None) -> TakeoverConfig:
    """Load takeover config from a yaml path OR a parsed dict. None / missing → defaults."""
    if source is None:
        return DEFAULT_TAKEOVER_CONFIG

    if isinstance(source, Path):
        if not source.exists():
            return DEFAULT_TAKEOVER_CONFIG
        try:
            raw = load_config(source)
        except Exception:
            return DEFAULT_TAKEOVER_CONFIG
    else:
        raw = source

    section = (raw or {}).get("takeover") or {}
    return TakeoverConfig(
        idle_timeout_ms=int(section.get("idle_timeout_ms", DEFAULT_TAKEOVER_CONFIG.idle_timeout_ms)),
        warning_ms=int(section.get("warning_ms", DEFAULT_TAKEOVER_CONFIG.warning_ms)),
        offline_grace_ms=int(section.get("offline_grace_ms", DEFAULT_TAKEOVER_CONFIG.offline_grace_ms)),
    )
