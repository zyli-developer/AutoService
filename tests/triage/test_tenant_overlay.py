"""Tenant overlay for classify_intent.yaml — §4.2 of the spec."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from autoservice.model_router import FastClassifier, AgentRole, Intent
from autoservice.tenant_triage_config import (
    load_classify_intent_config,
    _merge_intent_config,
)


@pytest.fixture()
def tenant_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a tmp cwd with a fake plugin overlay for tenant ``acme``."""
    plugins = tmp_path / "plugins" / "acme" / "classify_intent.yaml"
    plugins.parent.mkdir(parents=True)
    plugins.write_text(
        yaml.safe_dump({
            "intents": {
                "purchase_intent": {
                    "keywords": ["委托", "retainer", "聘请"],
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_deep_merge_replaces_keywords_preserves_other_fields():
    global_cfg = {
        "intents": {
            "purchase_intent": {
                "keywords": ["买", "pricing"],
                "route_to": "lead",
                "model_tier": "slow",
                "priority": "high",
            },
        },
        "confidence": {"high": 0.8, "medium": 0.6, "low": 0.3, "uncertain": 0.0},
    }
    overlay = {"intents": {"purchase_intent": {"keywords": ["委托"]}}}
    merged = _merge_intent_config(global_cfg, overlay)
    assert merged["intents"]["purchase_intent"]["keywords"] == ["委托"]
    assert merged["intents"]["purchase_intent"]["route_to"] == "lead"
    assert merged["intents"]["purchase_intent"]["priority"] == "high"
    assert merged["confidence"]["high"] == 0.8


def test_load_without_tenant_returns_global(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_classify_intent_config(tenant_id=None)
    assert "intents" in cfg and "confidence" in cfg


def test_load_with_tenant_applies_overlay(tenant_cwd):
    cfg = load_classify_intent_config(tenant_id="acme")
    assert cfg["intents"]["purchase_intent"]["keywords"] == ["委托", "retainer", "聘请"]
    # Non-overlaid intents unchanged.
    assert "投诉" in cfg["intents"]["complaint"]["keywords"]


def test_fast_classifier_per_tenant(tenant_cwd):
    FastClassifier.clear_tenant_cache()
    clf = FastClassifier.for_tenant("acme")
    # After overlay, "价格" alone is no longer a purchase keyword for this tenant.
    result = clf.classify("价格")
    assert result.route_to != AgentRole.LEAD
    # But "委托" now triggers purchase.
    result2 = clf.classify("想委托你们处理")
    assert result2.route_to == AgentRole.LEAD
