"""Unit tests for ``autoservice.country_registry`` (M3 T2S.6).

Contract: docs/contracts/m3/e4-compliance.md §1.
"""
from __future__ import annotations

import pytest

from autoservice import country_registry as cr


# ──────────────────────────────────────────────────────────────────────────
# Registry shape
# ──────────────────────────────────────────────────────────────────────────


def test_iso_set_has_expected_cardinality():
    # ISO 3166-1 alpha-2 is ~249 codes as of 2025. Allow some drift.
    assert 240 <= len(cr.ISO_3166_1_ALPHA_2) <= 260


def test_accepted_set_includes_iso_plus_markers():
    assert cr.GLOBAL_TAG in cr.ACCEPTED_COUNTRY_CODES
    assert cr.EU_ALIAS in cr.ACCEPTED_COUNTRY_CODES
    assert cr.ISO_3166_1_ALPHA_2 <= cr.ACCEPTED_COUNTRY_CODES


def test_common_countries_are_valid():
    for code in ["US", "CN", "JP", "SG", "AU", "GB", "DE", "FR", "BR", "IN"]:
        assert cr.is_valid(code), f"{code} should be valid ISO alpha-2"


def test_eu_alias_is_valid_for_tenant_config():
    assert cr.is_valid("EU")


def test_global_tag_is_valid():
    assert cr.is_valid("*")


# ──────────────────────────────────────────────────────────────────────────
# is_valid
# ──────────────────────────────────────────────────────────────────────────


def test_unknown_code_rejected():
    assert not cr.is_valid("ZZ")
    assert not cr.is_valid("XX")
    assert not cr.is_valid("U1")


def test_case_sensitive_by_design():
    """Lowercase codes are NOT accepted — callers must normalize first."""
    assert not cr.is_valid("us")
    assert not cr.is_valid("Us")
    assert cr.is_valid("US")


def test_empty_string_rejected():
    assert not cr.is_valid("")


def test_long_code_rejected():
    assert not cr.is_valid("USA")  # alpha-3 not accepted


def test_normalize_uppercases_and_trims():
    assert cr.normalize("us") == "US"
    assert cr.normalize("  Jp  ") == "JP"
    assert cr.normalize("*") == "*"


# ──────────────────────────────────────────────────────────────────────────
# validate_list
# ──────────────────────────────────────────────────────────────────────────


def test_validate_list_all_valid_returns_empty():
    assert cr.validate_list(["US", "JP", "EU"]) == []


def test_validate_list_returns_invalid_codes():
    invalid = cr.validate_list(["US", "ZZ", "JP", "XX"])
    assert invalid == ["ZZ", "XX"]


def test_validate_list_empty_input_returns_empty():
    """Empty list → empty result (no codes to invalidate; policy at scan layer)."""
    assert cr.validate_list([]) == []


def test_validate_list_preserves_input_order():
    assert cr.validate_list(["XX", "US", "ZZ"]) == ["XX", "ZZ"]


def test_validate_list_rejects_non_list_type():
    with pytest.raises(TypeError, match="expected list"):
        cr.validate_list("US")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        cr.validate_list({"US": True})  # type: ignore[arg-type]


def test_validate_list_rejects_non_string_items():
    with pytest.raises(TypeError, match="only strings"):
        cr.validate_list(["US", 123, "JP"])  # type: ignore[list-item]


# ──────────────────────────────────────────────────────────────────────────
# assert_valid_list
# ──────────────────────────────────────────────────────────────────────────


def test_assert_valid_list_passes_when_all_valid():
    cr.assert_valid_list(["US", "JP", "SG", "EU", "*"])  # no raise


def test_assert_valid_list_raises_on_bad_codes():
    with pytest.raises(ValueError, match=r"ZZ"):
        cr.assert_valid_list(["US", "ZZ"])


def test_assert_valid_list_error_mentions_registry_hint():
    with pytest.raises(ValueError, match="ISO 3166-1 alpha-2"):
        cr.assert_valid_list(["XX"])


def test_assert_valid_list_empty_input_passes():
    """Empty list passes validation — fail-closed policy lives at scan layer."""
    cr.assert_valid_list([])
