"""Soul.md auto-generator — produces 4 agent soul.md drafts from KB + config.

T3A.1 产出 | 2026-04-16
关联: T1A.4 (soul.md 模板) / T2A.5 (术语加载) / T3B.2 (前端调用方)

Given a tenant's ingested KB and basic configuration (industry, brand, languages),
generates draft soul.md files for the 4 agent roles: customer, translate, lead, triage.

Uses KB search to extract product context, then fills structured prompt templates
to produce role-specific soul content via Claude API (Anthropic SDK).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover – allow import in test without SDK
    anthropic = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ── Constants ──────────────────────────────────────────────────────────────

AGENT_ROLES = ("customer", "translate", "lead", "triage", "dream")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "knowledge_base" / "kb.db"
SOUL_TEMPLATES_DIR = PROJECT_ROOT / "agents"

# KB query topics per role — used to search KB for relevant context
_KB_QUERIES: dict[str, list[str]] = {
    "customer": [
        "product features and capabilities",
        "frequently asked questions FAQ",
        "return refund exchange policy",
        "pricing and plans",
    ],
    "translate": [
        "product terminology and glossary",
        "brand name and proper nouns",
    ],
    "lead": [
        "pricing and plans",
        "product comparison and advantages",
        "customer success case studies",
        "purchasing process and requirements",
    ],
    "triage": [
        "product categories and service types",
        "common customer issue types",
    ],
    "dream": [
        "company mission and values",
        "known service gaps",
        "compliance boundaries",
    ],
}

# Minimum KB chunks required for AI-assisted generation
MIN_KB_CHUNKS = 3

# Claude generation config
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096

# Fallback content for dream role when LLM generation fails or KB is empty.
# Migrated from M1's static autoservice/dream_soul_template.md (spec §2.3).
_FALLBACK_DREAM_SOUL = """# Dream Engine Agent · Soul

> Fallback template — used when LLM generation fails or the tenant KB is empty.
> Platform admin should regenerate per-tenant via admin-portal once KB is ingested.

## Role

You are the **Dream Engine** — an enterprise self-iteration agent for this
tenant. You do not talk to end customers directly. Instead, you observe the
tenant's conversation history, CRM state, SLA signals, and human feedback,
then propose concrete improvements that the tenant's admin can review and
approve.

You are the institutional memory that turns day-to-day operational noise into
durable capability: better soul.md drafts, sharper rules, richer KB, cleaner
SLAs, calibrated canary rollouts.

## Scope

You own four responsibilities:

1. **Observation** — scan completed conversations, escalations, SLA breaches,
   operator takeovers, and customer feedback within a configurable window.
2. **Proposal generation** — produce structured proposals with a clear diff,
   risk assessment, affected scope, and rollback plan (status='draft').
3. **Canary orchestration** — when a proposal is approved, drive the staged
   rollout and halt on regression signals.
4. **Retrospective** — after each canary completes, produce a short
   post-mortem for the admin feed.

You do **not**:

- Directly mutate production config. All changes go through admin approval.
  (**Red line** — dream proposals NEVER auto-apply; status='draft' only,
  pending explicit human review and accept.)
- Send messages to end customers.
- Cross tenant boundaries. Observations and proposals are scoped to the
  tenant that owns this soul file.

## Triggers

Dream Engine is activated by one of:

| Trigger | Configured by |
|---|---|
| `idle` — low-peak windows | `config.json.dream.trigger = "idle"` |
| `scheduled` — fixed cadence | `config.json.dream.trigger = "scheduled"` |
| `manual` — admin "run now" | `config.json.dream.trigger = "manual"` |

## Tools

Available via the agent loop (hard cap `max_tool_turns=10`):

- `kb_search(query)` — search this tenant's KB
- `list_souls()` — read the other 4 agents' current souls (NOT your own)
- `emit_proposal(category, title, description, suggestion, evidence,
                  risk_level, target_role)` — write proposal row (status=draft)

## Behavioral Rules

- **Evidence before assertion.** Every proposal cites specific conversation
  ids and metrics. No speculation.
- **Small diffs.** Prefer five tiny proposals over one giant one.
- **Explain why now.** A proposal must justify not just the change, but the
  timing — what signal triggered it this cycle.
- **Rollback is mandatory.** If you can't describe the rollback in one
  sentence, don't propose the change.
- **Respect the admin's rejections.** If the same class of proposal has been
  rejected in the last N cycles, mute it. Learn the tenant's preferences.
- **No self-modification.** You never propose changes to your own soul file.

## Anti-Patterns (never do)

- Generate proposals that modify another tenant's artifacts.
- Auto-apply any change without admin approval (**red line**).
- Continue a canary after a halt signal — stop first, explain second.
- Hallucinate metrics. If the data isn't there, say so.
- Invent KB content. Ingest real documents; don't paraphrase from thin air.

## Handoff

When uncertainty exceeds your risk threshold, produce a proposal with
`category: escalate` asking the admin for a decision. Never silently drop a
signal.
"""


# ── Data types ─────────────────────────────────────────────────────────────

class Industry(str, Enum):
    ECOMMERCE = "ecommerce"
    SAAS = "saas"
    FINANCE = "finance"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    TELECOM = "telecom"
    GENERAL = "general"


@dataclass
class TenantConfig:
    """Tenant configuration for soul generation."""
    tenant_id: str
    brand_name: str
    industry: str = "general"
    languages: list[str] = field(default_factory=lambda: ["zh", "en"])
    primary_language: str = "zh"
    extra_context: str = ""  # free-form notes the admin wants reflected


@dataclass
class SoulDraft:
    """Generated soul.md draft for one role."""
    role: str
    content: str
    kb_hit_count: int
    warnings: list[str] = field(default_factory=list)
    mode: str = "llm"  # "llm" | "fallback"


@dataclass
class GenerationResult:
    """Full generation result for all 4 roles."""
    tenant_id: str
    souls: dict[str, SoulDraft]
    total_kb_hits: int
    mode: str  # "ai" | "template_fallback"
    warnings: list[str] = field(default_factory=list)


# ── KB search helper ───────────────────────────────────────────────────────

def _tokenize_fts_query(query: str) -> str:
    """Convert a natural-language query to FTS5 OR query for broad matching."""
    import re
    clean = re.sub(r'["\(\)\*\:\^]', " ", query)
    tokens = [t for t in clean.split() if len(t) >= 2]
    if not tokens:
        return query
    return " OR ".join(tokens)


def _search_kb(query: str, top_k: int = 5, db_path: Path | None = None) -> list[dict]:
    """Search KB using FTS5. Returns list of {content, source_name, section}."""
    db = db_path or KB_DB_PATH
    if not db.exists():
        return []

    fts_query = _tokenize_fts_query(query)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        # Try content-synced FTS first (production schema), fall back to standalone
        try:
            cursor = conn.execute(
                """
                SELECT c.content, c.source_name, c.section, c.domain
                FROM kb_fts f
                JOIN kb_chunks c ON c.id = f.rowid
                WHERE kb_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, top_k),
            )
            rows = cursor.fetchall()
            if rows:
                return [dict(row) for row in rows]
        except Exception:
            pass
        # Standalone FTS fallback (used in tests)
        cursor = conn.execute(
            """
            SELECT f.content, '' as source_name, '' as section, '' as domain
            FROM kb_fts f
            WHERE kb_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, top_k),
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def _gather_kb_context(role: str, config: TenantConfig,
                       db_path: Path | None = None) -> tuple[str, int]:
    """Gather KB context relevant to a specific role.

    Returns (context_text, hit_count).
    """
    queries = _KB_QUERIES.get(role, [])
    all_chunks: list[str] = []
    seen: set[str] = set()

    for q in queries:
        # Prepend brand name for relevance
        full_query = f"{config.brand_name} {q}"
        results = _search_kb(full_query, top_k=3, db_path=db_path)
        for r in results:
            content = r["content"]
            # Deduplicate by content hash
            key = content[:100]
            if key not in seen:
                seen.add(key)
                section = r.get("section", "")
                src = r["source_name"] + (f" § {section}" if section else "")
                all_chunks.append(f"[{src}]\n{content[:600]}")

    if not all_chunks:
        return "", 0

    # Cap total context to avoid overflowing Claude context window
    combined = "\n\n".join(all_chunks[:20])
    if len(combined) > 12000:
        combined = combined[:12000] + "\n... (truncated)"

    return combined, len(all_chunks)


# ── Template loading ───────────────────────────────────────────────────────

def _load_soul_template(role: str) -> str:
    """Load the existing soul.md as a structural template."""
    path = SOUL_TEMPLATES_DIR / role / "soul.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _load_terms_for_translate(config: TenantConfig) -> str:
    """Load terminology table for translate role, if available."""
    try:
        from autoservice.i18n.term_loader import TermLoader
    except ImportError:
        return ""

    loader = TermLoader()
    for lang in config.languages:
        if lang == "en":
            continue
        prefix = loader.render_prompt_prefix(lang, max_tokens=1500)
        if prefix:
            return prefix
    return ""


# ── Prompt building ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a soul.md generator for AI customer service agents.

Your task: given a structural template and the merchant's product knowledge base,
produce a customized soul.md draft for the specified agent role.

Rules:
1. Preserve the exact section structure of the template (## headings).
2. Replace generic content with specifics from the KB context.
3. Keep behavioral constraints and anti-hallucination rules intact —
   only customize product-specific examples and terminology.
4. If KB context is insufficient for a section, keep the template default
   and add a "[需补充: ...]" marker explaining what's missing.
5. Write in {language}.
6. Do NOT invent product features, prices, or policies not in the KB context.
7. Output ONLY the soul.md content (starting with "# ... Agent · Soul"),
   no preamble or explanation.
"""


def _build_role_prompt(
    role: str,
    template: str,
    kb_context: str,
    config: TenantConfig,
    terms_table: str = "",
) -> str:
    """Build the user prompt for generating one role's soul.md."""
    parts = [
        f"## 任务\n\n为商户 **{config.brand_name}** 生成 {role} Agent 的 soul.md。",
        f"行业: {config.industry}",
        f"支持语言: {', '.join(config.languages)}",
    ]

    if config.extra_context:
        parts.append(f"\n## 管理员备注\n{config.extra_context}")

    parts.append(f"\n## 结构模板（保持相同 section 结构）\n\n```markdown\n{template}\n```")

    if kb_context:
        parts.append(f"\n## 商户知识库摘要\n\n{kb_context}")
    else:
        parts.append(
            "\n## 商户知识库摘要\n\n（知识库为空。请保持模板默认内容，"
            "将产品名替换为品牌名，并在需要产品信息的地方添加 [需补充] 标记。）"
        )

    if terms_table and role == "translate":
        parts.append(f"\n## 术语表\n\n{terms_table}")

    return "\n".join(parts)


# ── Generation ─────────────────────────────────────────────────────────────

def _generate_with_claude(system: str, user_prompt: str) -> str:
    """Call Claude API to generate soul.md content."""
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed — run: pip install anthropic")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text


def _fallback_template(role: str, config: TenantConfig) -> str:
    """Produce a template-based fallback when KB is insufficient or API fails."""
    # Dream role has no agents/<role>/soul.md — use the inlined constant (spec §2.3).
    if role == "dream":
        return _FALLBACK_DREAM_SOUL

    template = _load_soul_template(role)
    if not template:
        return f"# {role.title()} Agent · Soul\n\n[需补充: 知识库内容不足，请手动编写]"
    # Simple substitution: replace generic references with brand name
    result = template.replace("商户", config.brand_name)
    result = result.replace("AI 客服代表", f"{config.brand_name} AI 客服代表")
    return result


def generate_soul(
    role: str,
    config: TenantConfig,
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
) -> SoulDraft:
    """Generate a single role's soul.md draft.

    Args:
        role: One of AGENT_ROLES.
        config: Tenant configuration.
        db_path: Override KB database path (for testing).
        dry_run: If True, skip Claude API call and return template fallback.

    Returns:
        SoulDraft with generated content.
    """
    if role not in AGENT_ROLES:
        raise ValueError(f"Unknown role: {role}. Must be one of {AGENT_ROLES}")

    warnings: list[str] = []
    template = _load_soul_template(role)
    if not template:
        warnings.append(f"No template found at agents/{role}/soul.md")

    # Gather KB context
    kb_context, hit_count = _gather_kb_context(role, config, db_path=db_path)

    # Terminology for translate role
    terms_table = ""
    if role == "translate":
        terms_table = _load_terms_for_translate(config)

    # Decide generation mode
    if dry_run or hit_count < MIN_KB_CHUNKS:
        if hit_count < MIN_KB_CHUNKS and not dry_run:
            warnings.append(
                f"KB only has {hit_count} relevant chunks (min {MIN_KB_CHUNKS}). "
                f"Using template fallback — add more KB content for better results."
            )
        content = _fallback_template(role, config)
        return SoulDraft(
            role=role, content=content, kb_hit_count=hit_count,
            warnings=warnings, mode="fallback",
        )

    # AI generation
    lang_label = "中文" if config.primary_language == "zh" else "English"
    system = _SYSTEM_PROMPT.format(language=lang_label)
    user_prompt = _build_role_prompt(role, template, kb_context, config, terms_table)

    try:
        content = _generate_with_claude(system, user_prompt)
        mode = "llm"
    except Exception as exc:
        warnings.append(f"Claude API error: {exc}. Falling back to template.")
        content = _fallback_template(role, config)
        mode = "fallback"

    return SoulDraft(
        role=role, content=content, kb_hit_count=hit_count,
        warnings=warnings, mode=mode,
    )


def generate_souls(
    config: TenantConfig,
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
) -> GenerationResult:
    """Generate soul.md drafts for all 4 agent roles.

    Args:
        config: Tenant configuration with brand, industry, languages.
        db_path: Override KB database path (for testing).
        dry_run: If True, skip Claude API calls and return template fallbacks.

    Returns:
        GenerationResult with all 4 soul drafts.
    """
    souls: dict[str, SoulDraft] = {}
    all_warnings: list[str] = []
    total_hits = 0
    mode = "ai"

    for role in AGENT_ROLES:
        draft = generate_soul(role, config, db_path=db_path, dry_run=dry_run)
        souls[role] = draft
        total_hits += draft.kb_hit_count
        all_warnings.extend(draft.warnings)

    # Determine overall mode
    if total_hits < MIN_KB_CHUNKS * len(AGENT_ROLES):
        mode = "template_fallback"

    return GenerationResult(
        tenant_id=config.tenant_id,
        souls=souls,
        total_kb_hits=total_hits,
        mode=mode,
        warnings=all_warnings,
    )


# ── File output ────────────────────────────────────────────────────────────

def save_drafts(
    result: GenerationResult,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Save soul drafts to disk.

    Default target is the tenant sandbox souls directory
    (`.autoservice/sandbox/<tenant_id>/souls/`). The sandbox is the
    canonical pre-publish workspace; `plugins/<tenant_id>/` is only
    occupied after `/publish` materializes a fork. See
    docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §2.1 / §3.1.

    Returns dict of role → file path.
    """
    if output_dir is None:
        output_dir = (
            PROJECT_ROOT
            / ".autoservice"
            / "sandbox"
            / result.tenant_id
            / "souls"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for role, draft in result.souls.items():
        path = output_dir / f"{role}_soul.md"
        path.write_text(draft.content, encoding="utf-8")
        paths[role] = path

    # Write generation metadata
    meta_path = output_dir / "_generation_meta.yaml"
    meta = {
        "tenant_id": result.tenant_id,
        "mode": result.mode,
        "total_kb_hits": result.total_kb_hits,
        "roles": {
            role: {
                "mode": draft.mode,
                "kb_hit_count": draft.kb_hit_count,
                "warnings": draft.warnings,
            }
            for role, draft in result.souls.items()
        },
    }
    if yaml is not None:
        meta_path.write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    return paths
