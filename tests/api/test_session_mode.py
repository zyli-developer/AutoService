"""Tests for T1B.5 — GET /api/session/mode endpoint.

M1 contract: master-only deployment returns {mode: "master", role: "platform_admin"}.
Tenant-mode response (with tenant_id) is M2 scope and must NOT appear here.

See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
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


def test_session_mode_returns_master_in_m1(client: TestClient) -> None:
    """M1: /api/session/mode returns master/platform_admin, no tenant_id."""
    resp = client.get("/api/session/mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "master"
    assert body["role"] == "platform_admin"
    assert "tenant_id" not in body  # tenant-mode only (M2)


def test_session_mode_response_shape(client: TestClient) -> None:
    """Response keys are exactly {mode, role} in M1 — nothing else leaks."""
    resp = client.get("/api/session/mode")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"mode", "role"}
