"""Tests for autoservice/fewshot_loader.py — T3A.3 Few-shot injection mechanism.

Test plan: .artifacts/test-plans/plan-T3A.3-fewshot-injection.md
13 test cases covering YAML loading, language filtering, prompt rendering,
save/load round-trip, and hot-reload.
"""

import yaml
import pytest

from autoservice.fewshot_loader import FewshotExample, FewshotLoader
from autoservice.sim_customer import Persona, Scenario, SimDialog, SimTurn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_yaml(path, data):
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


@pytest.fixture
def fewshot_yaml(tmp_path):
    """Create a fewshot_override.yaml with 3 examples (2 zh + 1 en)."""
    path = tmp_path / "fewshot_override.yaml"
    data = {
        "version": "1.0",
        "examples": [
            {
                "scenario": "退款申请",
                "customer_turns": ["我要退款", "已经等了三天了"],
                "agent_response": "非常抱歉让您久等了，退款将在1-2个工作日内到账。",
                "language": "zh",
            },
            {
                "scenario": "产品咨询",
                "customer_turns": ["这个产品支持什么平台？"],
                "agent_response": "我们支持iOS和Android双平台。",
                "language": "zh",
            },
            {
                "scenario": "Refund inquiry",
                "customer_turns": ["I want a refund please"],
                "agent_response": "I'll process your refund right away.",
                "language": "en",
            },
        ],
    }
    _write_yaml(path, data)
    return path


@pytest.fixture
def many_examples_yaml(tmp_path):
    """Create a YAML with 20 examples for truncation testing."""
    path = tmp_path / "many.yaml"
    examples = []
    for i in range(20):
        examples.append({
            "scenario": f"场景{i}",
            "customer_turns": [f"这是一个很长的客户问题描述，用来测试截断功能，编号{i}"],
            "agent_response": f"这是一个同样很长的AI回复内容，包含详细的解决方案说明，编号{i}",
            "language": "zh",
        })
    _write_yaml(path, {"version": "1.0", "examples": examples})
    return path


def _make_dialog(review_status, dialog_id="d1"):
    return SimDialog(
        id=dialog_id,
        scenario=Scenario(
            id="test", name_zh="测试场景", intent="complaint",
            keywords=["测试"], trap_question="陷阱题",
        ),
        persona=Persona(
            id="angry", name_zh="愤怒客户",
            traits=["激动"], communication_style="aggressive",
        ),
        turns=[
            SimTurn(role="customer", content="我要投诉！"),
            SimTurn(role="agent", content="非常抱歉。"),
            SimTurn(role="customer", content="赶快处理！"),
            SimTurn(role="agent", content="已为您加急处理。"),
        ],
        language="zh",
        review_status=review_status,
    )


# ===================================================================
# TC-001: YAML 加载正常文件
# ===================================================================


class TestLoadNormal:
    def test_loads_three_examples(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        examples = loader.load_examples()
        assert len(examples) == 3

    def test_example_fields(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        ex = loader.load_examples()[0]
        assert isinstance(ex, FewshotExample)
        assert ex.scenario == "退款申请"
        assert ex.customer_turns == ["我要退款", "已经等了三天了"]
        assert "退款" in ex.agent_response
        assert ex.language == "zh"


# ===================================================================
# TC-002: YAML 加载 — 文件不存在
# ===================================================================


class TestLoadMissing:
    def test_missing_file_returns_empty(self, tmp_path):
        loader = FewshotLoader(tmp_path / "nonexistent.yaml")
        assert loader.load_examples() == []

    def test_none_path_returns_empty(self):
        loader = FewshotLoader(None)
        assert loader.load_examples() == []


# ===================================================================
# TC-003: YAML 加载 — 空文件
# ===================================================================


class TestLoadEmpty:
    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        loader = FewshotLoader(path)
        assert loader.load_examples() == []


# ===================================================================
# TC-004: YAML 加载 — 格式损坏
# ===================================================================


class TestLoadCorrupt:
    def test_invalid_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("{{{not valid yaml:::", encoding="utf-8")
        loader = FewshotLoader(path)
        assert loader.load_examples() == []

    def test_yaml_without_examples_key(self, tmp_path):
        path = tmp_path / "nokey.yaml"
        _write_yaml(path, {"version": "1.0", "other": "data"})
        loader = FewshotLoader(path)
        assert loader.load_examples() == []


# ===================================================================
# TC-005: 语言过滤
# ===================================================================


class TestLanguageFilter:
    def test_filter_zh(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        zh = loader.load_examples(language="zh")
        assert len(zh) == 2
        assert all(ex.language == "zh" for ex in zh)

    def test_filter_en(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        en = loader.load_examples(language="en")
        assert len(en) == 1
        assert en[0].language == "en"

    def test_filter_nonexistent_language(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        assert loader.load_examples(language="fr") == []


# ===================================================================
# TC-006: 语言过滤 — None 返回全部
# ===================================================================


class TestLanguageFilterNone:
    def test_none_returns_all(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        all_ex = loader.load_examples(language=None)
        assert len(all_ex) == 3


# ===================================================================
# TC-007: prompt 渲染 — 正常
# ===================================================================


class TestRenderNormal:
    def test_renders_markdown(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        section = loader.render_prompt_section("zh")
        assert "## 参考对话示例" in section
        assert "退款申请" in section
        assert "退款" in section
        assert "产品咨询" in section

    def test_renders_customer_and_agent(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        section = loader.render_prompt_section("zh")
        assert "> 客户:" in section
        assert "**推荐回复**:" in section


# ===================================================================
# TC-008: prompt 渲染 — 无 example
# ===================================================================


class TestRenderEmpty:
    def test_no_file_returns_empty_string(self, tmp_path):
        loader = FewshotLoader(tmp_path / "missing.yaml")
        assert loader.render_prompt_section("zh") == ""

    def test_no_matching_language_returns_empty(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        assert loader.render_prompt_section("fr") == ""


# ===================================================================
# TC-009: prompt 渲染 — 截断过长
# ===================================================================


class TestRenderTruncation:
    def test_truncates_within_limit(self, many_examples_yaml):
        loader = FewshotLoader(many_examples_yaml)
        section = loader.render_prompt_section("zh", max_tokens=200)
        # 200 tokens * 4 chars = 800 chars max
        assert len(section) <= 800

    def test_truncation_preserves_complete_examples(self, many_examples_yaml):
        loader = FewshotLoader(many_examples_yaml)
        section = loader.render_prompt_section("zh", max_tokens=200)
        # Should not cut in the middle of an example
        assert section.count("### 示例") < 20  # definitely truncated
        if "### 示例" in section:
            # Each included example should be complete (has both customer and response)
            assert "> 客户:" in section
            assert "**推荐回复**:" in section


# ===================================================================
# TC-010: save_from_sim_dialogs — 仅保存 edited
# ===================================================================


class TestSaveEdited:
    def test_saves_only_edited(self, tmp_path):
        path = tmp_path / "output.yaml"
        loader = FewshotLoader(path)

        dialogs = [
            _make_dialog("edited", "d1"),
            _make_dialog("approved", "d2"),
            _make_dialog("edited", "d3"),
            _make_dialog("approved", "d4"),
            _make_dialog("flagged", "d5"),
        ]

        count = loader.save_from_sim_dialogs(dialogs)
        assert count == 2

    def test_saved_yaml_readable(self, tmp_path):
        path = tmp_path / "output.yaml"
        loader = FewshotLoader(path)
        dialogs = [_make_dialog("edited")]
        loader.save_from_sim_dialogs(dialogs)

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["version"] == "1.0"
        assert len(data["examples"]) == 1


# ===================================================================
# TC-011: save_from_sim_dialogs — YAML 可再加载
# ===================================================================


class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "roundtrip.yaml"
        loader = FewshotLoader(path)

        dialogs = [_make_dialog("edited", "d1"), _make_dialog("edited", "d2")]
        loader.save_from_sim_dialogs(dialogs)

        loaded = loader.load_examples()
        assert len(loaded) == 2
        assert loaded[0].scenario == "测试场景"
        assert loaded[0].language == "zh"
        assert "投诉" in loaded[0].customer_turns[0]
        assert loaded[0].agent_response  # non-empty

    def test_content_matches(self, tmp_path):
        path = tmp_path / "match.yaml"
        loader = FewshotLoader(path)

        dialog = _make_dialog("edited")
        loader.save_from_sim_dialogs([dialog])

        loaded = loader.load_examples()
        assert len(loaded) == 1
        # Last agent response from turns: "已为您加急处理。"
        assert loaded[0].agent_response == "已为您加急处理。"


# ===================================================================
# TC-012: 热加载 — 文件更新后立即生效
# ===================================================================


class TestHotReload:
    def test_reload_after_append(self, fewshot_yaml):
        loader = FewshotLoader(fewshot_yaml)
        initial = loader.load_examples()
        assert len(initial) == 3

        # Append a new example
        with open(fewshot_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["examples"].append({
            "scenario": "新增场景",
            "customer_turns": ["新问题"],
            "agent_response": "新回复",
            "language": "zh",
        })
        _write_yaml(fewshot_yaml, data)

        reloaded = loader.load_examples()
        assert len(reloaded) == 4


# ===================================================================
# TC-013: FewshotExample round-trip
# ===================================================================


class TestExampleRoundTrip:
    def test_to_from_dict(self):
        ex = FewshotExample(
            scenario="退款",
            customer_turns=["我要退款", "多久到账"],
            agent_response="3-5个工作日",
            language="zh",
        )
        d = ex.to_dict()
        restored = FewshotExample.from_dict(d)
        assert restored.scenario == ex.scenario
        assert restored.customer_turns == ex.customer_turns
        assert restored.agent_response == ex.agent_response
        assert restored.language == ex.language
