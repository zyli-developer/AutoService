"""Tenant overlay loader for classify_intent.yaml.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §4.2

Lookup order:
  1. .autoservice/sandbox/<tenant_id>/classify_intent.yaml  (master side)
  2. plugins/<tenant_id>/classify_intent.yaml                (fork side)
  3. autoservice/classify_intent.yaml                         (global)

Merge semantics:
  intents.<name>.keywords             — REPLACED (not appended)
  intents.<name>.{description, route_to, model_tier, priority} — per-field override
  confidence.{high, medium, low, uncertain}                    — per-field override
  timeouts / model_tiers              — NOT overridable (blast-radius guard)
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("triage.config")

_GLOBAL_PATH = Path(__file__).parent / "classify_intent.yaml"

_OVERLAY_ALLOWED_TOP = {"intents", "confidence"}
_OVERLAY_ALLOWED_INTENT = {"description", "keywords", "route_to", "model_tier", "priority"}
_OVERLAY_ALLOWED_CONFIDENCE = {"high", "medium", "low", "uncertain"}


def _tenant_overlay_path(tenant_id: str) -> Path | None:
    """Return the first existing overlay path, or None."""
    if not tenant_id or "/" in tenant_id or "\\" in tenant_id or ".." in tenant_id:
        return None
    cwd = Path.cwd()
    for candidate in (
        cwd / ".autoservice" / "sandbox" / tenant_id / "classify_intent.yaml",
        cwd / "plugins" / tenant_id / "classify_intent.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _merge_intent_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Apply tenant overlay on top of global config (deep copy, immutable result)."""
    merged = copy.deepcopy(base)
    for top_key, top_val in overlay.items():
        if top_key not in _OVERLAY_ALLOWED_TOP:
            log.warning("Ignoring non-overridable overlay key: %s", top_key)
            continue
        if top_key == "intents":
            for intent_name, intent_overlay in top_val.items():
                base_intent = merged["intents"].get(intent_name)
                if base_intent is None:
                    log.warning("Overlay references unknown intent: %s", intent_name)
                    continue
                for field, value in intent_overlay.items():
                    if field not in _OVERLAY_ALLOWED_INTENT:
                        log.warning("Ignoring non-overridable intent field: %s", field)
                        continue
                    base_intent[field] = value  # keywords replacement; other: scalar override
        elif top_key == "confidence":
            for field, value in top_val.items():
                if field not in _OVERLAY_ALLOWED_CONFIDENCE:
                    log.warning("Ignoring non-overridable confidence field: %s", field)
                    continue
                merged["confidence"][field] = value
    return merged


def load_classify_intent_config(tenant_id: str | None) -> dict[str, Any]:
    """Load the global config, optionally deep-merged with a tenant overlay."""
    with _GLOBAL_PATH.open(encoding="utf-8") as f:
        base = yaml.safe_load(f)
    if tenant_id is None:
        return base
    overlay_path = _tenant_overlay_path(tenant_id)
    if overlay_path is None:
        return base
    try:
        overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Failed to read tenant overlay %s: %s — using global", overlay_path, exc)
        return base
    return _merge_intent_config(base, overlay)
