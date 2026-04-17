"""Tests for autoservice.few_shot — FewShotInjector.

T3A.3 | 2026-04-16
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from autoservice.few_shot import FewShotInjector
from autoservice.sim_customer import Persona, Scenario, SimDialog, SimTurn

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_YAML = {
    "domain": "test_domain",
    "language": "zh",
    "examples": [
        {
            "turns": [
                {"role": "customer", "content": "Hello, I have a question."},
                {"role": "agent", "content": "Sure, how can I help?"},
            ]
        },
        {
            "turns": [
                {"role": "customer", "content": "What is your return policy?"},
                {"role": "agent", "content": "You can return within 30 days."},
            ]
        },
        {
            "turns": [
                {"role": "customer", "content": "How much does it cost?"},
                {"role": "agent", "content": "The price is $99."},
            ]
        },
    ],
}


@pytest.fixture()
def examples_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample YAML example files."""
    yaml_path = tmp_path / "test_domain.yaml"
    yaml_path.write_text(yaml.dump(SAMPLE_YAML, allow_unicode=True), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def injector(examples_dir: Path) -> FewShotInjector:
    return FewShotInjector(examples_dir=examples_dir)


def _make_sim_dialog(intent: str = "product_inquiry") -> SimDialog:
    """Helper to build a SimDialog for testing."""
    return SimDialog(
        id="test-001",
        scenario=Scenario(
            id="sc-test",
            name_zh="测试场景",
            intent=intent,
            keywords=["测试"],
            trap_question="这个问题KB回答不了",
        ),
        persona=Persona(
            id="p-test",
            name_zh="测试角色",
            traits=["友好"],
            communication_style="formal",
        ),
        turns=[
            SimTurn(role="customer", content="你好，我想咨询产品"),
            SimTurn(role="agent", content="您好，请问有什么可以帮您？"),
        ],
        language="zh",
    )


# ---------------------------------------------------------------------------
# Tests: load_examples
# ---------------------------------------------------------------------------


class TestLoadExamples:
    def test_loads_from_yaml(self, injector: FewShotInjector) -> None:
        examples = injector.load_examples("test_domain")
        assert len(examples) == 3
        assert examples[0]["turns"][0]["role"] == "customer"
        assert examples[0]["turns"][0]["content"] == "Hello, I have a question."

    def test_max_examples_limits_results(self, injector: FewShotInjector) -> None:
        examples = injector.load_examples("test_domain", max_examples=2)
        assert len(examples) == 2

    def test_max_examples_zero_returns_empty(self, injector: FewShotInjector) -> None:
        examples = injector.load_examples("test_domain", max_examples=0)
        assert examples == []

    def test_missing_domain_returns_empty(self, injector: FewShotInjector) -> None:
        examples = injector.load_examples("nonexistent_domain")
        assert examples == []

    def test_fallback_to_sim_dialogs(self, injector: FewShotInjector) -> None:
        dialog = _make_sim_dialog("my_custom_intent")
        examples = injector.load_examples(
            "my_custom_intent", sim_dialogs=[dialog]
        )
        assert len(examples) == 1
        assert examples[0]["turns"][0]["content"] == "你好，我想咨询产品"

    def test_yaml_takes_priority_over_sim_dialogs(
        self, injector: FewShotInjector
    ) -> None:
        dialog = _make_sim_dialog("test_domain")
        examples = injector.load_examples("test_domain", sim_dialogs=[dialog])
        # Should load from YAML, not sim_dialogs
        assert examples[0]["turns"][0]["content"] == "Hello, I have a question."

    def test_sim_dialog_matches_by_scenario_id(
        self, injector: FewShotInjector
    ) -> None:
        dialog = _make_sim_dialog("other_intent")
        examples = injector.load_examples("sc-test", sim_dialogs=[dialog])
        assert len(examples) == 1

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("not: valid: yaml: [[[", encoding="utf-8")
        inj = FewShotInjector(examples_dir=tmp_path)
        examples = inj.load_examples("bad")
        assert examples == []

    def test_yaml_missing_turns_skipped(self, tmp_path: Path) -> None:
        data = {"examples": [{"no_turns_key": True}, {"turns": [{"role": "customer", "content": "Hi"}]}]}
        (tmp_path / "partial.yaml").write_text(yaml.dump(data), encoding="utf-8")
        inj = FewShotInjector(examples_dir=tmp_path)
        examples = inj.load_examples("partial")
        assert len(examples) == 1


# ---------------------------------------------------------------------------
# Tests: render_prefix
# ---------------------------------------------------------------------------


class TestRenderPrefix:
    def test_empty_examples_returns_empty_string(self) -> None:
        assert FewShotInjector.render_prefix([]) == ""

    def test_single_example_format(self) -> None:
        examples = [
            {
                "turns": [
                    {"role": "customer", "content": "Hi"},
                    {"role": "agent", "content": "Hello!"},
                ]
            }
        ]
        result = FewShotInjector.render_prefix(examples)
        assert "## Few-shot examples" in result
        assert "### Example 1" in result
        assert "Customer: Hi" in result
        assert "Agent: Hello!" in result

    def test_multiple_examples_numbered(self) -> None:
        examples = [
            {"turns": [{"role": "customer", "content": "Q1"}]},
            {"turns": [{"role": "customer", "content": "Q2"}]},
        ]
        result = FewShotInjector.render_prefix(examples)
        assert "### Example 1" in result
        assert "### Example 2" in result

    def test_empty_turns_skipped(self) -> None:
        examples = [{"turns": []}, {"turns": [{"role": "customer", "content": "Hi"}]}]
        result = FewShotInjector.render_prefix(examples)
        assert "### Example 1" in result
        assert "### Example 2" not in result


# ---------------------------------------------------------------------------
# Tests: inject
# ---------------------------------------------------------------------------


class TestInject:
    def test_prepends_prefix_to_system_prompt(self, injector: FewShotInjector) -> None:
        original = "You are a helpful assistant."
        result = injector.inject(original, "test_domain")
        assert result.startswith("## Few-shot examples")
        assert result.endswith(original)

    def test_no_examples_returns_original(self, injector: FewShotInjector) -> None:
        original = "You are a helpful assistant."
        result = injector.inject(original, "nonexistent")
        assert result == original

    def test_inject_with_sim_dialogs_fallback(
        self, injector: FewShotInjector
    ) -> None:
        dialog = _make_sim_dialog("custom_intent")
        original = "System prompt."
        result = injector.inject(
            original, "custom_intent", sim_dialogs=[dialog]
        )
        assert "## Few-shot examples" in result
        assert result.endswith("System prompt.")

    def test_inject_max_examples(self, injector: FewShotInjector) -> None:
        original = "Base prompt."
        result = injector.inject(original, "test_domain", max_examples=1)
        assert "### Example 1" in result
        assert "### Example 2" not in result


# ---------------------------------------------------------------------------
# Tests: default examples directory
# ---------------------------------------------------------------------------


class TestDefaultExamples:
    """Verify the bundled example YAML files load correctly."""

    def test_product_inquiry_examples_loadable(self) -> None:
        inj = FewShotInjector()  # uses default examples_dir
        examples = inj.load_examples("product_inquiry")
        assert len(examples) >= 1
        assert examples[0]["turns"][0]["role"] == "customer"

    def test_complaint_examples_loadable(self) -> None:
        inj = FewShotInjector()
        examples = inj.load_examples("complaint")
        assert len(examples) >= 1

    def test_general_question_examples_loadable(self) -> None:
        inj = FewShotInjector()
        examples = inj.load_examples("general_question")
        assert len(examples) >= 1
