"""Tests for autoservice.soul_generator.

T3A.1 tests | 2026-04-16
Covers: TenantConfig, KB context gathering, template fallback, prompt building,
        generate_soul (dry_run), generate_souls, save_drafts.
"""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from autoservice.soul_generator import (
    AGENT_ROLES,
    MIN_KB_CHUNKS,
    TenantConfig,
    SoulDraft,
    GenerationResult,
    Industry,
    _search_kb,
    _gather_kb_context,
    _load_soul_template,
    _build_role_prompt,
    _fallback_template,
    generate_soul,
    generate_souls,
    save_drafts,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tenant_config() -> TenantConfig:
    return TenantConfig(
        tenant_id="test_shop",
        brand_name="TestShop",
        industry="ecommerce",
        languages=["zh", "en"],
        primary_language="zh",
    )


@pytest.fixture
def kb_db(tmp_path: Path) -> Path:
    """Create a temporary KB database with sample data."""
    db_path = tmp_path / "kb.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE kb_chunks (
            id INTEGER PRIMARY KEY,
            source_id TEXT,
            source_type TEXT,
            source_name TEXT,
            source_url TEXT,
            file_path TEXT,
            section TEXT,
            content TEXT,
            domain TEXT,
            region TEXT,
            language TEXT,
            page_number INTEGER,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE kb_fts USING fts5(content)
    """)
    # Insert sample KB data
    samples = [
        ("f1", "docs", "TestShop Product Guide", "", "", "Overview",
         "TestShop is an ecommerce platform offering electronics, clothing, and home goods. "
         "Features include one-click checkout, 30-day returns, and 24/7 support.",
         "ecommerce", "CN", "en"),
        ("f1", "docs", "TestShop Product Guide", "", "", "Pricing",
         "TestShop offers three plans: Basic ($9/mo), Pro ($29/mo), and Enterprise (custom). "
         "All plans include free shipping on orders over $50.",
         "ecommerce", "CN", "en"),
        ("f1", "docs", "TestShop FAQ", "", "", "Returns",
         "Return policy: Items can be returned within 30 days of purchase. "
         "Refunds processed within 5-7 business days. Shipping costs are non-refundable.",
         "ecommerce", "CN", "en"),
        ("f1", "docs", "TestShop FAQ", "", "", "Support",
         "Customer support is available 24/7 via live chat, email, and phone. "
         "Average response time is under 2 minutes for chat.",
         "ecommerce", "CN", "en"),
        ("f1", "docs", "TestShop FAQ", "", "", "Products",
         "Our product catalog includes over 10,000 items across electronics, fashion, "
         "home & garden, and sports categories. New items added weekly.",
         "ecommerce", "CN", "en"),
    ]
    for s in samples:
        conn.execute(
            "INSERT INTO kb_chunks (source_id, source_type, source_name, source_url, "
            "file_path, section, content, domain, region, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", s,
        )
    # Populate FTS index — insert content into standalone FTS table
    for row in conn.execute("SELECT id, content FROM kb_chunks"):
        conn.execute("INSERT INTO kb_fts(rowid, content) VALUES (?, ?)",
                     (row[0], row[1]))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_kb_db(tmp_path: Path) -> Path:
    """Create an empty KB database."""
    db_path = tmp_path / "kb_empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE kb_chunks (
            id INTEGER PRIMARY KEY, source_id TEXT, source_type TEXT,
            source_name TEXT, source_url TEXT, file_path TEXT, section TEXT,
            content TEXT, domain TEXT, region TEXT, language TEXT,
            page_number INTEGER, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE kb_fts USING fts5(content, content=kb_chunks, content_rowid=id)
    """)
    conn.commit()
    conn.close()
    return db_path


# ── TenantConfig tests ────────────────────────────────────────────────────

class TestTenantConfig:
    def test_defaults(self):
        tc = TenantConfig(tenant_id="t1", brand_name="Brand")
        assert tc.industry == "general"
        assert tc.languages == ["zh", "en"]
        assert tc.primary_language == "zh"
        assert tc.extra_context == ""

    def test_custom_values(self):
        tc = TenantConfig(
            tenant_id="t2", brand_name="SaaSTool",
            industry="saas", languages=["en"], primary_language="en",
            extra_context="Focus on B2B enterprise features",
        )
        assert tc.industry == "saas"
        assert tc.extra_context == "Focus on B2B enterprise features"


# ── KB search tests ────────────────────────────────────────────────────────

class TestKBSearch:
    def test_search_with_results(self, kb_db: Path):
        results = _search_kb("product features", top_k=3, db_path=kb_db)
        assert len(results) > 0
        assert "content" in results[0]

    def test_search_no_db(self, tmp_path: Path):
        results = _search_kb("anything", db_path=tmp_path / "nonexistent.db")
        assert results == []

    def test_search_empty_db(self, empty_kb_db: Path):
        results = _search_kb("product", db_path=empty_kb_db)
        assert results == []

    def test_gather_kb_context(self, kb_db: Path, tenant_config: TenantConfig):
        context, hits = _gather_kb_context("customer", tenant_config, db_path=kb_db)
        assert hits > 0
        assert len(context) > 0

    def test_gather_kb_context_empty(self, empty_kb_db: Path, tenant_config: TenantConfig):
        context, hits = _gather_kb_context("customer", tenant_config, db_path=empty_kb_db)
        assert hits == 0
        assert context == ""


# ── Template tests ─────────────────────────────────────────────────────────

class TestTemplates:
    def test_load_existing_template(self):
        template = _load_soul_template("customer")
        assert "# Customer Service Agent" in template
        assert "## 角色定位" in template

    def test_load_all_templates(self):
        # 'dream' intentionally has no agents/dream/soul.md — uses
        # _FALLBACK_DREAM_SOUL constant instead (spec §2.3).
        for role in AGENT_ROLES:
            if role == "dream":
                continue
            template = _load_soul_template(role)
            assert template, f"Template for {role} should not be empty"
            assert "## 角色定位" in template

    def test_load_nonexistent_template(self):
        template = _load_soul_template("nonexistent_role")
        assert template == ""


# ── Prompt building tests ──────────────────────────────────────────────────

class TestPromptBuilding:
    def test_build_prompt_with_kb(self, tenant_config: TenantConfig):
        template = _load_soul_template("customer")
        kb_context = "[TestShop Docs]\nTestShop sells electronics."
        prompt = _build_role_prompt("customer", template, kb_context, tenant_config)
        assert "TestShop" in prompt
        assert "ecommerce" in prompt
        assert "知识库摘要" in prompt
        assert "electronics" in prompt

    def test_build_prompt_without_kb(self, tenant_config: TenantConfig):
        template = _load_soul_template("customer")
        prompt = _build_role_prompt("customer", template, "", tenant_config)
        assert "知识库为空" in prompt
        assert "[需补充]" in prompt

    def test_build_prompt_with_extra_context(self):
        tc = TenantConfig(
            tenant_id="t1", brand_name="B",
            extra_context="We handle high-value orders",
        )
        template = "# Template"
        prompt = _build_role_prompt("customer", template, "kb data", tc)
        assert "管理员备注" in prompt
        assert "high-value orders" in prompt

    def test_build_prompt_translate_with_terms(self, tenant_config: TenantConfig):
        template = _load_soul_template("translate")
        terms = "术语表 (zh):\n| 英文 | 翻译 |\n| Checkout | 结账 |"
        prompt = _build_role_prompt("translate", template, "kb", tenant_config, terms)
        assert "术语表" in prompt
        assert "Checkout" in prompt


# ── Fallback template tests ───────────────────────────────────────────────

class TestFallback:
    def test_fallback_substitutes_brand(self, tenant_config: TenantConfig):
        content = _fallback_template("customer", tenant_config)
        assert "TestShop" in content

    def test_fallback_nonexistent_role(self, tenant_config: TenantConfig):
        content = _fallback_template("nonexistent", tenant_config)
        assert "[需补充" in content


# ── Generation tests (dry_run) ─────────────────────────────────────────────

class TestGenerateDryRun:
    def test_generate_soul_dry_run(self, tenant_config: TenantConfig, kb_db: Path):
        draft = generate_soul("customer", tenant_config, db_path=kb_db, dry_run=True)
        assert isinstance(draft, SoulDraft)
        assert draft.role == "customer"
        assert len(draft.content) > 0

    def test_generate_soul_invalid_role(self, tenant_config: TenantConfig):
        with pytest.raises(ValueError, match="Unknown role"):
            generate_soul("invalid", tenant_config)

    def test_generate_souls_dry_run(self, tenant_config: TenantConfig, kb_db: Path):
        result = generate_souls(tenant_config, db_path=kb_db, dry_run=True)
        assert isinstance(result, GenerationResult)
        assert set(result.souls.keys()) == set(AGENT_ROLES)
        for role, draft in result.souls.items():
            assert draft.role == role
            assert len(draft.content) > 0

    def test_generate_souls_empty_kb_fallback(
        self, tenant_config: TenantConfig, empty_kb_db: Path,
    ):
        result = generate_souls(tenant_config, db_path=empty_kb_db)
        assert result.mode == "template_fallback"
        assert any("template fallback" in w.lower() or "KB only has" in w
                    for w in result.warnings)


# ── Generation tests (mocked Claude API) ──────────────────────────────────

class TestGenerateWithMock:
    def test_generate_soul_calls_claude(self, tenant_config: TenantConfig, kb_db: Path):
        mock_content = "# Customer Service Agent · Soul\n\n## 角色定位\n\nCustomized content."
        # Patch _gather_kb_context to ensure enough hits to trigger AI mode
        fake_context = ("KB context about TestShop products", 10)
        with patch("autoservice.soul_generator._gather_kb_context", return_value=fake_context), \
             patch("autoservice.soul_generator._generate_with_claude", return_value=mock_content):
            draft = generate_soul("customer", tenant_config, db_path=kb_db)
        assert draft.content == mock_content
        assert draft.kb_hit_count >= MIN_KB_CHUNKS

    def test_generate_soul_api_failure_fallback(
        self, tenant_config: TenantConfig, kb_db: Path,
    ):
        fake_context = ("KB context about TestShop products", 10)
        with patch("autoservice.soul_generator._gather_kb_context", return_value=fake_context), \
             patch(
                "autoservice.soul_generator._generate_with_claude",
                side_effect=RuntimeError("API timeout"),
             ):
            draft = generate_soul("customer", tenant_config, db_path=kb_db)
        assert any("Claude API error" in w for w in draft.warnings)
        # Should fall back to template content
        assert "Customer Service Agent" in draft.content


# ── Save drafts tests ─────────────────────────────────────────────────────

class TestSaveDrafts:
    def test_save_creates_files(self, tmp_path: Path, tenant_config: TenantConfig):
        souls = {
            role: SoulDraft(role=role, content=f"# {role} soul", kb_hit_count=5)
            for role in AGENT_ROLES
        }
        result = GenerationResult(
            tenant_id="test_shop", souls=souls,
            total_kb_hits=20, mode="ai",
        )
        output_dir = tmp_path / "drafts"
        paths = save_drafts(result, output_dir=output_dir)

        assert len(paths) == len(AGENT_ROLES)
        for role, path in paths.items():
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert f"# {role} soul" in content

        # Check metadata file
        meta = output_dir / "_generation_meta.yaml"
        assert meta.exists()

    def test_save_does_not_overwrite_agents(self, tmp_path: Path, tenant_config: TenantConfig):
        """Verify drafts go to separate directory, not agents/."""
        souls = {
            role: SoulDraft(role=role, content=f"# {role}", kb_hit_count=5)
            for role in AGENT_ROLES
        }
        result = GenerationResult(
            tenant_id="test_shop", souls=souls,
            total_kb_hits=20, mode="ai",
        )
        output_dir = tmp_path / "souls_draft"
        save_drafts(result, output_dir=output_dir)

        # Original agent souls should be untouched
        for role in AGENT_ROLES:
            original = Path(__file__).resolve().parent.parent / "agents" / role / "soul.md"
            if original.exists():
                assert "# {role}" not in original.read_text(encoding="utf-8")
