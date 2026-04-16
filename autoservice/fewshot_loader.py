"""Few-shot injection mechanism for customer agent prompts.

T3A.3 产出 | 2026-04-16
关联: ζ4 T4.10c / US-1.3 / agents/customer/soul.md

Loads merchant-edited conversation examples from tenant YAML and renders
them as few-shot prompt sections, injected after soul.md + terminology.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from autoservice.sim_customer import SimDialog

logger = logging.getLogger(__name__)


@dataclass
class FewshotExample:
    scenario: str
    customer_turns: list[str]
    agent_response: str
    language: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FewshotExample":
        return cls(
            scenario=data["scenario"],
            customer_turns=list(data["customer_turns"]),
            agent_response=data["agent_response"],
            language=data.get("language", "zh"),
        )


class FewshotLoader:
    """Load and render few-shot examples for customer agent prompts.

    Follows the same pattern as TermLoader: load from YAML, render as
    prompt section, no caching (hot-reload on every call).
    """

    def __init__(self, override_path: str | Path | None = None) -> None:
        self._path = Path(override_path) if override_path else None

    def load_examples(self, language: str | None = None) -> list[FewshotExample]:
        """Load few-shot examples, optionally filtered by language.

        Returns empty list if file doesn't exist, is empty, or is malformed.
        """
        if self._path is None or not self._path.is_file():
            return []

        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.warning("Failed to parse fewshot YAML: %s", self._path)
            return []

        if not data or "examples" not in data:
            return []

        examples: list[FewshotExample] = []
        for item in data["examples"]:
            try:
                ex = FewshotExample(
                    scenario=item["scenario"],
                    customer_turns=list(item["customer_turns"]),
                    agent_response=item["agent_response"],
                    language=item.get("language", "zh"),
                )
                if language is None or ex.language == language:
                    examples.append(ex)
            except (KeyError, TypeError):
                continue

        return examples

    def render_prompt_section(
        self, language: str, max_tokens: int = 3000
    ) -> str:
        """Render few-shot examples as a prompt section.

        Uses heuristic 1 token ~ 4 chars for truncation.
        Returns empty string if no examples available.
        """
        examples = self.load_examples(language=language)
        if not examples:
            return ""

        max_chars = max_tokens * 4
        lines: list[str] = ["## 参考对话示例", ""]
        used = sum(len(line) + 1 for line in lines)

        for i, ex in enumerate(examples, 1):
            block_lines = [
                f"### 示例 {i}: {ex.scenario}",
                "",
            ]
            for turn in ex.customer_turns:
                block_lines.append(f"> 客户: {turn}")
            block_lines.append("")
            block_lines.append(f"**推荐回复**: {ex.agent_response}")
            block_lines.append("")

            block_len = sum(len(line) + 1 for line in block_lines)
            if used + block_len > max_chars:
                break

            lines.extend(block_lines)
            used += block_len

        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

    def save_from_sim_dialogs(
        self, dialogs: "list[SimDialog]",
    ) -> int:
        """Save edited SimDialogs as few-shot examples.

        Only dialogs with review_status == "edited" are saved.
        Returns the number of examples saved.
        """
        if self._path is None:
            raise ValueError("override_path is required to save")

        examples: list[dict] = []
        for dialog in dialogs:
            if dialog.review_status != "edited":
                continue

            customer_turns: list[str] = []
            agent_response = ""
            for turn in dialog.turns:
                if turn.role == "customer":
                    customer_turns.append(turn.content)
                elif turn.role == "agent":
                    agent_response = turn.content  # last agent response wins

            if customer_turns and agent_response:
                examples.append({
                    "scenario": dialog.scenario.name_zh,
                    "customer_turns": customer_turns,
                    "agent_response": agent_response,
                    "language": dialog.language,
                })

        output = {
            "version": "1.0",
            "examples": examples,
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(
                output, f, allow_unicode=True, default_flow_style=False,
                sort_keys=False,
            )

        return len(examples)
