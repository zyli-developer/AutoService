"""T1B.2 — Dream role extension in soul_generator.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.3
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from autoservice import soul_generator
from autoservice.soul_generator import (
    AGENT_ROLES,
    TenantConfig,
    generate_soul,
    generate_souls,
    save_drafts,
)


@pytest.fixture
def tenant_config() -> TenantConfig:
    return TenantConfig(
        tenant_id="_master",
        brand_name="AutoService",
        industry="platform-ops",
        languages=["zh", "en"],
        primary_language="zh",
    )


class TestDreamRoleRegistration:
    def test_dream_appended_to_agent_roles(self):
        """AGENT_ROLES must contain all 5 roles including dream."""
        assert "dream" in AGENT_ROLES
        assert set(AGENT_ROLES) >= {"customer", "translate", "lead", "triage", "dream"}
        assert len(AGENT_ROLES) == 5

    def test_dream_has_kb_queries(self):
        """_KB_QUERIES must define dream-specific retrieval prompts."""
        assert "dream" in soul_generator._KB_QUERIES
        queries = soul_generator._KB_QUERIES["dream"]
        assert isinstance(queries, list) and len(queries) >= 2
        assert all(isinstance(q, str) and q for q in queries)

    def test_fallback_dream_soul_constant_exists(self):
        """_FALLBACK_DREAM_SOUL must be a non-empty string with core markers."""
        assert hasattr(soul_generator, "_FALLBACK_DREAM_SOUL")
        content = soul_generator._FALLBACK_DREAM_SOUL
        assert isinstance(content, str) and len(content) > 200
        # Key red-line markers from spec §2.3 / CON-04
        assert "Dream" in content
        assert "proposal" in content.lower()

    def test_fallback_dream_soul_preserves_red_line_literal(self):
        """The red line ('NEVER auto-apply' + status='draft') must be verbatim.

        This test locks in CON-04: dream proposals never mutate config without
        human review. If someone edits the constant to soften that wording,
        this test fails loudly so reviewers notice the red-line erosion.
        """
        content = soul_generator._FALLBACK_DREAM_SOUL
        assert "NEVER auto-apply" in content, (
            "Red line CON-04 wording missing from _FALLBACK_DREAM_SOUL — "
            "dream proposals must never auto-apply."
        )
        assert "status='draft'" in content, (
            "Red line CON-04 wording missing from _FALLBACK_DREAM_SOUL — "
            "proposals must be status='draft' pending human review."
        )


class TestDreamBrandNeutrality:
    def test_dream_fallback_not_brand_substituted(self, tmp_path):
        """Dream fallback is a platform-level soul — no brand substitution.

        Other 4 roles substitute '商户' → brand_name; dream must not, because
        §3 / §2.7 has `_master` (platform) own dream governance, not the tenant.
        """
        config = TenantConfig(
            tenant_id="acme",
            brand_name="AcmeShop",
            industry="ecommerce",
        )
        draft = generate_soul(
            "dream", config, db_path=tmp_path / "kb.db", dry_run=True
        )
        # The raw constant should pass through unaltered (no 商户 → AcmeShop swap).
        assert draft.content == soul_generator._FALLBACK_DREAM_SOUL
        assert "AcmeShop" not in draft.content


class TestDreamFallback:
    def test_dream_dry_run_uses_fallback_constant(self, tenant_config, tmp_path):
        """dry_run=True for dream role → content == _FALLBACK_DREAM_SOUL."""
        empty_kb = tmp_path / "empty_kb.db"
        # Don't even create the file — _search_kb handles missing gracefully
        draft = generate_soul(
            "dream", tenant_config, db_path=empty_kb, dry_run=True
        )
        assert draft.role == "dream"
        assert draft.content == soul_generator._FALLBACK_DREAM_SOUL
        assert draft.mode == "fallback"

    def test_dream_fallback_when_llm_raises(self, tenant_config, tmp_path, monkeypatch):
        """LLM exception → fallback constant used, mode recorded."""
        # Force KB hit count above MIN_KB_CHUNKS so we go down the AI path
        fake_ctx = "\n".join(f"[doc{i}]\nchunk {i}" for i in range(10))
        monkeypatch.setattr(
            soul_generator,
            "_gather_kb_context",
            lambda *a, **kw: (fake_ctx, 10),
        )

        def _raise(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr(soul_generator, "_generate_with_claude", _raise)

        draft = generate_soul(
            "dream", tenant_config, db_path=tmp_path / "kb.db", dry_run=False
        )
        assert draft.mode == "fallback"
        assert draft.content == soul_generator._FALLBACK_DREAM_SOUL
        assert any("LLM" in w or "fallback" in w.lower() for w in draft.warnings)


class TestGenerate5Roles:
    def test_generate_souls_covers_5_roles(self, tenant_config, tmp_path):
        """generate_souls returns an entry for every AGENT_ROLES member."""
        result = generate_souls(tenant_config, db_path=tmp_path / "kb.db", dry_run=True)
        assert set(result.souls.keys()) == set(AGENT_ROLES)
        assert len(result.souls) == 5


class TestGenerationMetaMode:
    def test_save_drafts_meta_records_per_role_mode(self, tenant_config, tmp_path):
        """_generation_meta.yaml should mark each role's mode (llm | fallback)."""
        result = generate_souls(tenant_config, db_path=tmp_path / "kb.db", dry_run=True)
        out_dir = tmp_path / "souls_out"
        save_drafts(result, output_dir=out_dir)

        meta_path = out_dir / "_generation_meta.yaml"
        assert meta_path.exists()

        import yaml
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        assert "roles" in meta
        for role, info in meta["roles"].items():
            assert "mode" in info, f"role {role} missing mode"
            assert info["mode"] in ("llm", "fallback")
