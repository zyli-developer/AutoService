"""Tests for T3S.4 — classify_intent CRUD endpoints + hot-reload (M3).

Contract: docs/contracts/m3/e3-triage.md §3.4.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import (
    api_routes,
    auth,
    classify_intent_config as cic,
    operator_routes,
    operators,
)


@pytest.fixture()
def db_conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    cic.apply_schema(c)
    yield c
    c.close()


@pytest.fixture()
def app(db_conn):
    operator_routes._reset_op_db_for_tests(db_conn)
    api_routes._reset_auth_db_for_tests(db_conn)
    a = FastAPI()
    a.include_router(api_routes.api_router)
    yield a
    operator_routes._reset_op_db_for_tests(None)
    api_routes._reset_auth_db_for_tests(None)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def admin_cookie(db_conn):
    return auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")


# ──────────────────────────────────────────────────────────────────────────
# List
# ──────────────────────────────────────────────────────────────────────────


def test_list_auto_seeds_defaults_if_yaml_present(client, db_conn, admin_cookie):
    r = client.get(
        "/api/admin/acme/classify-intent",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "acme"
    # Real YAML has 5 intents
    intent_names = {i["intent"] for i in data["intents"]}
    assert {
        "product_inquiry", "complaint", "purchase_intent",
        "language_barrier", "general_question",
    } <= intent_names


def test_list_shows_tenant_override_beating_default(client, db_conn, admin_cookie):
    # Seed + override
    cic.seed_defaults_from_yaml(db_conn)
    cic.upsert_intent(
        db_conn, tenant_id="acme", intent="complaint",
        keywords=["ACME-CUSTOM"], model_tier="slow",
        route_role="customer", priority="high",
    )
    r = client.get(
        "/api/admin/acme/classify-intent",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    complaints = [i for i in r.json()["intents"] if i["intent"] == "complaint"]
    assert len(complaints) == 1
    assert complaints[0]["tenant_id"] == "acme"  # overridden
    assert complaints[0]["keywords"] == ["ACME-CUSTOM"]


def test_list_requires_auth(client):
    r = client.get("/api/admin/acme/classify-intent")
    assert r.status_code == 401


def test_list_cross_tenant_denied(client, db_conn, admin_cookie):
    r = client.get(
        "/api/admin/other-tenant/classify-intent",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Upsert
# ──────────────────────────────────────────────────────────────────────────


def test_upsert_creates_new_intent(client, db_conn, admin_cookie):
    r = client.put(
        "/api/admin/acme/classify-intent/vip_flow",
        json={
            "keywords": ["vip", "enterprise"],
            "threshold": 0.7,
            "model_tier": "slow",
            "route_role": "lead",
            "priority": "high",
        },
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "vip_flow"
    assert data["keywords"] == ["vip", "enterprise"]
    assert data["threshold"] == 0.7
    assert data["updated_by"] == "admin@acme.com"


def test_upsert_updates_existing(client, db_conn, admin_cookie):
    cic.seed_defaults_from_yaml(db_conn)
    r = client.put(
        "/api/admin/acme/classify-intent/complaint",
        json={
            "keywords": ["updated"],
            "model_tier": "slow",
            "route_role": "customer",
        },
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200
    assert r.json()["keywords"] == ["updated"]


def test_upsert_rejects_non_list_keywords(client, admin_cookie):
    r = client.put(
        "/api/admin/acme/classify-intent/x",
        json={"keywords": "not-a-list"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 422


def test_upsert_rejects_non_string_keyword_items(client, admin_cookie):
    r = client.put(
        "/api/admin/acme/classify-intent/x",
        json={"keywords": ["ok", 123, "also-ok"]},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 422


def test_upsert_rejects_bad_model_tier(client, admin_cookie):
    r = client.put(
        "/api/admin/acme/classify-intent/x",
        json={"keywords": ["a"], "model_tier": "ultra"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 422


def test_upsert_cross_tenant_denied(client, db_conn, admin_cookie):
    r = client.put(
        "/api/admin/other-tenant/classify-intent/x",
        json={"keywords": ["a"]},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Delete (removes tenant override, falls back to _default)
# ──────────────────────────────────────────────────────────────────────────


def test_delete_removes_tenant_override(client, db_conn, admin_cookie):
    cic.seed_defaults_from_yaml(db_conn)
    cic.upsert_intent(
        db_conn, tenant_id="acme", intent="complaint",
        keywords=["override"], model_tier="slow", route_role="customer",
    )
    # Sanity: override in place
    assert cic.get_intent(db_conn, "acme", "complaint").tenant_id == "acme"

    r = client.delete(
        "/api/admin/acme/classify-intent/complaint",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 204

    # Now falls back to _default
    assert cic.get_intent(db_conn, "acme", "complaint").tenant_id == cic.DEFAULT_TENANT_KEY


def test_delete_nonexistent_override_returns_404(client, db_conn, admin_cookie):
    r = client.delete(
        "/api/admin/acme/classify-intent/nonexistent",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 404


def test_delete_default_tenant_rejected(client, db_conn, admin_cookie):
    """Can't delete _default rows — protective guard."""
    cic.seed_defaults_from_yaml(db_conn)
    # Pretend admin is scoped to _default (edge case; normally disallowed but
    # tier-0 master admin can be scoped here)
    from autoservice import auth as _auth
    sid = _auth.create_session(db_conn, "master@example.com", tenant_id=None)

    r = client.delete(
        "/api/admin/_default/classify-intent/complaint",
        cookies={_auth.AUTH_SESSION_COOKIE_NAME: sid},
    )
    # tier-0 admin can access any tenant; delete protection raises ValueError → 422
    assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Hot-reload via clear_tenant_cache
# ──────────────────────────────────────────────────────────────────────────


def test_upsert_triggers_clear_tenant_cache(client, db_conn, admin_cookie, monkeypatch):
    """Patch the route's _invalidate_classifier_cache helper directly —
    robust against module-import ordering."""
    calls: list[str] = []

    def spy(tenant_id: str) -> None:
        calls.append(tenant_id)

    monkeypatch.setattr(operator_routes, "_invalidate_classifier_cache", spy)

    client.put(
        "/api/admin/acme/classify-intent/test_intent",
        json={"keywords": ["a"]},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert calls == ["acme"]


def test_delete_triggers_clear_tenant_cache(client, db_conn, admin_cookie, monkeypatch):
    calls: list[str] = []

    def spy(tenant_id: str) -> None:
        calls.append(tenant_id)

    monkeypatch.setattr(operator_routes, "_invalidate_classifier_cache", spy)

    cic.seed_defaults_from_yaml(db_conn)
    cic.upsert_intent(
        db_conn, tenant_id="acme", intent="complaint",
        keywords=["override"], model_tier="slow", route_role="customer",
    )
    calls.clear()  # reset after seed

    client.delete(
        "/api/admin/acme/classify-intent/complaint",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert "acme" in calls


def test_invalidate_classifier_cache_is_signature_tolerant(monkeypatch):
    """Upstream FastClassifier.clear_tenant_cache takes NO args; our caller
    passes tenant_id.  The helper must fall back to no-arg invocation."""
    call_count = {"with_arg": 0, "no_arg": 0}

    class _RealStyleClassifier:
        @classmethod
        def clear_tenant_cache(cls) -> None:  # matches real signature — no tid arg
            call_count["no_arg"] += 1

    import sys, types
    mod = types.ModuleType("autoservice.model_router")
    mod.FastClassifier = _RealStyleClassifier
    import autoservice
    monkeypatch.setattr(autoservice, "model_router", mod, raising=False)
    monkeypatch.setitem(sys.modules, "autoservice.model_router", mod)

    operator_routes._invalidate_classifier_cache("acme")
    # Fell back from 1-arg to no-arg (TypeError caught)
    assert call_count["no_arg"] == 1


def test_upsert_survives_missing_model_router(client, db_conn, admin_cookie, monkeypatch):
    """No model_router module → upsert still succeeds; cache clear is soft."""
    import sys
    # Ensure no model_router
    monkeypatch.setitem(sys.modules, "autoservice.model_router", None)

    r = client.put(
        "/api/admin/acme/classify-intent/new_one",
        json={"keywords": ["a"]},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    # Soft-dep: missing module does not 500 the request
    assert r.status_code in (200, 422)  # 200 is expected; 422 only on validation
    assert r.status_code == 200
