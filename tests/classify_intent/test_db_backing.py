"""Tests for ``autoservice.classify_intent_config`` (M3 T3S.3).

Contract: docs/contracts/m3/e3-triage.md §3.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from autoservice import classify_intent_config as cfg


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cfg.apply_schema(c)
    yield c
    c.close()


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────


def test_apply_schema_creates_table(conn):
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "classify_intent_config" in tables


def test_apply_schema_idempotent(conn):
    cfg.apply_schema(conn)
    cfg.apply_schema(conn)  # no raise


def test_model_tier_check_constraint(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO classify_intent_config "
            "(tenant_id, intent, keywords, threshold, model_tier, route_role, "
            "priority, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cfg.DEFAULT_TENANT_KEY, "x", "[]", 0.5, "ultra", "customer", "normal", "t"),
        )


def test_priority_check_constraint(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO classify_intent_config "
            "(tenant_id, intent, keywords, threshold, model_tier, route_role, "
            "priority, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cfg.DEFAULT_TENANT_KEY, "x", "[]", 0.5, "fast", "customer", "urgent", "t"),
        )


def test_primary_key_prevents_dup_per_tenant_intent(conn):
    cfg.upsert_intent(
        conn, tenant_id="t1", intent="complaint", keywords=["a"], route_role="customer"
    )
    # Second UPSERT — should update, not dup
    cfg.upsert_intent(
        conn, tenant_id="t1", intent="complaint", keywords=["b", "c"],
        route_role="customer",
    )
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM classify_intent_config "
        "WHERE tenant_id='t1' AND intent='complaint'"
    ).fetchone()
    assert rows["n"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Seed from YAML
# ──────────────────────────────────────────────────────────────────────────


def test_seed_from_yaml_populates_default_rows(conn):
    n = cfg.seed_defaults_from_yaml(conn)
    assert n > 0

    rows = conn.execute(
        "SELECT intent FROM classify_intent_config WHERE tenant_id = ?",
        (cfg.DEFAULT_TENANT_KEY,),
    ).fetchall()
    intent_names = {r["intent"] for r in rows}
    # Real YAML has 5 intents
    expected = {
        "product_inquiry", "complaint", "purchase_intent",
        "language_barrier", "general_question",
    }
    assert expected <= intent_names


def test_seed_is_idempotent(conn):
    n1 = cfg.seed_defaults_from_yaml(conn)
    n2 = cfg.seed_defaults_from_yaml(conn)
    assert n1 > 0
    assert n2 == 0, "second seed should insert nothing"


def test_seed_preserves_existing_admin_edits(conn):
    cfg.seed_defaults_from_yaml(conn)
    # Admin edits _default's complaint keyword via upsert
    cfg.upsert_intent(
        conn, tenant_id=cfg.DEFAULT_TENANT_KEY, intent="complaint",
        keywords=["EDITED"], model_tier="slow", route_role="customer",
    )
    # Re-seed should NOT overwrite
    cfg.seed_defaults_from_yaml(conn)

    c = cfg.get_intent(conn, cfg.DEFAULT_TENANT_KEY, "complaint")
    assert c.keywords == ["EDITED"]


def test_seed_raises_on_missing_yaml(conn, tmp_path):
    ghost = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError):
        cfg.seed_defaults_from_yaml(conn, yaml_path=ghost)


# ──────────────────────────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────────────────────────


def test_upsert_insert_then_update(conn):
    c1 = cfg.upsert_intent(
        conn, tenant_id="acme", intent="vip",
        keywords=["vip"], model_tier="slow", route_role="lead",
    )
    assert c1.keywords == ["vip"]

    c2 = cfg.upsert_intent(
        conn, tenant_id="acme", intent="vip",
        keywords=["vip", "enterprise"], model_tier="slow",
        route_role="lead", updated_by="admin@acme.com",
    )
    assert c2.keywords == ["vip", "enterprise"]
    assert c2.updated_by == "admin@acme.com"


def test_upsert_validates_model_tier():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cfg.apply_schema(c)
    with pytest.raises(ValueError, match="model_tier"):
        cfg.upsert_intent(
            c, tenant_id="t1", intent="x", keywords=[],
            model_tier="ultra", route_role="customer",
        )


def test_upsert_validates_priority():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cfg.apply_schema(c)
    with pytest.raises(ValueError, match="priority"):
        cfg.upsert_intent(
            c, tenant_id="t1", intent="x", keywords=[],
            model_tier="fast", route_role="customer", priority="critical",
        )


def test_get_intent_falls_back_to_default(conn):
    cfg.seed_defaults_from_yaml(conn)
    # Tenant without override → gets _default
    c = cfg.get_intent(conn, "some-tenant", "complaint")
    assert c is not None
    assert c.tenant_id == cfg.DEFAULT_TENANT_KEY


def test_get_intent_tenant_override_wins(conn):
    cfg.seed_defaults_from_yaml(conn)
    cfg.upsert_intent(
        conn, tenant_id="acme", intent="complaint",
        keywords=["acme-specific"], model_tier="slow", route_role="customer",
        priority="high",
    )
    c = cfg.get_intent(conn, "acme", "complaint")
    assert c.tenant_id == "acme"
    assert c.keywords == ["acme-specific"]


def test_get_intent_missing_returns_none(conn):
    assert cfg.get_intent(conn, "acme", "nonexistent") is None


def test_list_intents_union_of_tenant_and_default(conn):
    cfg.seed_defaults_from_yaml(conn)
    cfg.upsert_intent(
        conn, tenant_id="acme", intent="complaint",
        keywords=["override"], model_tier="slow", route_role="customer",
    )
    out = cfg.list_intents(conn, "acme")
    names = [c.intent for c in out]
    # Tenant's "complaint" plus _default's others
    assert "complaint" in names
    assert "product_inquiry" in names

    # Verify override wins: only ONE complaint row, and it's tenant-scoped
    complaints = [c for c in out if c.intent == "complaint"]
    assert len(complaints) == 1
    assert complaints[0].tenant_id == "acme"
    assert complaints[0].keywords == ["override"]


def test_delete_tenant_override(conn):
    cfg.seed_defaults_from_yaml(conn)
    cfg.upsert_intent(
        conn, tenant_id="acme", intent="complaint",
        keywords=["override"], model_tier="slow", route_role="customer",
    )
    assert cfg.get_intent(conn, "acme", "complaint").tenant_id == "acme"

    assert cfg.delete_tenant_override(conn, "acme", "complaint") is True
    # Now falls back to _default
    assert cfg.get_intent(conn, "acme", "complaint").tenant_id == cfg.DEFAULT_TENANT_KEY


def test_delete_tenant_override_default_protected(conn):
    cfg.seed_defaults_from_yaml(conn)
    with pytest.raises(ValueError, match="_default"):
        cfg.delete_tenant_override(conn, cfg.DEFAULT_TENANT_KEY, "complaint")


def test_delete_missing_row_returns_false(conn):
    assert cfg.delete_tenant_override(conn, "acme", "nonexistent") is False
