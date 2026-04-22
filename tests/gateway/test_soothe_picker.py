"""Unit tests for SoothePicker — context-aware placeholder selection."""
from __future__ import annotations

import random
from pathlib import Path

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
