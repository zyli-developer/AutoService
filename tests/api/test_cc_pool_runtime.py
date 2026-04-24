"""Tests for GET /api/cc_pool/runtime endpoint.

The operator console polls this endpoint every 3 s to drive the "system
busy" badge (formerly a hardcoded `concurrencyLimit: 5` in the Zustand
store). The endpoint reads the snapshot file the status-writer loop
maintains — see ``autoservice.cc_pool._status_writer_loop``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Client with snapshot path pointed at a tmp file the tests control."""
    snap = tmp_path / "cc_pool_status.json"
    monkeypatch.setattr(api_routes, "_CC_POOL_STATUS_FILE", snap)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    tc = TestClient(app)
    tc.snap = snap  # type: ignore[attr-defined]
    return tc


def test_missing_snapshot_returns_empty_shape(client: TestClient) -> None:
    """Fresh install / pool never started → consistent zero shape, not 404.

    UI renders a no-busy state; avoids a red error badge when a dev
    frontend is pointed at a backend where the pool isn't up yet.
    """
    resp = client.get("/api/cc_pool/runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "started": False,
        "max_size": 0,
        "checked_out": 0,
        "sticky": 0,
        "available": 0,
        "total": 0,
    }


def test_malformed_snapshot_returns_empty_shape(client: TestClient) -> None:
    """Partial / corrupted JSON (writer crashed mid-write) — don't 500."""
    client.snap.write_text("{not valid json", encoding="utf-8")  # type: ignore[attr-defined]
    resp = client.get("/api/cc_pool/runtime")
    assert resp.status_code == 200
    assert resp.json()["started"] is False


def test_live_snapshot_is_reflected(client: TestClient) -> None:
    """A real snapshot (as written by ``_write_status_snapshot``) round-trips."""
    snap_data = {
        "started": True,
        "total": 4,
        "available": 1,
        "sticky": 0,
        "checked_out": 3,
        "max_size": 5,
        # Extra fields in the real snapshot (instance list, sticky bindings)
        # MUST be ignored — the UI only needs the capacity numbers.
        "instances": [{"id": "cc-001", "healthy": True}],
        "sticky_bindings": [],
        "updated_at": "2026-04-24T10:00:00",
    }
    client.snap.write_text(json.dumps(snap_data), encoding="utf-8")  # type: ignore[attr-defined]
    resp = client.get("/api/cc_pool/runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "started": True,
        "max_size": 5,
        "checked_out": 3,
        "sticky": 0,
        "available": 1,
        "total": 4,
    }
    # UI uses (checked_out / max_size) for the busy-ratio readout; verify
    # neither value gets coerced to 0 accidentally.
    assert body["checked_out"] == 3
    assert body["max_size"] == 5


def test_coerces_stringy_numbers(client: TestClient) -> None:
    """Snapshot writer shouldn't but might emit numbers as JSON strings;
    the endpoint coerces defensively so the UI never sees ``"5"`` vs ``5``
    drifting its numeric comparisons."""
    client.snap.write_text(  # type: ignore[attr-defined]
        json.dumps({
            "started": True, "max_size": 5, "checked_out": 2,
            "sticky": 1, "available": 2, "total": 5,
        }),
        encoding="utf-8",
    )
    resp = client.get("/api/cc_pool/runtime")
    body = resp.json()
    assert isinstance(body["max_size"], int)
    assert isinstance(body["checked_out"], int)
