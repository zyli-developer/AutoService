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
from pathlib import Path
from typing import Any

import yaml


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
        # Fallback: language-level defaults. Empty fallback is a bank
        # authoring bug — Task 4 validation will raise at load time,
        # but until then return a benign empty-text sentinel rather
        # than letting random.choice([]) raise IndexError.
        fb_lines = self._fallback_by_lang.get(lang_norm, [])
        text = self._rng.choice(fb_lines) if fb_lines else ""
        return SoothePick(
            template_id=f"fallback_{lang_norm}",
            text=text,
        )
