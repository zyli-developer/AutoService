"""Unit tests for SoothePicker — context-aware placeholder selection."""
from __future__ import annotations

import random
from pathlib import Path

import pytest
import yaml

from autoservice.gateway.soothe_picker import SoothePick, SoothePicker


def _bank():
    """Minimal in-memory template bank for direct construction tests."""
    return {
        "version": 1,
        "defaults": {
            "fallback": {
                "zh": ["好的，我帮您看看…"],
                "en": ["Sure, one moment…"],
            },
        },
        "templates": [
            {
                "id": "complaint_zh",
                "intent": "complaint",
                "lang": "zh",
                "lines": ["很抱歉给您添麻烦，我这就核实…"],
            },
            {
                "id": "complaint_en",
                "intent": "complaint",
                "lang": "en",
                "lines": ["So sorry — checking now…"],
            },
        ],
    }


def test_pick_exact_match_zh():
    picker = SoothePicker(bank=_bank(), rng=random.Random(0))
    pick = picker.pick(intent="complaint", lang="zh")
    assert isinstance(pick, SoothePick)
    assert pick.template_id == "complaint_zh"
    assert pick.text == "很抱歉给您添麻烦，我这就核实…"


def test_pick_exact_match_en():
    picker = SoothePicker(bank=_bank(), rng=random.Random(0))
    pick = picker.pick(intent="complaint", lang="en")
    assert pick.template_id == "complaint_en"
    assert pick.text == "So sorry — checking now…"


def test_load_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "soothe.yaml"
    yaml_path.write_text(
        yaml.safe_dump(_bank()),
        encoding="utf-8",
    )
    picker = SoothePicker.from_yaml(yaml_path, rng=random.Random(0))
    pick = picker.pick(intent="complaint", lang="zh")
    assert pick.template_id == "complaint_zh"
    assert pick.text == "很抱歉给您添麻烦，我这就核实…"


def _bank_with_wildcard():
    b = _bank()
    b["templates"].append({
        "id": "wildcard_zh",
        "intent": "*",
        "lang": "zh",
        "lines": ["稍等，我先看一眼…"],
    })
    return b


def test_unknown_intent_falls_to_wildcard():
    picker = SoothePicker(bank=_bank_with_wildcard(), rng=random.Random(0))
    pick = picker.pick(intent="unknown_xyz", lang="zh")
    assert pick.template_id == "wildcard_zh"
    assert pick.text == "稍等，我先看一眼…"


def test_unknown_intent_no_wildcard_falls_to_defaults():
    picker = SoothePicker(bank=_bank(), rng=random.Random(0))  # no wildcard entry
    pick = picker.pick(intent="unknown_xyz", lang="zh")
    assert pick.template_id == "fallback_zh"
    assert pick.text == "好的，我帮您看看…"


def test_none_intent_goes_to_wildcard_or_defaults():
    picker = SoothePicker(bank=_bank_with_wildcard(), rng=random.Random(0))
    pick = picker.pick(intent=None, lang="zh")
    # intent=None should behave the same as unknown intent
    assert pick.template_id == "wildcard_zh"


def test_unknown_lang_normalized_to_zh():
    picker = SoothePicker(bank=_bank(), rng=random.Random(0))
    pick = picker.pick(intent="complaint", lang="fr")
    # lang 'fr' does not start with 'en' → normalized to 'zh'
    assert pick.template_id == "complaint_zh"


def test_missing_fallback_zh_raises():
    bank = _bank()
    del bank["defaults"]["fallback"]["zh"]
    with pytest.raises(ValueError, match="defaults.fallback.zh"):
        SoothePicker(bank=bank)


def test_missing_fallback_en_raises():
    bank = _bank()
    del bank["defaults"]["fallback"]["en"]
    with pytest.raises(ValueError, match="defaults.fallback.en"):
        SoothePicker(bank=bank)


def test_empty_fallback_raises():
    bank = _bank()
    bank["defaults"]["fallback"]["zh"] = []
    with pytest.raises(ValueError, match="defaults.fallback.zh"):
        SoothePicker(bank=bank)


def test_empty_template_lines_raises():
    bank = _bank()
    bank["templates"][0]["lines"] = []
    with pytest.raises(ValueError, match="complaint_zh.*lines"):
        SoothePicker(bank=bank)


def test_unknown_intent_in_bank_warns_but_loads(caplog):
    import logging
    bank = _bank()
    bank["templates"].append({
        "id": "fake_intent_zh",
        "intent": "fake_intent_not_in_classify_yaml",
        "lang": "zh",
        "lines": ["test"],
    })
    known_intents = {"complaint", "product_inquiry"}
    with caplog.at_level(logging.WARNING):
        SoothePicker(bank=bank, known_intents=known_intents)
    assert any(
        "fake_intent_not_in_classify_yaml" in rec.message
        for rec in caplog.records
    )


def test_missing_required_key_raises():
    """A template entry missing 'id', 'intent', 'lang', or 'lines' must raise at load time."""
    bank = _bank()
    bank["templates"].append({
        # missing 'id'
        "intent": "complaint",
        "lang": "zh",
        "lines": ["test"],
    })
    with pytest.raises(ValueError, match="missing required key.*id"):
        SoothePicker(bank=bank)


def test_duplicate_intent_lang_warns(caplog):
    """Two templates sharing (intent, lang) is a template-authoring bug —
    the second entry silently overwrites the first. Warn so the author
    notices. Loading still succeeds."""
    import logging
    bank = _bank()
    bank["templates"].append({
        "id": "complaint_zh_dup",
        "intent": "complaint",   # collides with existing complaint_zh
        "lang": "zh",
        "lines": ["duplicate"],
    })
    with caplog.at_level(logging.WARNING):
        SoothePicker(bank=bank)
    assert any(
        "duplicate" in rec.message.lower() and "complaint" in rec.message.lower()
        for rec in caplog.records
    )
