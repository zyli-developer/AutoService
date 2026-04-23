# Soothe Placeholder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 1.5s-delayed static placeholder in the gateway's `_drain_with_placeholder` with an immediate, context-aware line selected by a new `SoothePicker` keyed on `(intent × lang)` pulled from triage output.

**Architecture:** Keep the existing placeholder race architecture in `autoservice/gateway/message_router.py` unchanged. Swap just two things: (1) the text source — `_placeholder_text()` gains an `intent` arg and defers to a new `SoothePicker` singleton loaded from `autoservice/soothe_templates.yaml`; (2) the default `PLACEHOLDER_DELAY_S` drops from `1.5` to `0.0`. A `SOOTHE_PLACEHOLDER_ENABLED=0` env flag restores baseline behavior.

**Tech Stack:** Python 3.11+, PyYAML (already in project deps via `classify_intent.yaml`), pytest, existing `tests/gateway/test_drain_with_placeholder.py` pattern.

**Spec:** [docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md](../specs/2026-04-23-soothe-placeholder-design.md)

---

## File map

| Operation | Path | Purpose |
|---|---|---|
| Create | `autoservice/gateway/soothe_picker.py` | `SoothePick` dataclass, `SoothePicker` class with `pick()`, `get_picker()` singleton |
| Create | `autoservice/soothe_templates.yaml` | Declarative template bank (4 intents × 2 langs + fallbacks) |
| Modify | `autoservice/gateway/message_router.py` | Change `_placeholder_text` signature + body; new `SOOTHE_ENABLED` constant; change `PLACEHOLDER_DELAY_S` default; thread `intent` through `_drain_with_placeholder` and its call site (~L1430) |
| Create | `tests/gateway/test_soothe_picker.py` | Unit tests: exact match, fallback chain, validation, singleton |
| Create | `tests/contract/test_soothe_templates.py` | Contract test: YAML schema validity, intent alignment with `classify_intent.yaml`, line length |
| Modify | `tests/gateway/test_drain_with_placeholder.py` | Add tests covering new `intent` kwarg; add flag-off regression test |

---

## Task 1: Scaffold SoothePicker with in-memory exact match

**Files:**
- Create: `autoservice/gateway/soothe_picker.py`
- Create: `tests/gateway/test_soothe_picker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/gateway/test_soothe_picker.py`:

```python
"""Unit tests for SoothePicker — context-aware placeholder selection."""
from __future__ import annotations

import random

import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoservice.gateway.soothe_picker'`

- [ ] **Step 3: Write minimal implementation**

Create `autoservice/gateway/soothe_picker.py`:

```python
"""Context-aware placeholder text picker.

Selects a soothing line from a declarative template bank, keyed by the
``intent`` produced by the triage agent and the detected language. This
replaces the generic ``"正在为您查询，请稍候..."`` placeholder with
something that reflects what the user just said.

Design: docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SoothePick:
    """Result of ``SoothePicker.pick()``: the chosen template id and text."""
    template_id: str
    text: str


class SoothePicker:
    """Pick a soothe line keyed by ``(intent × lang)``.

    Templates are held in memory after construction; ``pick()`` performs
    no I/O. The bank can be supplied directly (tests) or loaded from YAML
    (production — see Task 2).
    """

    def __init__(
        self,
        bank: dict[str, Any],
        rng: random.Random | None = None,
    ) -> None:
        self._rng = rng or random.Random()
        # Index: (intent, lang) -> (template_id, lines)
        self._index: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for entry in bank.get("templates", []):
            key = (entry["intent"], entry["lang"])
            self._index[key] = (entry["id"], list(entry["lines"]))
        self._fallback_by_lang: dict[str, list[str]] = dict(
            bank.get("defaults", {}).get("fallback", {})
        )

    def pick(self, *, intent: str | None, lang: str | None) -> SoothePick:
        lang_norm = "en" if (lang and lang.lower().startswith("en")) else "zh"
        if intent:
            entry = self._index.get((intent, lang_norm))
            if entry:
                tid, lines = entry
                return SoothePick(template_id=tid, text=self._rng.choice(lines))
        # Fallback: language-level defaults
        fb_lines = self._fallback_by_lang.get(lang_norm, [])
        return SoothePick(
            template_id=f"fallback_{lang_norm}",
            text=self._rng.choice(fb_lines),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: PASS — both `test_pick_exact_match_zh` and `test_pick_exact_match_en`

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/soothe_picker.py tests/gateway/test_soothe_picker.py
git commit -m "feat(gateway): add SoothePicker scaffold with exact-match lookup

First slice of the soothe placeholder feature: in-memory (intent × lang)
indexed template bank + pick() that returns a SoothePick. YAML loading,
fallback chain, validation, and integration come in subsequent tasks.

Spec: docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md"
```

---

## Task 2: YAML loading

**Files:**
- Modify: `autoservice/gateway/soothe_picker.py`
- Modify: `tests/gateway/test_soothe_picker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_soothe_picker.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/test_soothe_picker.py::test_load_from_yaml -v`
Expected: FAIL with `AttributeError: type object 'SoothePicker' has no attribute 'from_yaml'`

- [ ] **Step 3: Add `from_yaml` classmethod to SoothePicker**

In `autoservice/gateway/soothe_picker.py`, add imports and classmethod:

```python
from pathlib import Path

import yaml
```

Inside `SoothePicker`, add:

```python
    @classmethod
    def from_yaml(
        cls,
        path: Path,
        rng: random.Random | None = None,
    ) -> "SoothePicker":
        """Load template bank from a YAML file."""
        with path.open("r", encoding="utf-8") as fh:
            bank = yaml.safe_load(fh)
        return cls(bank=bank, rng=rng)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/soothe_picker.py tests/gateway/test_soothe_picker.py
git commit -m "feat(gateway): SoothePicker.from_yaml — load template bank from disk"
```

---

## Task 3: Fallback chain — wildcard intent and defaults

**Files:**
- Modify: `autoservice/gateway/soothe_picker.py`
- Modify: `tests/gateway/test_soothe_picker.py`

The picker currently skips straight to `defaults.fallback[lang]` when an intent doesn't match. Per spec §5.1 we want an intermediate step: if `(intent, lang)` misses, try `("*", lang)` before falling to defaults.

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_soothe_picker.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_soothe_picker.py -v -k "wildcard or defaults or none_intent"`
Expected: FAIL — tests for wildcard return `fallback_zh` instead of `wildcard_zh`

- [ ] **Step 3: Update pick() fallback chain**

Replace `pick()` body in `autoservice/gateway/soothe_picker.py`:

```python
    def pick(self, *, intent: str | None, lang: str | None) -> SoothePick:
        lang_norm = "en" if (lang and lang.lower().startswith("en")) else "zh"
        # 1. Exact (intent, lang)
        if intent:
            entry = self._index.get((intent, lang_norm))
            if entry:
                tid, lines = entry
                return SoothePick(template_id=tid, text=self._rng.choice(lines))
        # 2. Wildcard ("*", lang)
        wildcard = self._index.get(("*", lang_norm))
        if wildcard:
            tid, lines = wildcard
            return SoothePick(template_id=tid, text=self._rng.choice(lines))
        # 3. defaults.fallback[lang]
        fb_lines = self._fallback_by_lang.get(lang_norm, [])
        return SoothePick(
            template_id=f"fallback_{lang_norm}",
            text=self._rng.choice(fb_lines),
        )
```

- [ ] **Step 4: Run all picker tests**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: all PASS (originals + 4 new)

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/soothe_picker.py tests/gateway/test_soothe_picker.py
git commit -m "feat(gateway): SoothePicker — 3-step fallback chain (exact → wildcard → defaults)"
```

---

## Task 4: Load-time validation + unknown-intent warning

**Files:**
- Modify: `autoservice/gateway/soothe_picker.py`
- Modify: `tests/gateway/test_soothe_picker.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_soothe_picker.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_soothe_picker.py -v -k "missing or empty or unknown_intent_in_bank"`
Expected: FAIL — no validation currently raises

- [ ] **Step 3: Add validation to `__init__`**

Update `autoservice/gateway/soothe_picker.py`. Add `logging`:

```python
import logging

log = logging.getLogger("soothe.picker")
```

Update `__init__` signature and body:

```python
    def __init__(
        self,
        bank: dict[str, Any],
        rng: random.Random | None = None,
        known_intents: set[str] | None = None,
    ) -> None:
        self._rng = rng or random.Random()
        self._index: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for entry in bank.get("templates", []):
            tid = entry.get("id", "<unknown>")
            intent = entry["intent"]
            lang = entry["lang"]
            lines = list(entry.get("lines", []))
            if not lines:
                raise ValueError(
                    f"template {tid!r} (intent={intent!r}, lang={lang!r}) has empty 'lines'"
                )
            if known_intents is not None and intent != "*" and intent not in known_intents:
                log.warning(
                    "soothe template %r uses unknown intent %r "
                    "(not in classify_intent.yaml); loading anyway",
                    tid, intent,
                )
            self._index[(intent, lang)] = (tid, lines)
        self._fallback_by_lang: dict[str, list[str]] = dict(
            bank.get("defaults", {}).get("fallback", {})
        )
        # defaults.fallback.{zh,en} must exist and be non-empty
        for required_lang in ("zh", "en"):
            fb = self._fallback_by_lang.get(required_lang, [])
            if not fb:
                raise ValueError(
                    f"defaults.fallback.{required_lang} is missing or empty"
                )
```

- [ ] **Step 4: Run all picker tests**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/soothe_picker.py tests/gateway/test_soothe_picker.py
git commit -m "feat(gateway): SoothePicker — load-time validation + unknown-intent warning"
```

---

## Task 5: `get_picker()` singleton with lazy YAML load

**Files:**
- Modify: `autoservice/gateway/soothe_picker.py`
- Modify: `tests/gateway/test_soothe_picker.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_soothe_picker.py`:

```python
def test_get_picker_returns_singleton(monkeypatch, tmp_path):
    from autoservice.gateway import soothe_picker as sp

    yaml_path = tmp_path / "soothe.yaml"
    yaml_path.write_text(yaml.safe_dump(_bank()), encoding="utf-8")

    monkeypatch.setattr(sp, "_DEFAULT_TEMPLATES_PATH", yaml_path)
    monkeypatch.setattr(sp, "_singleton", None)  # reset cache

    a = sp.get_picker()
    b = sp.get_picker()
    assert a is b


def test_get_picker_loads_default_yaml(monkeypatch, tmp_path):
    from autoservice.gateway import soothe_picker as sp

    yaml_path = tmp_path / "soothe.yaml"
    yaml_path.write_text(yaml.safe_dump(_bank()), encoding="utf-8")

    monkeypatch.setattr(sp, "_DEFAULT_TEMPLATES_PATH", yaml_path)
    monkeypatch.setattr(sp, "_singleton", None)

    picker = sp.get_picker()
    pick = picker.pick(intent="complaint", lang="zh")
    assert pick.template_id == "complaint_zh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_soothe_picker.py -v -k "singleton or default_yaml"`
Expected: FAIL — `get_picker` not defined

- [ ] **Step 3: Add singleton machinery**

Append to `autoservice/gateway/soothe_picker.py`:

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TEMPLATES_PATH: Path = _PROJECT_ROOT / "autoservice" / "soothe_templates.yaml"

_singleton: SoothePicker | None = None


def _load_known_intents() -> set[str]:
    """Read intent names from classify_intent.yaml for load-time validation."""
    path = _PROJECT_ROOT / "autoservice" / "classify_intent.yaml"
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return set((data.get("intents") or {}).keys())
    except OSError:
        log.warning("classify_intent.yaml not readable at %s", path)
        return set()


def get_picker() -> SoothePicker:
    """Return the process-level singleton picker.

    First call loads ``soothe_templates.yaml``; subsequent calls reuse
    the same instance. Use ``monkeypatch.setattr(..., _singleton, None)``
    in tests to force a fresh load.
    """
    global _singleton
    if _singleton is None:
        _singleton = SoothePicker.from_yaml(
            _DEFAULT_TEMPLATES_PATH,
            known_intents=_load_known_intents(),
        )
    return _singleton
```

Update `from_yaml` to forward `known_intents`:

```python
    @classmethod
    def from_yaml(
        cls,
        path: Path,
        rng: random.Random | None = None,
        known_intents: set[str] | None = None,
    ) -> "SoothePicker":
        with path.open("r", encoding="utf-8") as fh:
            bank = yaml.safe_load(fh)
        return cls(bank=bank, rng=rng, known_intents=known_intents)
```

- [ ] **Step 4: Run all picker tests**

Run: `pytest tests/gateway/test_soothe_picker.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/soothe_picker.py tests/gateway/test_soothe_picker.py
git commit -m "feat(gateway): SoothePicker.get_picker — process-level singleton with YAML load"
```

---

## Task 6: Ship `autoservice/soothe_templates.yaml` with contract tests

**Files:**
- Create: `autoservice/soothe_templates.yaml`
- Create: `tests/contract/test_soothe_templates.py`

- [ ] **Step 1: Write the failing contract test**

Create `tests/contract/test_soothe_templates.py`:

```python
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
```

- [ ] **Step 2: Run contract tests to verify they fail**

Run: `pytest tests/contract/test_soothe_templates.py -v`
Expected: FAIL — file does not exist

- [ ] **Step 3: Create the template bank**

Create `autoservice/soothe_templates.yaml`:

```yaml
# Soothe Placeholder Template Bank
# Consumed by autoservice/gateway/soothe_picker.py
# Spec: docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md
#
# Lookup: (intent × lang) → 3-step fallback:
#   1. (intent, lang)       exact
#   2. ("*", lang)          same-language wildcard
#   3. defaults.fallback    language-level fallback (required)
#
# Authoring rules (contract-enforced):
#   - Each line ≤ 30 characters
#   - lang must be 'zh' or 'en'
#   - intent must exist in classify_intent.yaml (or be '*')
# Authoring rules (code-review-enforced):
#   - No specific promises (numbers, deadlines)
#   - No product/competitor names
#   - Chinese full-width punctuation; English half-width
#   - End with '…' to signal continuation

version: 1

defaults:
  fallback:
    zh:
      - "好的，我帮您看看…"
      - "收到，正在为您处理…"
      - "稍等，我先确认一下…"
    en:
      - "Got it, let me take a look…"
      - "Sure, one moment…"
      - "Working on it now…"

templates:
  # ── complaint (customer, slow) ────────────────────────
  - id: complaint_zh
    intent: complaint
    lang: zh
    lines:
      - "非常抱歉给您添麻烦，我这就核实…"
      - "理解您的着急，我马上查原因…"
      - "很抱歉让您不愉快，先看一下状态…"

  - id: complaint_en
    intent: complaint
    lang: en
    lines:
      - "So sorry — checking that now…"
      - "That's frustrating, looking into it…"
      - "Apologies, let me find the cause…"

  # ── product_inquiry (customer, slow) ──────────────────
  - id: product_inquiry_zh
    intent: product_inquiry
    lang: zh
    lines:
      - "好的，我帮您看一下具体功能…"
      - "这个我先确认一下细节…"
      - "让我帮您梳理一下支持情况…"

  - id: product_inquiry_en
    intent: product_inquiry
    lang: en
    lines:
      - "Sure, let me look that up for you…"
      - "One sec, checking the details…"
      - "Let me pull up what we support…"

  # ── purchase_intent (lead, slow) ──────────────────────
  - id: purchase_intent_zh
    intent: purchase_intent
    lang: zh
    lines:
      - "好的，我帮您整理一下方案…"
      - "了解您的需求，正在核对…"
      - "稍等，让我给您拉一份报价…"

  - id: purchase_intent_en
    intent: purchase_intent
    lang: en
    lines:
      - "Sure, putting that together…"
      - "Noted — pulling the options…"
      - "Let me grab the pricing for you…"

  # ── general_question (customer, fast) ─────────────────
  - id: general_question_zh
    intent: general_question
    lang: zh
    lines:
      - "好的，让我想想…"
      - "嗯，我看一下…"

  - id: general_question_en
    intent: general_question
    lang: en
    lines:
      - "Let me think…"
      - "One moment…"
```

- [ ] **Step 4: Run contract tests to verify they pass**

Run: `pytest tests/contract/test_soothe_templates.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/soothe_templates.yaml tests/contract/test_soothe_templates.py
git commit -m "feat(autoservice): soothe_templates.yaml initial bank (4 intents × 2 langs)

Contract tests enforce line length, lang enum, intent alignment with
classify_intent.yaml, and non-empty fallback per language."
```

---

## Task 7: Extend `_placeholder_text` to accept `intent`

**Files:**
- Modify: `autoservice/gateway/message_router.py`
- Modify: `tests/gateway/test_drain_with_placeholder.py`

This is the smallest possible integration: just change the text-generation function. Delay semantics and flag gating come in Task 9.

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_drain_with_placeholder.py`:

```python
def test_placeholder_text_with_known_intent_uses_picker(monkeypatch):
    """When intent is known, _placeholder_text returns a soothe line,
    not the static _PLACEHOLDER_TEXT_ZH."""
    from autoservice.gateway import message_router as mr
    from autoservice.gateway import soothe_picker as sp

    # Stub picker to return a deterministic line
    class _StubPicker:
        def pick(self, *, intent, lang):
            return sp.SoothePick(template_id="test_id", text="stubbed soothe")

    monkeypatch.setattr(sp, "_singleton", _StubPicker())
    monkeypatch.setattr(mr, "SOOTHE_ENABLED", True)

    text = mr._placeholder_text(detected_language="zh", intent="complaint")
    assert text == "stubbed soothe"


def test_placeholder_text_picker_failure_falls_back_to_static(monkeypatch, caplog):
    """If picker raises, _placeholder_text falls back to the static
    Chinese/English constants — main flow never breaks on soothe errors."""
    import logging
    from autoservice.gateway import message_router as mr
    from autoservice.gateway import soothe_picker as sp

    class _BrokenPicker:
        def pick(self, *, intent, lang):
            raise RuntimeError("boom")

    monkeypatch.setattr(sp, "_singleton", _BrokenPicker())
    monkeypatch.setattr(mr, "SOOTHE_ENABLED", True)

    with caplog.at_level(logging.ERROR):
        text_zh = mr._placeholder_text(detected_language="zh", intent="complaint")
        text_en = mr._placeholder_text(detected_language="en", intent="complaint")
    assert text_zh == mr._PLACEHOLDER_TEXT_ZH
    assert text_en == mr._PLACEHOLDER_TEXT_EN
    assert any("soothe picker failed" in rec.message.lower() for rec in caplog.records)


def test_placeholder_text_flag_off_uses_static(monkeypatch):
    """With SOOTHE_ENABLED=False, static text is returned regardless of intent."""
    from autoservice.gateway import message_router as mr

    monkeypatch.setattr(mr, "SOOTHE_ENABLED", False)
    assert mr._placeholder_text(detected_language="zh", intent="complaint") == mr._PLACEHOLDER_TEXT_ZH
    assert mr._placeholder_text(detected_language="en", intent="complaint") == mr._PLACEHOLDER_TEXT_EN


def test_placeholder_text_no_intent_still_works(monkeypatch):
    """Legacy callers that don't pass intent still get a valid placeholder
    (picker's fallback chain handles intent=None)."""
    from autoservice.gateway import message_router as mr
    from autoservice.gateway import soothe_picker as sp

    class _StubPicker:
        def pick(self, *, intent, lang):
            return sp.SoothePick(
                template_id=f"fallback_{lang}",
                text="fallback stub",
            )

    monkeypatch.setattr(sp, "_singleton", _StubPicker())
    monkeypatch.setattr(mr, "SOOTHE_ENABLED", True)

    text = mr._placeholder_text(detected_language="zh")  # no intent kwarg
    assert text == "fallback stub"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_drain_with_placeholder.py -v -k "placeholder_text"`
Expected: FAIL — `AttributeError: module 'autoservice.gateway.message_router' has no attribute 'SOOTHE_ENABLED'` and `_placeholder_text` doesn't accept `intent`

- [ ] **Step 3: Modify `_placeholder_text` and add `SOOTHE_ENABLED`**

In `autoservice/gateway/message_router.py`:

Add import near other imports:

```python
import os

from autoservice.gateway import soothe_picker
```

Add constant below the existing placeholder constants (~L816):

```python
#: Module-level kill-switch for the soothe placeholder feature. Read once
#: at import (not per-request) for consistency. Setting
#: SOOTHE_PLACEHOLDER_ENABLED=0 restores the 2026-04-22 baseline behavior:
#: static text + 1.5s delay. See spec §10.
SOOTHE_ENABLED: bool = os.getenv("SOOTHE_PLACEHOLDER_ENABLED", "1") != "0"
```

Replace `_placeholder_text` (current L818-827):

```python
def _placeholder_text(
    detected_language: str | None,
    intent: str | None = None,
) -> str:
    """Localize the placeholder bubble.

    When ``SOOTHE_ENABLED`` is true, delegates to
    :func:`soothe_picker.get_picker` to return a context-aware line keyed
    by ``(intent, lang)``. On any picker exception (or when the feature
    flag is off), falls back to the static ``_PLACEHOLDER_TEXT_*``
    constants — main reply pipeline must never break because of a soothe
    lookup.
    """
    def _static() -> str:
        if detected_language and detected_language.lower().startswith("en"):
            return _PLACEHOLDER_TEXT_EN
        return _PLACEHOLDER_TEXT_ZH

    if not SOOTHE_ENABLED:
        return _static()

    try:
        pick = soothe_picker.get_picker().pick(
            intent=intent, lang=detected_language,
        )
        logger.info(
            "soothe picked intent=%s lang=%s template_id=%s",
            intent, detected_language, pick.template_id,
        )
        return pick.text
    except Exception:
        logger.exception("soothe picker failed — falling back to static text")
        return _static()
```

Also, confirm there is a module-level `logger`. Check for existing `logger = logging.getLogger(...)` near the top of the file; if none exists, add `import logging; logger = logging.getLogger(__name__)` near the other imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/gateway/test_drain_with_placeholder.py -v`
Expected: all PASS (new 4 tests + existing tests still green since signature is backward-compatible — `intent` defaults to `None`)

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/message_router.py tests/gateway/test_drain_with_placeholder.py
git commit -m "feat(gateway): _placeholder_text uses SoothePicker when SOOTHE_ENABLED

Gated behind SOOTHE_PLACEHOLDER_ENABLED env var (default on). Picker
failures transparently fall back to the static _PLACEHOLDER_TEXT_*
constants; main reply pipeline is never broken by soothe issues."
```

---

## Task 8: Thread `intent` through `_drain_with_placeholder` and call site

**Files:**
- Modify: `autoservice/gateway/message_router.py`
- Modify: `tests/gateway/test_drain_with_placeholder.py`

The `_placeholder_text` function now takes `intent`, but `_drain_with_placeholder` still calls it without passing one. Fix the signature chain.

- [ ] **Step 1: Write the failing test**

Append to `tests/gateway/test_drain_with_placeholder.py`:

```python
@pytest.mark.asyncio
async def test_drain_passes_intent_to_placeholder_text(monkeypatch):
    """_drain_with_placeholder forwards ``intent`` to _placeholder_text."""
    from autoservice.gateway import message_router as mr

    captured: dict = {}
    real_fn = mr._placeholder_text

    def _spy(detected_language=None, intent=None):
        captured["lang"] = detected_language
        captured["intent"] = intent
        return real_fn(detected_language, intent)

    monkeypatch.setattr(mr, "_placeholder_text", _spy)
    monkeypatch.setattr(mr, "SOOTHE_ENABLED", False)  # use static path — deterministic

    # Minimal fakes re-using existing helpers in this test file
    engine = MagicMock()
    engine.send_message = AsyncMock(return_value=_msg("stub"))
    engine.edit_message = AsyncMock()
    ws = MagicMock()

    async def _slow_stream():
        # Never yields — forces placeholder branch
        await asyncio.sleep(0.2)
        if False:
            yield None

    # Use a small delay so the test runs fast
    await mr._drain_with_placeholder(
        _slow_stream(),
        engine=engine,
        conv_id="conv-1",
        target_role="customer",
        ws=ws,
        detected_language="zh",
        eligible=True,
        delay_s=0.05,
        intent="complaint",
    )
    assert captured["intent"] == "complaint"
    assert captured["lang"] == "zh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/test_drain_with_placeholder.py::test_drain_passes_intent_to_placeholder_text -v`
Expected: FAIL — `_drain_with_placeholder` does not accept `intent`

- [ ] **Step 3: Add `intent` kwarg to `_drain_with_placeholder`**

In `autoservice/gateway/message_router.py`, update the signature (around L830-840):

```python
async def _drain_with_placeholder(
    iterator: Any,
    *,
    engine: ConversationEngine,
    conv_id: str,
    target_role: str,
    ws: "WebSocket",
    detected_language: str | None = None,
    eligible: bool = True,
    delay_s: float = PLACEHOLDER_DELAY_S,
    intent: str | None = None,
) -> tuple[str, Any | None]:
```

Inside the body, locate the call to `_placeholder_text(detected_language)` (there should be exactly one — use grep to confirm) and change it to:

```python
_placeholder_text(detected_language, intent)
```

- [ ] **Step 4: Update call site**

Find the call site in `autoservice/gateway/message_router.py` (~L1510, inside the message-handling function where `decision = await triage_and_route(...)` is used). The current call looks like:

```python
reply_text, placeholder_msg = await _drain_with_placeholder(
    ...,
    detected_language=detected_language,
    eligible=placeholder_eligible,
    delay_s=PLACEHOLDER_DELAY_S,
)
```

(Exact arguments vary — verify by grepping. If the call passes `delay_s`, keep it.)

Change to include `intent`:

```python
reply_text, placeholder_msg = await _drain_with_placeholder(
    ...,
    detected_language=detected_language,
    eligible=placeholder_eligible,
    delay_s=PLACEHOLDER_DELAY_S,
    intent=getattr(decision, "intent", None) if decision else None,
)
```

Use `getattr(..., None)` so the call is robust to the `decision = None` branch where `triage_and_route` raised and was caught.

- [ ] **Step 5: Run tests**

Run: `pytest tests/gateway/test_drain_with_placeholder.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add autoservice/gateway/message_router.py tests/gateway/test_drain_with_placeholder.py
git commit -m "feat(gateway): thread intent from triage decision through _drain_with_placeholder

Decision.intent now flows to _placeholder_text so the soothe picker can
select a context-aware line. Legacy callers that pass no intent still
get a valid (fallback) placeholder."
```

---

## Task 9: Drop `PLACEHOLDER_DELAY_S` default to 0.0 when flag on

**Files:**
- Modify: `autoservice/gateway/message_router.py`
- Modify: `tests/gateway/test_drain_with_placeholder.py`

Currently the first token races a 1.5s timer before the placeholder is shown. With the picker in place, there is no reason to wait — emit immediately. Under `SOOTHE_ENABLED=False`, restore the 1.5s wait to preserve baseline behavior exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/gateway/test_drain_with_placeholder.py`:

```python
@pytest.mark.asyncio
async def test_default_delay_is_zero_when_enabled(monkeypatch):
    """With soothe on, the default PLACEHOLDER_DELAY_S is effectively 0
    so the placeholder arrives immediately."""
    from autoservice.gateway import message_router as mr

    monkeypatch.setattr(mr, "SOOTHE_ENABLED", True)
    assert mr._effective_placeholder_delay_s() == 0.0


@pytest.mark.asyncio
async def test_default_delay_restores_1p5s_when_disabled(monkeypatch):
    from autoservice.gateway import message_router as mr

    monkeypatch.setattr(mr, "SOOTHE_ENABLED", False)
    assert mr._effective_placeholder_delay_s() == 1.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/gateway/test_drain_with_placeholder.py -v -k "effective_placeholder_delay"`
Expected: FAIL — `_effective_placeholder_delay_s` does not exist

- [ ] **Step 3: Add delay-computing helper and wire it in**

In `autoservice/gateway/message_router.py`, near the `PLACEHOLDER_DELAY_S` constant (~L800), keep the constant at `1.5` so tests and ops can still reference the baseline, and add a helper:

```python
PLACEHOLDER_DELAY_S: float = 1.5   # unchanged: baseline wait for flag-off path


def _effective_placeholder_delay_s() -> float:
    """Resolve the actual delay used at call time.

    With SOOTHE_ENABLED=True, emit the placeholder immediately (0.0s).
    With the flag off, keep the 1.5s race (2026-04-22 baseline).
    """
    return 0.0 if SOOTHE_ENABLED else PLACEHOLDER_DELAY_S
```

Update the default in `_drain_with_placeholder`:

```python
async def _drain_with_placeholder(
    ...,
    delay_s: float | None = None,
    intent: str | None = None,
) -> tuple[str, Any | None]:
    if delay_s is None:
        delay_s = _effective_placeholder_delay_s()
    ...
```

(Callers that pass `delay_s=PLACEHOLDER_DELAY_S` explicitly — if any — still get the old 1.5s behavior. The call site in Task 8 should drop its explicit `delay_s=PLACEHOLDER_DELAY_S` so the helper's resolution kicks in.)

Update the call site to omit `delay_s`:

```python
reply_text, placeholder_msg = await _drain_with_placeholder(
    ...,
    detected_language=detected_language,
    eligible=placeholder_eligible,
    intent=getattr(decision, "intent", None) if decision else None,
)
```

- [ ] **Step 4: Run the whole gateway test suite**

Run: `pytest tests/gateway/ -v`
Expected: all PASS. If any existing test assumed `_drain_with_placeholder` default was `1.5`, update those tests to either (a) set `SOOTHE_ENABLED=False`, or (b) pass `delay_s=1.5` explicitly.

- [ ] **Step 5: Commit**

```bash
git add autoservice/gateway/message_router.py tests/gateway/test_drain_with_placeholder.py
git commit -m "feat(gateway): drop placeholder wait to 0s when soothe enabled

Placeholder now lands in ~50ms (previously 1500ms). Flag-off path keeps
the 1.5s race to preserve exact 2026-04-22 baseline for rollback."
```

---

## Task 10: Smoke + observability spot-check

**Files:** no code changes — verification only.

- [ ] **Step 1: Run full unit + contract + integration suites**

```bash
pytest tests/gateway/ tests/contract/test_soothe_templates.py -v
```

Expected: all PASS.

- [ ] **Step 2: Run the existing placeholder E2E if one exists**

```bash
pytest tests/e2e/ -v -k "placeholder"
```

If no match, this step is a no-op. If matches exist and fail, reconcile (delay assumption, text assumption) by either (a) adjusting the test to tolerate new soothe text, or (b) setting `SOOTHE_PLACEHOLDER_ENABLED=0` in the test's env fixture.

- [ ] **Step 3: Manual smoke against `make run-web`**

```bash
make run-web
# In another terminal / browser, open http://localhost:8000/
# Send: "我的订单怎么三天还没到？" (complaint, zh)
# Observe: placeholder appears within ~50ms with a complaint_zh line,
#          not the static "正在为您查询，请稍候…"
# Then send: "有什么优惠？" (purchase_intent keywords — may match)
# Observe: different placeholder text
```

Document what you observed (which `template_id` shown) in the commit body of a trailing `chore(m3.5):` commit if task tracking is needed. Otherwise no commit for this step.

- [ ] **Step 4: Verify flag kill-switch**

```bash
SOOTHE_PLACEHOLDER_ENABLED=0 make run-web
# Send: "我的订单怎么三天还没到？"
# Observe: the 2026-04-22 baseline behavior:
#          - 1.5s wait before placeholder appears
#          - placeholder text is "正在为您查询，请稍候..."
```

- [ ] **Step 5: No commit for Task 10** unless Step 3/4 revealed required fixes.

---

## Self-review checklist

- Spec §§1-16 each have a corresponding task above, or are explicit non-goals (§8).
- No "TBD" / "TODO" / "similar to" strings.
- `SoothePick`, `SoothePicker`, `get_picker`, `_singleton`, `_DEFAULT_TEMPLATES_PATH`, `_load_known_intents`, `SOOTHE_ENABLED`, `_effective_placeholder_delay_s`, `_placeholder_text(intent=)`, `_drain_with_placeholder(intent=)` — names are consistent between tasks.
- Every test has full test-body code, not a prose summary.
- Every implementation step has the full code to paste/insert.
- Every task ends with a git commit with a concrete message.
- Rollback path (flag off → 1.5s + static text) is exercised by tests in Tasks 7 and 9.
