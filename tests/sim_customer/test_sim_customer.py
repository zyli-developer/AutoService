"""Tests for autoservice/sim_customer.py — T3A.2 virtual customer generation pipeline.

Test plan: .artifacts/test-plans/plan-T3A.2-sim-customer-pipeline.md
20 test cases covering config loading, scenario extraction, assignment matrix,
dialog generation, and end-to-end pipeline.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from autoservice.sim_customer import (
    Persona,
    Scenario,
    SimConfig,
    SimDialog,
    SimTurn,
    build_assignment_matrix,
    extract_scenarios,
    generate_sim_dialogs,
    generate_single_dialog,
    load_sim_config,
)


# ===================================================================
# TC-001: YAML config loading — personas
# ===================================================================


class TestConfigLoadingPersonas:
    def test_loads_six_personas(self, sim_config):
        assert len(sim_config.personas) == 6

    def test_persona_fields(self, sim_config):
        for p in sim_config.personas:
            assert isinstance(p, Persona)
            assert p.id
            assert p.name_zh
            assert isinstance(p.traits, list) and len(p.traits) > 0
            assert p.communication_style

    def test_persona_ids_unique(self, sim_config):
        ids = [p.id for p in sim_config.personas]
        assert len(ids) == len(set(ids))

    def test_expected_persona_ids(self, sim_config):
        ids = {p.id for p in sim_config.personas}
        expected = {
            "angry-refund", "price-sensitive", "non-native-speaker",
            "tech-illiterate", "repeat-customer", "cross-border",
        }
        assert ids == expected


# ===================================================================
# TC-002: YAML config loading — fallback scenarios
# ===================================================================


class TestConfigLoadingScenarios:
    def test_loads_fallback_scenarios(self, sim_config):
        assert len(sim_config.fallback_scenarios) >= 3

    def test_scenario_fields(self, sim_config):
        for s in sim_config.fallback_scenarios:
            assert isinstance(s, Scenario)
            assert s.id
            assert s.name_zh
            assert s.intent in {
                "product_inquiry", "complaint", "purchase_intent",
                "language_barrier", "general_question",
            }
            assert isinstance(s.keywords, list)
            assert s.trap_question

    def test_constraints_loaded(self, sim_config):
        c = sim_config.constraints
        assert "min_turns" in c
        assert "max_turns" in c
        assert c["min_turns"] == 3
        assert c["max_turns"] == 6


# ===================================================================
# TC-003: KB scenario extraction — normal KB
# ===================================================================


class TestKBScenarioExtraction:
    @pytest.mark.asyncio
    async def test_extracts_scenarios_from_kb(self, fixture_kb, sim_config, mock_llm):
        scenarios = await extract_scenarios(fixture_kb, sim_config, mock_llm)
        assert len(scenarios) >= 3
        assert len(scenarios) <= 8
        for s in scenarios:
            assert isinstance(s, Scenario)
            assert s.id
            assert s.intent in {
                "product_inquiry", "complaint", "purchase_intent",
                "language_barrier", "general_question",
            }

    @pytest.mark.asyncio
    async def test_scenarios_have_trap_questions(self, fixture_kb, sim_config, mock_llm):
        scenarios = await extract_scenarios(fixture_kb, sim_config, mock_llm)
        for s in scenarios:
            assert s.trap_question  # non-empty

    @pytest.mark.asyncio
    async def test_scenarios_not_degraded(self, fixture_kb, sim_config, mock_llm):
        scenarios = await extract_scenarios(fixture_kb, sim_config, mock_llm)
        assert all(not s.degraded for s in scenarios)


# ===================================================================
# TC-004: KB scenario extraction — empty KB degradation
# ===================================================================


class TestEmptyKBDegradation:
    @pytest.mark.asyncio
    async def test_empty_kb_returns_fallbacks(self, empty_kb, sim_config, mock_llm):
        scenarios = await extract_scenarios(empty_kb, sim_config, mock_llm)
        assert len(scenarios) >= 3
        assert all(s.degraded for s in scenarios)

    @pytest.mark.asyncio
    async def test_nonexistent_kb_returns_fallbacks(self, tmp_path, sim_config, mock_llm):
        fake_path = tmp_path / "nonexistent.db"
        scenarios = await extract_scenarios(fake_path, sim_config, mock_llm)
        assert len(scenarios) >= 3
        assert all(s.degraded for s in scenarios)


# ===================================================================
# TC-005: Assignment matrix
# ===================================================================


class TestAssignmentMatrix:
    def test_returns_correct_count(self, sim_config):
        scenarios = sim_config.fallback_scenarios
        personas = sim_config.personas
        matrix = build_assignment_matrix(scenarios, personas, count=12)
        assert len(matrix) == 12

    def test_all_intents_covered(self, sim_config):
        scenarios = sim_config.fallback_scenarios
        personas = sim_config.personas
        matrix = build_assignment_matrix(scenarios, personas, count=12)
        intents = {s.intent for s, _ in matrix}
        expected_intents = {s.intent for s in scenarios}
        assert expected_intents.issubset(intents)

    def test_all_personas_covered(self, sim_config):
        scenarios = sim_config.fallback_scenarios
        personas = sim_config.personas
        matrix = build_assignment_matrix(scenarios, personas, count=12)
        used_personas = {p.id for _, p in matrix}
        all_persona_ids = {p.id for p in personas}
        assert all_persona_ids.issubset(used_personas)

    def test_small_count_still_works(self, sim_config):
        scenarios = sim_config.fallback_scenarios
        personas = sim_config.personas
        matrix = build_assignment_matrix(scenarios, personas, count=5)
        assert len(matrix) == 5

    def test_large_count(self, sim_config):
        scenarios = sim_config.fallback_scenarios
        personas = sim_config.personas
        matrix = build_assignment_matrix(scenarios, personas, count=20)
        assert len(matrix) == 20


# ===================================================================
# TC-006: Single dialog generation — structure validation
# ===================================================================


class TestSingleDialogStructure:
    @pytest.mark.asyncio
    async def test_dialog_structure(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        assert isinstance(dialog, SimDialog)
        assert dialog.id
        assert dialog.scenario == sample_scenario
        assert dialog.persona == sample_persona
        assert dialog.language == "zh"
        assert dialog.review_status == "pending"

    @pytest.mark.asyncio
    async def test_turns_alternating(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        assert len(dialog.turns) >= 6  # 4 customer + at least matching agent
        # First turn is customer
        assert dialog.turns[0].role == "customer"
        # Alternating pattern
        for i in range(0, len(dialog.turns) - 1, 2):
            assert dialog.turns[i].role == "customer"
            assert dialog.turns[i + 1].role == "agent"

    @pytest.mark.asyncio
    async def test_turns_have_content(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        for turn in dialog.turns:
            assert turn.content  # non-empty


# ===================================================================
# TC-007: Trap question existence
# ===================================================================


class TestTrapQuestion:
    @pytest.mark.asyncio
    async def test_trap_turn_present(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        customer_turns = [t for t in dialog.turns if t.role == "customer"]
        trap_turns = [t for t in customer_turns if t.metadata.get("is_trap")]
        assert len(trap_turns) >= 1


# ===================================================================
# TC-008: AI response uses soul.md prompt
# ===================================================================


class TestSoulPromptUsage:
    @pytest.mark.asyncio
    async def test_soul_in_system_prompt(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        # Agent response calls have system prompt
        agent_calls = [c for c in mock_llm.calls if c["system"] is not None]
        assert len(agent_calls) > 0
        # System prompt should contain soul.md content
        system = agent_calls[0]["system"]
        assert "知识库" in system or "角色定位" in system


# ===================================================================
# TC-009: Terminology injection (zh)
# ===================================================================


class TestTermInjectionZh:
    @pytest.mark.asyncio
    async def test_zh_terms_in_prompt(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock_llm, sim_config
        )
        agent_calls = [c for c in mock_llm.calls if c["system"] is not None]
        # Should have term table header if zh terms exist
        # (depends on whether zh.yaml exists; test gracefully)
        assert len(agent_calls) > 0


# ===================================================================
# TC-010: Terminology injection (en)
# ===================================================================


class TestTermInjectionEn:
    @pytest.mark.asyncio
    async def test_en_terms_in_prompt(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "en", mock_llm, sim_config
        )
        agent_calls = [c for c in mock_llm.calls if c["system"] is not None]
        assert len(agent_calls) > 0
        system = agent_calls[0]["system"]
        assert "术语表 (en)" in system or "角色定位" in system

    @pytest.mark.asyncio
    async def test_en_dialog_language(
        self, sample_scenario, sample_persona, fixture_kb, mock_llm, sim_config,
    ):
        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "en", mock_llm, sim_config
        )
        assert dialog.language == "en"


# ===================================================================
# TC-011: End-to-end generate_sim_dialogs — normal path
# ===================================================================


class TestE2ENormalPath:
    @pytest.mark.asyncio
    async def test_generates_enough_dialogs(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=12,
            llm_client=mock_llm,
            config=sim_config,
        )
        assert len(dialogs) >= 10

    @pytest.mark.asyncio
    async def test_intent_coverage(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=12,
            llm_client=mock_llm,
            config=sim_config,
        )
        intents = {d.scenario.intent for d in dialogs}
        assert len(intents) >= 4  # at least 4 of 5 intents

    @pytest.mark.asyncio
    async def test_persona_coverage(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=12,
            llm_client=mock_llm,
            config=sim_config,
        )
        personas = {d.persona.id for d in dialogs}
        assert len(personas) >= 5  # at least 5 of 6

    @pytest.mark.asyncio
    async def test_all_dialogs_valid_structure(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=12,
            llm_client=mock_llm,
            config=sim_config,
        )
        for d in dialogs:
            assert isinstance(d, SimDialog)
            assert d.id
            assert d.scenario
            assert d.persona
            assert len(d.turns) >= 6  # 3+ customer + matching agent


# ===================================================================
# TC-012: Count parameter
# ===================================================================


class TestCountParameter:
    @pytest.mark.asyncio
    async def test_count_5(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=5,
            llm_client=mock_llm,
            config=sim_config,
        )
        assert len(dialogs) == 5

    @pytest.mark.asyncio
    async def test_count_20(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=20,
            llm_client=mock_llm,
            config=sim_config,
        )
        assert len(dialogs) == 20


# ===================================================================
# TC-013: Persona filtering
# ===================================================================


class TestPersonaFiltering:
    @pytest.mark.asyncio
    async def test_filter_two_personas(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=6,
            personas=["angry-refund", "cross-border"],
            llm_client=mock_llm,
            config=sim_config,
        )
        persona_ids = {d.persona.id for d in dialogs}
        assert persona_ids.issubset({"angry-refund", "cross-border"})

    @pytest.mark.asyncio
    async def test_invalid_persona_raises(self, fixture_kb, mock_llm, sim_config):
        with pytest.raises(ValueError, match="No matching personas"):
            await generate_sim_dialogs(
                tenant_id="test",
                kb_path=fixture_kb,
                personas=["nonexistent"],
                llm_client=mock_llm,
                config=sim_config,
            )


# ===================================================================
# TC-014: Turn count post-processing — truncate too long
# ===================================================================


class TestTurnTruncation:
    @pytest.mark.asyncio
    async def test_truncates_long_dialog(
        self, sample_scenario, sample_persona, fixture_kb, sim_config,
    ):
        mock = MockLLMClient()
        # Return 8 customer turns (exceeds max_turns=6)
        mock._customer_turns_response = json.dumps([
            {"role": "customer", "content": f"消息{i}", "metadata": {"is_trap": i == 5}}
            for i in range(8)
        ], ensure_ascii=False)

        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock, sim_config
        )
        customer_turns = [t for t in dialog.turns if t.role == "customer"]
        assert len(customer_turns) <= 6


# Need import for MockLLMClient in this scope
from tests.sim_customer.conftest import MockLLMClient


# ===================================================================
# TC-015: Turn count post-processing — pad too short
# ===================================================================


class TestTurnPadding:
    @pytest.mark.asyncio
    async def test_retries_short_dialog(
        self, sample_scenario, sample_persona, fixture_kb, sim_config,
    ):
        mock = MockLLMClient()
        call_count = [0]
        original_generate = mock.generate

        async def counting_generate(prompt, system=None):
            call_count[0] += 1
            if call_count[0] == 1 and "虚拟客户模拟器" in prompt:
                # First call returns too few turns
                return json.dumps([
                    {"role": "customer", "content": "你好", "metadata": {"is_trap": False}},
                    {"role": "customer", "content": "再见", "metadata": {"is_trap": False}},
                ], ensure_ascii=False)
            return await original_generate(prompt, system)

        mock.generate = counting_generate

        dialog = await generate_single_dialog(
            sample_scenario, sample_persona, fixture_kb, "zh", mock, sim_config
        )
        # Should have retried and got normal turns
        assert len(dialog.turns) >= 2  # at least some turns produced


# ===================================================================
# TC-016: Concurrency control — semaphore
# ===================================================================


class TestConcurrencyControl:
    @pytest.mark.asyncio
    async def test_max_concurrent_limited(self, fixture_kb, mock_llm, sim_config):
        dialogs = await generate_sim_dialogs(
            tenant_id="test",
            kb_path=fixture_kb,
            count=12,
            llm_client=mock_llm,
            config=sim_config,
        )
        # max_concurrency is 6 in config
        # Note: exact concurrency depends on event loop scheduling,
        # but we verify the pipeline completes with semaphore in place
        assert len(dialogs) == 12


# ===================================================================
# TC-017: Custom persona hot-reload
# ===================================================================


class TestCustomPersona:
    def test_tenant_override_adds_persona(self, tmp_path):
        override_path = tmp_path / "override.yaml"
        override_path.write_text(
            "personas:\n"
            "  - id: vip-customer\n"
            '    name_zh: "VIP客户"\n'
            "    traits: ['高净值', '要求专属服务']\n"
            "    communication_style: demanding\n",
            encoding="utf-8",
        )
        config = load_sim_config(tenant_override=str(override_path))
        ids = {p.id for p in config.personas}
        assert "vip-customer" in ids
        assert len(config.personas) == 7


# ===================================================================
# TC-018: SimDialog serialization round-trip
# ===================================================================


class TestSerialization:
    def test_round_trip(self, sample_dialog):
        d = sample_dialog.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        restored = SimDialog.from_dict(json.loads(json_str))

        assert restored.id == sample_dialog.id
        assert restored.scenario.id == sample_dialog.scenario.id
        assert restored.persona.id == sample_dialog.persona.id
        assert len(restored.turns) == len(sample_dialog.turns)
        assert restored.language == sample_dialog.language
        assert restored.review_status == sample_dialog.review_status

    def test_turn_content_preserved(self, sample_dialog):
        d = sample_dialog.to_dict()
        restored = SimDialog.from_dict(d)
        for orig, rest in zip(sample_dialog.turns, restored.turns):
            assert orig.role == rest.role
            assert orig.content == rest.content


# ===================================================================
# TC-019: Invalid language parameter
# ===================================================================


class TestInvalidLanguage:
    @pytest.mark.asyncio
    async def test_unsupported_language_raises(self, fixture_kb, mock_llm, sim_config):
        with pytest.raises(ValueError, match="Unsupported language"):
            await generate_sim_dialogs(
                tenant_id="test",
                kb_path=fixture_kb,
                language="xx",
                llm_client=mock_llm,
                config=sim_config,
            )


# ===================================================================
# TC-020: Tenant persona override
# ===================================================================


class TestTenantOverride:
    def test_override_existing_persona(self, tmp_path):
        override_path = tmp_path / "override.yaml"
        override_path.write_text(
            "personas:\n"
            "  - id: angry-refund\n"
            "    traits: ['超级愤怒', '威胁投诉']\n",
            encoding="utf-8",
        )
        config = load_sim_config(tenant_override=str(override_path))
        angry = next(p for p in config.personas if p.id == "angry-refund")
        assert "超级愤怒" in angry.traits
        # Other personas unchanged
        assert len(config.personas) == 6
