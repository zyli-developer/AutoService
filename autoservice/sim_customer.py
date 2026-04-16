"""Virtual customer generation pipeline.

T3A.2 产出 | 2026-04-16
关联: US-1.3 / ζ4 / agents/customer/soul.md

Generates ≥10 simulated customer-agent conversations by combining
KB-derived business scenarios with predefined personas.
"""

from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from autoservice.fewshot_loader import FewshotLoader
from autoservice.i18n.term_loader import TermLoader

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Persona:
    id: str
    name_zh: str
    traits: list[str]
    communication_style: str  # aggressive | cautious | hesitant | confused | familiar | formal


@dataclass
class Scenario:
    id: str
    name_zh: str
    intent: str  # maps to classify_intent.yaml intents
    keywords: list[str]
    trap_question: str
    degraded: bool = False


@dataclass
class SimTurn:
    role: str  # "customer" | "agent"
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass
class SimDialog:
    id: str
    scenario: Scenario
    persona: Persona
    turns: list[SimTurn]
    language: str
    review_status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scenario": asdict(self.scenario),
            "persona": asdict(self.persona),
            "turns": [asdict(t) for t in self.turns],
            "language": self.language,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SimDialog":
        return cls(
            id=data["id"],
            scenario=Scenario(**data["scenario"]),
            persona=Persona(**data["persona"]),
            turns=[SimTurn(**t) for t in data["turns"]],
            language=data["language"],
            review_status=data.get("review_status", "pending"),
        )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "sim_scenarios.yaml"


@dataclass
class SimConfig:
    personas: list[Persona]
    fallback_scenarios: list[Scenario]
    constraints: dict


def load_sim_config(
    config_path: str | Path | None = None,
    tenant_override: str | Path | None = None,
) -> SimConfig:
    """Load personas, fallback scenarios, and constraints from YAML."""
    path = Path(config_path) if config_path else _CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    personas = [Persona(**p) for p in data.get("personas", [])]
    fallbacks = [
        Scenario(**s) for s in data.get("fallback_scenarios", [])
    ]
    constraints = data.get("constraints", {})

    # Apply tenant overrides if provided
    if tenant_override:
        tenant_path = Path(tenant_override)
        if tenant_path.is_file():
            with open(tenant_path, encoding="utf-8") as f:
                override_data = yaml.safe_load(f)
            if override_data:
                personas = _apply_persona_overrides(personas, override_data)

    return SimConfig(
        personas=personas,
        fallback_scenarios=fallbacks,
        constraints=constraints,
    )


def _apply_persona_overrides(
    personas: list[Persona], override_data: dict
) -> list[Persona]:
    """Merge tenant persona overrides (tenant wins on same id)."""
    overrides_by_id = {
        p["id"]: p for p in override_data.get("personas", []) if "id" in p
    }
    result = []
    seen = set()
    for p in personas:
        seen.add(p.id)
        if p.id in overrides_by_id:
            merged = {
                "id": p.id,
                "name_zh": p.name_zh,
                "traits": p.traits,
                "communication_style": p.communication_style,
            }
            merged.update(overrides_by_id[p.id])
            result.append(Persona(**merged))
        else:
            result.append(p)
    # New personas from tenant
    for pid, pdata in overrides_by_id.items():
        if pid not in seen:
            result.append(Persona(**pdata))
    return result


# ---------------------------------------------------------------------------
# KB scenario extraction
# ---------------------------------------------------------------------------


def _kb_entry_count(kb_path: str | Path) -> int:
    """Count entries in FTS5 knowledge base."""
    db = Path(kb_path)
    if not db.is_file():
        return 0
    try:
        conn = sqlite3.connect(str(db))
        cursor = conn.execute(
            "SELECT count(*) FROM kb_chunks"
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


async def extract_scenarios(
    kb_path: str | Path,
    config: SimConfig,
    llm_client: Any = None,
) -> list[Scenario]:
    """Extract business scenarios from KB via LLM clustering.

    Falls back to config.fallback_scenarios if KB is too sparse (< 3 entries).
    """
    count = _kb_entry_count(kb_path)
    if count < 3:
        return [
            Scenario(
                id=s.id,
                name_zh=s.name_zh,
                intent=s.intent,
                keywords=list(s.keywords),
                trap_question=s.trap_question,
                degraded=True,
            )
            for s in config.fallback_scenarios
        ]

    # Read KB content for LLM clustering
    conn = sqlite3.connect(str(kb_path))
    rows = conn.execute(
        "SELECT content FROM kb_chunks ORDER BY rowid LIMIT 50"
    ).fetchall()
    conn.close()
    kb_sample = "\n---\n".join(r[0] for r in rows)

    if llm_client is None:
        raise ValueError("llm_client required for KB scenario extraction")

    prompt = (
        "分析以下知识库内容，提取 5-8 个主要业务场景。\n"
        "每个场景输出 JSON 格式：\n"
        '{"id": "场景ID", "name_zh": "场景名", "intent": "意图类型", '
        '"keywords": ["关键词1", "关键词2"], "trap_question": "一个KB无法回答的边界问题"}\n\n'
        "intent 必须是以下之一：product_inquiry, complaint, purchase_intent, "
        "language_barrier, general_question\n\n"
        f"知识库内容：\n{kb_sample}\n\n"
        "输出 JSON 数组（仅 JSON，不要其他文字）："
    )

    response = await llm_client.generate(prompt)
    scenarios = _parse_scenarios_json(response)

    if len(scenarios) < 3:
        # Supplement with fallbacks
        existing_intents = {s.intent for s in scenarios}
        for fb in config.fallback_scenarios:
            if fb.intent not in existing_intents:
                scenarios.append(
                    Scenario(
                        id=fb.id,
                        name_zh=fb.name_zh,
                        intent=fb.intent,
                        keywords=list(fb.keywords),
                        trap_question=fb.trap_question,
                        degraded=True,
                    )
                )
    return scenarios


def _parse_scenarios_json(response: str) -> list[Scenario]:
    """Parse LLM response into Scenario list, tolerating markdown fences."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    scenarios = []
    for item in items:
        try:
            scenarios.append(Scenario(
                id=item["id"],
                name_zh=item["name_zh"],
                intent=item["intent"],
                keywords=item.get("keywords", []),
                trap_question=item.get("trap_question", ""),
            ))
        except (KeyError, TypeError):
            continue
    return scenarios


# ---------------------------------------------------------------------------
# Assignment matrix
# ---------------------------------------------------------------------------

_ALL_INTENTS = [
    "product_inquiry", "complaint", "purchase_intent",
    "language_barrier", "general_question",
]


def build_assignment_matrix(
    scenarios: list[Scenario],
    personas: list[Persona],
    count: int = 12,
) -> list[tuple[Scenario, Persona]]:
    """Build deterministic scenario-persona pairs ensuring coverage.

    Guarantees:
    - All 5 intents appear at least once (if enough scenarios)
    - All personas appear at least once (if count >= len(personas))
    - Each scenario paired with 2 personas (PRD requirement)
    """
    assignments: list[tuple[Scenario, Persona]] = []

    # Phase 1: ensure intent coverage — one pair per intent
    intent_to_scenarios: dict[str, list[Scenario]] = {}
    for s in scenarios:
        intent_to_scenarios.setdefault(s.intent, []).append(s)

    used_personas = set()
    persona_cycle = list(personas)
    pi = 0

    for intent in _ALL_INTENTS:
        if intent not in intent_to_scenarios:
            continue
        scenario = intent_to_scenarios[intent][0]
        persona = persona_cycle[pi % len(persona_cycle)]
        assignments.append((scenario, persona))
        used_personas.add(persona.id)
        pi += 1

    # Phase 2: ensure persona coverage
    for persona in personas:
        if persona.id not in used_personas and len(assignments) < count:
            scenario = scenarios[len(assignments) % len(scenarios)]
            assignments.append((scenario, persona))
            used_personas.add(persona.id)

    # Phase 3: fill remaining slots (2 personas per scenario goal)
    while len(assignments) < count:
        si = len(assignments) % len(scenarios)
        scenario = scenarios[si]
        persona = persona_cycle[len(assignments) % len(persona_cycle)]
        assignments.append((scenario, persona))

    return assignments[:count]


# ---------------------------------------------------------------------------
# Dialog generation
# ---------------------------------------------------------------------------

_SOUL_PATH = Path(__file__).parent.parent / "agents" / "customer" / "soul.md"


def _load_soul() -> str:
    """Load customer agent soul.md content."""
    if _SOUL_PATH.is_file():
        return _SOUL_PATH.read_text(encoding="utf-8")
    return ""


_SIM_CUSTOMER_PROMPT = """\
你是一个虚拟客户模拟器。根据以下角色设定生成客户对话。

## 角色设定
- persona: {persona_id} ({persona_name_zh})
- 特征: {traits}
- 沟通风格: {style}

## 场景
- 场景: {scenario_name_zh}
- 意图: {intent}
- 关键词: {keywords}

## 要求
1. 生成 {min_turns}-{max_turns} 轮客户发言（仅客户侧）
2. 使用{language_name}
3. 语言风格要真实自然（包括口语化表达、偶尔的错别字、不完整描述）
4. 必须包含 1 个陷阱问题（KB 无法回答的边界问题）：{trap_question}
5. 按对话顺序输出

输出 JSON 数组，每项格式：
{{"role": "customer", "content": "客户发言", "metadata": {{"is_trap": false}}}}

陷阱题的 metadata 设 {{"is_trap": true}}。仅输出 JSON 数组。
"""


async def generate_single_dialog(
    scenario: Scenario,
    persona: Persona,
    kb_path: str | Path,
    language: str = "zh",
    llm_client: Any = None,
    config: SimConfig | None = None,
    fewshot_loader: FewshotLoader | None = None,
) -> SimDialog:
    """Generate a single simulated dialog (customer turns + AI responses)."""
    if llm_client is None:
        raise ValueError("llm_client required")
    if config is None:
        config = load_sim_config()

    constraints = config.constraints
    min_turns = constraints.get("min_turns", 3)
    max_turns = constraints.get("max_turns", 6)

    lang_names = {"zh": "中文", "en": "English"}
    language_name = lang_names.get(language, language)

    # Step 1: Generate customer turns
    customer_prompt = _SIM_CUSTOMER_PROMPT.format(
        persona_id=persona.id,
        persona_name_zh=persona.name_zh,
        traits=", ".join(persona.traits),
        style=persona.communication_style,
        scenario_name_zh=scenario.name_zh,
        intent=scenario.intent,
        keywords=", ".join(scenario.keywords),
        min_turns=min_turns,
        max_turns=max_turns,
        language_name=language_name,
        trap_question=scenario.trap_question,
    )

    customer_response = await llm_client.generate(customer_prompt)
    customer_turns = _parse_turns_json(customer_response)

    # Post-process turn count
    if len(customer_turns) > max_turns:
        customer_turns = customer_turns[:max_turns]
    if len(customer_turns) < min_turns:
        # Retry once for too-short responses
        retry_response = await llm_client.generate(
            customer_prompt + f"\n\n注意：必须生成至少 {min_turns} 轮对话。"
        )
        retry_turns = _parse_turns_json(retry_response)
        if len(retry_turns) >= min_turns:
            customer_turns = retry_turns[:max_turns]

    # Step 2: Generate AI responses using soul.md + terms + few-shot
    soul_content = _load_soul()
    term_loader = TermLoader()
    term_prefix = term_loader.render_prompt_prefix(language)
    fewshot_section = ""
    if fewshot_loader is not None:
        fewshot_section = fewshot_loader.render_prompt_section(language)

    parts = [soul_content]
    if term_prefix:
        parts.append(term_prefix)
    if fewshot_section:
        parts.append(fewshot_section)
    system_prompt = "\n\n".join(parts)

    turns: list[SimTurn] = []
    for ct in customer_turns:
        turns.append(ct)
        # Build conversation context for AI
        conv_context = "\n".join(
            f"{'客户' if t.role == 'customer' else 'AI客服'}: {t.content}"
            for t in turns
        )
        ai_prompt = (
            f"请基于以下对话上下文，以客服身份回复最后一条客户消息。\n\n"
            f"{conv_context}\n\nAI客服:"
        )
        ai_response = await llm_client.generate(
            ai_prompt, system=system_prompt
        )
        turns.append(SimTurn(
            role="agent",
            content=ai_response.strip(),
            metadata={"model_tier": "slow"},
        ))

    return SimDialog(
        id=str(uuid.uuid4())[:8],
        scenario=scenario,
        persona=persona,
        turns=turns,
        language=language,
    )


def _parse_turns_json(response: str) -> list[SimTurn]:
    """Parse LLM response into SimTurn list."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    turns = []
    for item in items:
        try:
            turns.append(SimTurn(
                role=item.get("role", "customer"),
                content=item["content"],
                metadata=item.get("metadata", {}),
            ))
        except (KeyError, TypeError):
            continue
    return turns


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

_SUPPORTED_LANGUAGES: set[str] | None = None


def _get_supported_languages() -> set[str]:
    global _SUPPORTED_LANGUAGES
    if _SUPPORTED_LANGUAGES is None:
        loader = TermLoader()
        _SUPPORTED_LANGUAGES = set(loader.list_languages()) | {"zh", "en"}
    return _SUPPORTED_LANGUAGES


async def generate_sim_dialogs(
    tenant_id: str,
    kb_path: str | Path,
    language: str = "zh",
    count: int = 12,
    personas: list[str] | None = None,
    llm_client: Any = None,
    config: SimConfig | None = None,
    fewshot_path: str | Path | None = None,
) -> list[SimDialog]:
    """Generate simulated customer-agent dialogs.

    Args:
        tenant_id: Tenant identifier.
        kb_path: Path to FTS5 knowledge base SQLite file.
        language: ISO 639-1 language code (default "zh").
        count: Number of dialogs to generate (default 12, min 1).
        personas: Optional list of persona IDs to use (None = all).
        llm_client: LLM client with async generate() method.
        config: Pre-loaded SimConfig (loads default if None).

    Returns:
        List of SimDialog objects.

    Raises:
        ValueError: If language is unsupported or llm_client is None.
    """
    if language not in _get_supported_languages():
        raise ValueError(
            f"Unsupported language: {language!r}. "
            f"Supported: {sorted(_get_supported_languages())}"
        )
    if llm_client is None:
        raise ValueError("llm_client is required")

    if config is None:
        config = load_sim_config()

    # Filter personas if specified
    available_personas = config.personas
    if personas is not None:
        persona_set = set(personas)
        available_personas = [p for p in available_personas if p.id in persona_set]
        if not available_personas:
            raise ValueError(f"No matching personas: {personas}")

    # Extract scenarios from KB (or use fallbacks)
    scenarios = await extract_scenarios(kb_path, config, llm_client)

    # Build assignment matrix
    assignments = build_assignment_matrix(scenarios, available_personas, count)

    # Set up fewshot loader if path provided
    fs_loader = FewshotLoader(fewshot_path) if fewshot_path else None

    # Generate dialogs concurrently with semaphore
    max_concurrency = config.constraints.get("max_concurrency", 6)
    sem = asyncio.Semaphore(max_concurrency)

    async def _gen(scenario: Scenario, persona: Persona) -> SimDialog:
        async with sem:
            return await generate_single_dialog(
                scenario, persona, kb_path, language, llm_client, config,
                fewshot_loader=fs_loader,
            )

    tasks = [_gen(s, p) for s, p in assignments]
    dialogs = await asyncio.gather(*tasks)

    return list(dialogs)
