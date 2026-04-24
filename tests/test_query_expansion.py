"""Unit tests for ``autoservice.query_expansion.expand_query``.

Pins the bilingual KB retrieval behavior landed 2026-04-23 to work
around the cinnox KB being ~99% English while customers type Chinese.
The expansion strategy is append-only (preserves original query) so
these tests also double as a spec for what the function MUST / MUST
NOT mutate.
"""
from __future__ import annotations

import pytest

from autoservice.query_expansion import expand_query


class TestCJKCountryExpansion:
    """Chinese country names append the English xlsx-canonical form."""

    def test_full_country_name(self):
        out = expand_query("英国的价格")
        assert out.startswith("英国的价格 ")
        assert "United Kingdom" in out

    def test_single_char_abbreviations(self):
        """Short-form CSR messages like "英 法 德" — the screenshot case."""
        out = expand_query("英 法 德")
        # Original preserved
        assert "英 法 德" in out
        # All three countries appended
        assert "United Kingdom" in out
        assert "France" in out
        assert "Germany" in out

    def test_longest_wins_over_shorter(self):
        """'英国' must not double-trigger '英' — expansion iterates
        longest-first and the ``seen`` set deduplicates per-token. So
        "United Kingdom" + "United States" in the same query dedups
        "United" (appears once in additions) but keeps both "Kingdom"
        and "States" as separate OR candidates — which is what FTS5
        needs. This is an optimization that keeps the query compact
        without losing recall."""
        out = expand_query("英国 美国")
        # Token-level dedup: "United" added once even though both map
        # "United Kingdom" and "United States" contain it.
        appended = out[len("英国 美国 "):]  # expansion segment
        tokens = appended.split()
        assert tokens.count("United") == 1, f"United not deduped: {tokens!r}"
        # Both country-specific discriminators preserved.
        assert "Kingdom" in tokens
        assert "States" in tokens


class TestChineseBusinessTerms:
    """Chinese pricing / product terms expand to English synonyms."""

    def test_price_term(self):
        out = expand_query("价格在哪")
        assert "价格在哪" in out
        # Multiple English synonyms for ranking headroom
        for token in ("price", "pricing", "cost", "fee"):
            assert token in out

    def test_service_term(self):
        out = expand_query("你们提供什么服务")
        assert "customer" in out or "service" in out or "feature" in out

    def test_plan_term(self):
        out = expand_query("你们的套餐")
        assert "plan" in out or "subscription" in out

    def test_provisioning_term(self):
        out = expand_query("DID 怎么开通")
        assert "provisioning" in out or "activation" in out
        # DID acronym also expands
        assert "Direct" in out and "Dialing" in out


class TestEnglishAcronymAndAlias:
    """English-side coverage — parity with the parallel autoservice repo."""

    def test_us_alias(self):
        out = expand_query("us pricing")
        assert "United States" in out

    def test_uk_alias(self):
        out = expand_query("uk DID")
        assert "United Kingdom" in out

    def test_ivr_acronym(self):
        out = expand_query("IVR pricing")
        assert "Interactive Voice Response" in out

    def test_word_boundary_no_false_positive(self):
        """'did' in 'candidate' must NOT trigger DID expansion (word
        boundary regex). Also guards against 'us' in 'campus'."""
        out = expand_query("the candidate on campus")
        assert "Direct Inward Dialing" not in out
        assert "United States" not in out


class TestIdempotenceAndEdgeCases:

    def test_already_english_no_op(self):
        """Pure English canonical query returns unchanged (no matches)."""
        q = "United Kingdom rates"
        out = expand_query(q)
        # No CJK or alias hits → returns original unchanged
        assert out == q

    def test_empty_query(self):
        assert expand_query("") == ""

    def test_whitespace_only(self):
        assert expand_query("   ") in ("   ", "")

    def test_none_rejected_gracefully(self):
        # Not expected in practice (caller ensures str), but shouldn't crash
        out = expand_query(None)  # type: ignore[arg-type]
        assert out == ""

    def test_original_always_preserved(self):
        """Core contract: expansion is *additive*, never rewrites the
        customer's original phrasing. Chinese-to-Chinese FTS matches
        must still work (the demo Chinese chunks rely on it)."""
        cases = [
            "英国价格",
            "DID 怎么开通",
            "us pricing",
            "whatever random query",
        ]
        for q in cases:
            out = expand_query(q)
            assert out.startswith(q), f"expansion must prepend original: {q!r} -> {out!r}"


class TestScreenshotScenarios:
    """Real customer messages from the 2026-04-23 test screenshots that
    triggered the "escalate to sales" fallback because FTS couldn't
    bridge the language gap. Each should now produce an expansion with
    at least one English country / term that the cinnox English rate
    cards contain."""

    def test_country_shorthand(self):
        """'英 法 德' — customer shorthand for UK/France/Germany pricing."""
        out = expand_query("英 法 德")
        assert "United Kingdom" in out
        assert "France" in out
        assert "Germany" in out

    def test_where_is_price(self):
        """'价格在哪' — maps to price/pricing/cost/fee English synonyms."""
        out = expand_query("价格在哪")
        assert any(w in out for w in ("price", "pricing", "cost", "fee"))

    def test_what_services_offered(self):
        """'你们提供哪些服务' — should get something English for BM25."""
        out = expand_query("你们提供哪些服务")
        # At least customer/service/feature synonym appends
        assert len(out) > len("你们提供哪些服务"), \
            f"expected expansion to add English terms: {out!r}"
