"""Tests for T6D.5 — /api/sla/summary period parameter.

TC-01 ~ TC-05: backend API period parameter parsing and window mapping.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI

from autoservice.api_routes import api_router, _get_sla
from autoservice.sla_aggregator import MetricType, WindowSize


@pytest.fixture()
def client():
    """Create a test client with api_router mounted and seed SLA data."""
    app = FastAPI()
    app.include_router(api_router)

    # Seed data into all 3 windows so counts differ per window
    agg = _get_sla()
    import time
    now = time.time()

    # Record a value — it goes to all 3 ring buffers
    agg.record(MetricType.CSAT_SCORE, 4.5, timestamp=now)
    agg.record(MetricType.FIRST_REPLY_MS, 120.0, timestamp=now)

    return TestClient(app)


class TestSlaSummaryPeriod:
    def test_tc01_no_period_defaults_to_5m(self, client: TestClient):
        """TC-01: No period param → default 5m window, 8 metrics returned (M3 T2S.4 added pool_wait_ms)."""
        resp = client.get("/api/sla/summary")
        assert resp.status_code == 200
        data = resp.json()
        # 8 metrics as of M3 T2S.4 (pool_wait_ms added); was 7 in M2
        assert len(data) == 8
        # Check structure of one metric
        csat = data["csat_score"]
        assert set(csat.keys()) == {"p50", "p95", "count", "min", "max"}

    def test_tc02_period_1h(self, client: TestClient):
        """TC-02: period=1h → returns ONE_HOUR window data."""
        resp = client.get("/api/sla/summary?period=1h")
        assert resp.status_code == 200
        data = resp.json()
        # 8 metrics as of M3 T2S.4 (pool_wait_ms added); was 7 in M2
        assert len(data) == 8
        assert data["csat_score"]["count"] >= 1

    def test_tc03_period_24h(self, client: TestClient):
        """TC-03: period=24h → returns TWENTY_FOUR_HOUR window data."""
        resp = client.get("/api/sla/summary?period=24h")
        assert resp.status_code == 200
        data = resp.json()
        # 8 metrics as of M3 T2S.4 (pool_wait_ms added); was 7 in M2
        assert len(data) == 8
        assert data["first_reply_ms"]["count"] >= 1

    def test_tc04_invalid_period_returns_400(self, client: TestClient):
        """TC-04: period=invalid → HTTP 400."""
        resp = client.get("/api/sla/summary?period=invalid")
        assert resp.status_code == 400

    def test_tc05_period_5m_explicit(self, client: TestClient):
        """TC-05: period=5m explicit → same as default."""
        resp_default = client.get("/api/sla/summary")
        resp_explicit = client.get("/api/sla/summary?period=5m")
        assert resp_explicit.status_code == 200
        assert resp_default.json() == resp_explicit.json()
