"""Few-shot injection mechanism for customer service agents.

T3A.3 产出 | 2026-04-16
关联: T3A.2 sim_customer.py, agents/customer/soul.md

Loads few-shot conversation examples from YAML files or SimDialog objects
(produced by sim_customer.py) and renders them as a prompt prefix that can
be prepended to the agent system prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from autoservice.sim_customer import SimDialog, SimTurn

logger = logging.getLogger(__name__)

_EXAMPLES_DIR = Path(__file__).parent / "few_shot_examples"


class FewShotInjector:
    """Loads, renders, and injects few-shot examples into system prompts.

    Examples can come from two sources:
    1. YAML files in ``autoservice/few_shot_examples/`` (static, curated)
    2. ``SimDialog`` objects from ``sim_customer.py`` (dynamic, generated)

    Parameters
    ----------
    examples_dir : str | Path | None
        Directory containing ``<domain>.yaml`` example files.
        Defaults to ``autoservice/few_shot_examples/``.
    """

    def __init__(self, examples_dir: str | Path | None = None) -> None:
        self.examples_dir = Path(examples_dir) if examples_dir else _EXAMPLES_DIR

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_examples(
        self,
        domain: str,
        max_examples: int = 3,
        sim_dialogs: list[SimDialog] | None = None,
    ) -> list[dict]:
        """Load few-shot examples for a given domain.

        Tries YAML files first, then falls back to ``sim_dialogs`` if
        provided. Returns up to *max_examples* conversations.

        Parameters
        ----------
        domain : str
            Domain / scenario key (e.g. ``"product_inquiry"``, ``"complaint"``).
        max_examples : int
            Maximum number of example conversations to return.
        sim_dialogs : list[SimDialog] | None
            Optional list of simulated dialogs (from ``sim_customer.py``)
            used as a fallback when no YAML file matches *domain*.

        Returns
        -------
        list[dict]
            Each dict has ``"turns"`` — a list of ``{"role": ..., "content": ...}``.
        """
        if max_examples < 1:
            return []

        examples = self._load_from_yaml(domain)

        # Fallback: convert SimDialogs matching the domain
        if not examples and sim_dialogs:
            examples = self._load_from_sim_dialogs(domain, sim_dialogs)

        return examples[:max_examples]

    def _load_from_yaml(self, domain: str) -> list[dict]:
        """Load examples from ``<examples_dir>/<domain>.yaml``."""
        yaml_path = self.examples_dir / f"{domain}.yaml"
        if not yaml_path.is_file():
            logger.debug("No YAML examples found for domain %r at %s", domain, yaml_path)
            return []

        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.warning("Failed to load YAML examples from %s", yaml_path, exc_info=True)
            return []

        if not isinstance(data, dict):
            return []

        raw_examples = data.get("examples", [])
        result: list[dict] = []
        for ex in raw_examples:
            if not isinstance(ex, dict) or "turns" not in ex:
                continue
            turns = []
            for t in ex["turns"]:
                if isinstance(t, dict) and "role" in t and "content" in t:
                    turns.append({"role": t["role"], "content": t["content"]})
            if turns:
                result.append({"turns": turns})
        return result

    def _load_from_sim_dialogs(
        self, domain: str, sim_dialogs: list[SimDialog]
    ) -> list[dict]:
        """Convert SimDialog objects matching *domain* into example dicts."""
        results: list[dict] = []
        for dialog in sim_dialogs:
            # Match by scenario intent or scenario id
            if dialog.scenario.intent == domain or dialog.scenario.id == domain:
                turns = [
                    {"role": t.role, "content": t.content}
                    for t in dialog.turns
                ]
                if turns:
                    results.append({"turns": turns})
        return results

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def render_prefix(examples: list[dict]) -> str:
        """Format examples as a prompt prefix string.

        Each example is rendered as a numbered conversation block with
        ``Customer:`` / ``Agent:`` turn labels.

        Parameters
        ----------
        examples : list[dict]
            List of example dicts, each with a ``"turns"`` key.

        Returns
        -------
        str
            Formatted prompt prefix (empty string if no examples).
        """
        if not examples:
            return ""

        blocks: list[str] = []
        role_labels = {"customer": "Customer", "agent": "Agent"}
        counter = 0

        for ex in examples:
            turns = ex.get("turns", [])
            if not turns:
                continue
            counter += 1
            lines = [f"### Example {counter}"]
            for turn in turns:
                role = turn.get("role", "customer")
                label = role_labels.get(role, role.capitalize())
                lines.append(f"{label}: {turn['content']}")
            blocks.append("\n".join(lines))

        if not blocks:
            return ""

        header = "## Few-shot examples\n\nThe following are example conversations for reference:\n"
        return header + "\n\n".join(blocks) + "\n"

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def inject(
        self,
        system_prompt: str,
        domain: str,
        max_examples: int = 3,
        sim_dialogs: list[SimDialog] | None = None,
    ) -> str:
        """Load examples, render, and prepend to system prompt.

        Parameters
        ----------
        system_prompt : str
            Original system prompt text.
        domain : str
            Domain / scenario key.
        max_examples : int
            Maximum number of examples.
        sim_dialogs : list[SimDialog] | None
            Optional simulated dialogs for fallback.

        Returns
        -------
        str
            System prompt with few-shot prefix prepended (if examples exist).
        """
        examples = self.load_examples(domain, max_examples, sim_dialogs)
        prefix = self.render_prefix(examples)
        if not prefix:
            return system_prompt
        return prefix + "\n" + system_prompt
