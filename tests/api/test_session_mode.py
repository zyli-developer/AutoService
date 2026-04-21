"""Tests for GET /api/session/mode endpoint.

Originally added for T1B.5 with the M1 master-only shape
(``{mode, role}``). T5B.6 extended the endpoint to the M2 AuthGate shape
per spec §4.5: ``{mode, tenant_id, authenticated, authenticated_as,
tier, brand_name}``.  The ``role`` field is gone — ``tier`` + the
session cookie convey the same information now.

See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5
(AuthGate) and §5.3 (require_tenant_access / tier derivation).
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI

from autoservice.api_routes import api_router


@pytest.fixture()
def client() -> TestClient:
    """Create a test client with api_router mounted."""
    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app)


def test_session_mode_anon_defaults_to_master_shape(client: TestClient) -> None:
    """Anonymous caller (no cookie, no config.local.yaml) → master defaults.

    The endpoint MUST degrade gracefully when config.local.yaml is absent
    (bootstrap fallback) — it is routinely called on the login page before
    any state exists.
    """
    resp = client.get("/api/session/mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "master"
    assert body["authenticated"] is False
    assert body["authenticated_as"] is None
    assert body["tier"] is None
    assert body["brand_name"] == "AutoService"


def test_session_mode_response_has_m2_shape(client: TestClient) -> None:
    """Response keys match the T5B.6 / spec §4.5 AuthGate contract."""
    resp = client.get("/api/session/mode")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {
        "mode",
        "tenant_id",
        "authenticated",
        "authenticated_as",
        "tier",
        "brand_name",
    }
