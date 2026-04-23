"""Contract tests for autoservice/soothe_templates.yaml.

Enforces the spec §6 rules at rest (CI-time), so they cannot drift:
  - Required fallback per language exists and is non-empty
  - Every template.intent exists in classify_intent.yaml (or is '*')
  - Every line is ≤ 30 characters
  - Every lang is 'zh' or 'en'
  - Every template has a non-empty 'lines' list
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SOOTHE_PATH = _ROOT / "autoservice" / "soothe_templates.yaml"
_INTENTS_PATH = _ROOT / "autoservice" / "classify_intent.yaml"


@pytest.fixture(scope="module")
def bank() -> dict:
    with _SOOTHE_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def known_intents() -> set[str]:
    with _INTENTS_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return set((data.get("intents") or {}).keys())


def test_yaml_parses(bank):
    assert isinstance(bank, dict)
    assert bank.get("version") == 1


def test_fallback_zh_nonempty(bank):
    fb = bank.get("defaults", {}).get("fallback", {}).get("zh", [])
    assert fb, "defaults.fallback.zh must be a non-empty list"


def test_fallback_en_nonempty(bank):
    fb = bank.get("defaults", {}).get("fallback", {}).get("en", [])
    assert fb, "defaults.fallback.en must be a non-empty list"


def test_all_templates_have_lines(bank):
    for entry in bank.get("templates", []):
        assert entry.get("lines"), f"template {entry.get('id')!r} has empty lines"


def test_all_lang_enum(bank):
    for entry in bank.get("templates", []):
        assert entry["lang"] in {"zh", "en"}, (
            f"template {entry['id']!r} has invalid lang={entry['lang']!r}"
        )


def test_line_length_budget(bank):
    budget = 30
    for entry in bank.get("templates", []):
        for line in entry["lines"]:
            assert len(line) <= budget, (
                f"template {entry['id']!r} line too long ({len(line)} > {budget}): {line!r}"
            )
    for lang, lines in bank.get("defaults", {}).get("fallback", {}).items():
        for line in lines:
            assert len(line) <= budget, (
                f"defaults.fallback.{lang} line too long ({len(line)} > {budget}): {line!r}"
            )


def test_intent_alignment(bank, known_intents):
    for entry in bank.get("templates", []):
        intent = entry["intent"]
        if intent == "*":
            continue
        assert intent in known_intents, (
            f"template {entry['id']!r} uses intent {intent!r} "
            f"not defined in classify_intent.yaml (known={sorted(known_intents)})"
        )


#: Template IDs that MUST exist in the bank. A YAML truncation bug that
#: dropped the `templates:` list (leaving only `version:` + `defaults:`)
#: would silently pass the other contract tests because they iterate
#: over `templates` which would be empty. This test is the structural
#: canary.
REQUIRED_TEMPLATE_IDS = frozenset({
    "complaint_zh",
    "complaint_en",
    "product_inquiry_zh",
    "product_inquiry_en",
    "purchase_intent_zh",
    "purchase_intent_en",
    "general_question_zh",
    "general_question_en",
})


def test_required_template_ids_present(bank):
    present = {entry["id"] for entry in bank.get("templates", [])}
    missing = REQUIRED_TEMPLATE_IDS - present
    assert not missing, (
        f"required template IDs missing from soothe_templates.yaml: "
        f"{sorted(missing)}"
    )
