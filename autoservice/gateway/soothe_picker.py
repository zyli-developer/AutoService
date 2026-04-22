"""Context-aware placeholder text picker.

Selects a soothing line from a declarative template bank, keyed by the
``intent`` produced by the triage agent and the detected language. This
replaces the generic ``"正在为您查询，请稍候..."`` placeholder with
something that reflects what the user just said.

Design: docs/superpowers/specs/2026-04-23-soothe-placeholder-design.md
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("autoservice.gateway.soothe")


@dataclass(frozen=True)
class SoothePick:
    """Result of ``SoothePicker.pick()``: the chosen template id and text."""
    template_id: str
    text: str


class SoothePicker:
    """Pick a soothe line keyed by ``(intent × lang)``.

    Templates are held in memory after construction; ``pick()`` performs
    no I/O. The bank can be supplied directly (tests) or loaded from YAML
    (production — see from_yaml).
    """

    def __init__(
        self,
        bank: dict[str, Any],
        rng: random.Random | None = None,
        known_intents: set[str] | None = None,
    ) -> None:
        self._rng = rng or random.Random()
        self._index: dict[tuple[str, str], tuple[str, list[str]]] = {}
        seen_keys: set[tuple[str, str]] = set()
        required = ("id", "intent", "lang", "lines")
        for entry in bank.get("templates", []):
            for k in required:
                if k not in entry:
                    raise ValueError(
                        f"soothe template entry {entry!r} missing required key {k!r}"
                    )
            tid = entry["id"]
            intent = entry["intent"]
            lang = entry["lang"]
            lines = list(entry["lines"])
            if not lines:
                raise ValueError(
                    f"template {tid!r} (intent={intent!r}, lang={lang!r}) has empty 'lines'"
                )
            key = (intent, lang)
            if key in seen_keys:
                log.warning(
                    "soothe template %r has duplicate (intent=%r, lang=%r) — "
                    "previous entry is overwritten",
                    tid, intent, lang,
                )
            seen_keys.add(key)
            if known_intents is not None and intent != "*" and intent not in known_intents:
                log.warning(
                    "soothe template %r uses unknown intent %r "
                    "(not in classify_intent.yaml); loading anyway",
                    tid, intent,
                )
            self._index[key] = (tid, lines)
        self._fallback_by_lang: dict[str, list[str]] = dict(
            bank.get("defaults", {}).get("fallback", {})
        )
        for required_lang in ("zh", "en"):
            fb = self._fallback_by_lang.get(required_lang, [])
            if not fb:
                raise ValueError(
                    f"defaults.fallback.{required_lang} is missing or empty"
                )

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        rng: random.Random | None = None,
        known_intents: set[str] | None = None,
    ) -> "SoothePicker":
        """Load template bank from a YAML file."""
        with path.open("r", encoding="utf-8") as fh:
            bank = yaml.safe_load(fh)
        return cls(bank=bank, rng=rng, known_intents=known_intents)

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
        # 3. defaults.fallback[lang]. Guaranteed non-empty by
        # __init__ validation, but the `if fb_lines else ""` guard
        # remains as a belt-and-braces safeguard against future refactors.
        fb_lines = self._fallback_by_lang.get(lang_norm, [])
        text = self._rng.choice(fb_lines) if fb_lines else ""
        return SoothePick(
            template_id=f"fallback_{lang_norm}",
            text=text,
        )


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
    except (OSError, yaml.YAMLError):
        log.warning("classify_intent.yaml not readable or malformed at %s", path)
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
