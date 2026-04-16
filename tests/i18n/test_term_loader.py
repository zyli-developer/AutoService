from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from autoservice.i18n.term_loader import TermLoader

TERMS_DIR = str(Path(__file__).resolve().parent.parent.parent / "autoservice" / "i18n" / "terms")


class TestLoadTerms:
    def test_load_en_returns_20_plus_terms(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        terms = loader.load_terms("en")
        assert len(terms) >= 20

    def test_load_zh_cn_has_translations(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        terms = loader.load_terms("zh-CN")
        assert len(terms) >= 20
        for t in terms:
            assert "zh-CN" in t, f"Term {t.get('id')} missing zh-CN translation"

    def test_load_nonexistent_language(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        terms = loader.load_terms("xx-FAKE")
        assert terms == []


class TestListLanguages:
    def test_list_returns_22_languages(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        langs = loader.list_languages()
        assert len(langs) == 22
        # Spot-check a few
        assert "en" in langs
        assert "zh-CN" in langs
        assert "ar" in langs
        assert "ja" in langs


class TestRenderPromptPrefix:
    def test_render_returns_table(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        prefix = loader.render_prompt_prefix("zh-CN")
        assert prefix.startswith("术语表 (zh-CN):")
        assert "| 英文 | 翻译 |" in prefix
        assert "|------|------|" in prefix
        # Should contain at least one data row
        lines = prefix.strip().split("\n")
        data_rows = [l for l in lines if l.startswith("|") and "英文" not in l and "---" not in l]
        assert len(data_rows) >= 1

    def test_render_truncates_at_max_tokens(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        # Very small max_tokens should truncate heavily
        prefix = loader.render_prompt_prefix("zh-CN", max_tokens=50)
        # 50 tokens * 4 chars = 200 chars max
        assert len(prefix) <= 250  # some slack for final newline

    def test_render_nonexistent_lang_returns_empty(self):
        loader = TermLoader(terms_dir=TERMS_DIR)
        prefix = loader.render_prompt_prefix("xx-FAKE")
        assert prefix == ""


class TestTenantOverride:
    def test_override_replaces_matching_id(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(
                {
                    "overrides": [
                        {
                            "id": "greeting",
                            "zh-CN": "欢迎光临XX商城！",
                        }
                    ]
                },
                f,
                allow_unicode=True,
            )
            tenant_path = f.name

        try:
            loader = TermLoader(terms_dir=TERMS_DIR, tenant_terms_path=tenant_path)
            terms = loader.load_terms("zh-CN")
            greeting = next(t for t in terms if t["id"] == "greeting")
            assert greeting["zh-CN"] == "欢迎光临XX商城！"
        finally:
            os.unlink(tenant_path)

    def test_override_adds_new_ids(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(
                {
                    "overrides": [
                        {
                            "id": "custom_product_name",
                            "en": "SuperWidget Pro",
                            "zh-CN": "超级小部件专业版",
                        }
                    ]
                },
                f,
                allow_unicode=True,
            )
            tenant_path = f.name

        try:
            loader = TermLoader(terms_dir=TERMS_DIR, tenant_terms_path=tenant_path)
            terms = loader.load_terms("zh-CN")
            ids = [t["id"] for t in terms]
            assert "custom_product_name" in ids
            custom = next(t for t in terms if t["id"] == "custom_product_name")
            assert custom["zh-CN"] == "超级小部件专业版"
        finally:
            os.unlink(tenant_path)

    def test_no_tenant_file_graceful_fallback(self):
        loader = TermLoader(
            terms_dir=TERMS_DIR,
            tenant_terms_path="/nonexistent/path/terms.yaml",
        )
        terms = loader.load_terms("zh-CN")
        assert len(terms) >= 20
