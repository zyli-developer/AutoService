from __future__ import annotations

import os
from pathlib import Path

import yaml


class TermLoader:
    """Load i18n terminology and render prompt prefixes for the translate agent."""

    def __init__(
        self,
        terms_dir: str | None = None,
        tenant_terms_path: str | None = None,
    ) -> None:
        if terms_dir is None:
            terms_dir = str(Path(__file__).parent / "terms")
        self._terms_dir = Path(terms_dir)
        self._tenant_path = Path(tenant_terms_path) if tenant_terms_path else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_terms(self, lang: str) -> list[dict]:
        """Load terms for *lang*, merging tenant overrides (tenant wins on same id)."""
        terms = self._load_global(lang)
        if not terms:
            return []
        if self._tenant_path and self._tenant_path.is_file():
            terms = self._merge_overrides(terms, lang)
        return terms

    def render_prompt_prefix(self, lang: str, max_tokens: int = 2000) -> str:
        """Render a terminology table suitable as a prompt prefix.

        Uses the heuristic 1 token ~ 4 chars for truncation.
        """
        terms = self.load_terms(lang)
        if not terms:
            return ""

        max_chars = max_tokens * 4
        lines: list[str] = [
            f"术语表 ({lang}):",
            "| 英文 | 翻译 |",
            "|------|------|",
        ]
        header_len = sum(len(l) + 1 for l in lines)
        used = header_len

        for t in terms:
            en_text = t.get("en", "")
            local_text = t.get(lang, en_text)
            row = f"| {en_text} | {local_text} |"
            row_len = len(row) + 1  # +1 for newline
            if used + row_len > max_chars:
                break
            lines.append(row)
            used += row_len

        return "\n".join(lines) + "\n"

    def list_languages(self) -> list[str]:
        """Return sorted list of available language codes."""
        if not self._terms_dir.is_dir():
            return []
        langs: list[str] = []
        for f in self._terms_dir.iterdir():
            if f.suffix in (".yaml", ".yml") and f.stem != "__pycache__":
                langs.append(f.stem)
        return sorted(langs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_global(self, lang: str) -> list[dict]:
        path = self._terms_dir / f"{lang}.yaml"
        if not path.is_file():
            return []
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not data or "terms" not in data:
            return []
        return list(data["terms"])

    def _merge_overrides(self, terms: list[dict], lang: str) -> list[dict]:
        assert self._tenant_path is not None
        with open(self._tenant_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not data or "overrides" not in data:
            return terms

        overrides_by_id: dict[str, dict] = {
            o["id"]: o for o in data["overrides"] if "id" in o
        }

        merged: list[dict] = []
        seen_ids: set[str] = set()
        for t in terms:
            tid = t.get("id", "")
            seen_ids.add(tid)
            if tid in overrides_by_id:
                override = overrides_by_id[tid]
                merged_term = dict(t)
                for key, val in override.items():
                    if key != "id":
                        merged_term[key] = val
                merged.append(merged_term)
            else:
                merged.append(t)

        # Append new ids from tenant that don't exist in global
        for oid, override in overrides_by_id.items():
            if oid not in seen_ids:
                merged.append(override)

        return merged
