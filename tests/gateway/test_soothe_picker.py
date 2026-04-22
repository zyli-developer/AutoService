"""Unit tests for SoothePicker — context-aware placeholder selection."""
from __future__ import annotations

import random

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


import yaml
from pathlib import Path


def test_load_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "soothe.yaml"
    yaml_path.write_text(
        yaml.safe_dump(_bank()),
        encoding="utf-8",
    )
    picker = SoothePicker.from_yaml(yaml_path, rng=random.Random(0))
    pick = picker.pick(intent="complaint", lang="zh")
    assert pick.template_id == "complaint_zh"
