"""Tests for T1B.3 — /api/rehearsal/generate persistence + /api/rehearsal/review.

Fixes bug #4: Step 2 virtual rehearsal dialogs were NEVER persisted.
After generate, the resulting rehearsal.json MUST exist on disk so that
frontend reloads can restore review state.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice.api_routes import api_router


TENANT_ID = "t1b3_tenant"
SANDBOX_ROOT = Path(".autoservice/sandbox")


@pytest.fixture()
def client(monkeypatch):
    """Create a test client and isolate sandbox state for the tenant."""
    # Force the demo-fallback path in /rehearsal/generate by ensuring the
    # LLM client returns None (the endpoint treats None as "unavailable"
    # and falls back to the 12 hardcoded demo dialogs).
    monkeypatch.setattr(
        "autoservice.api_routes._get_llm_client",
        lambda: None,
    )

    tenant_dir = SANDBOX_ROOT / TENANT_ID
    if tenant_dir.exists():
        shutil.rmtree(tenant_dir)

    app = FastAPI()
    app.include_router(api_router)
    yield TestClient(app)

    # Cleanup after test
    if tenant_dir.exists():
        shutil.rmtree(tenant_dir)


def _rehearsal_path(tenant_id: str = TENANT_ID) -> Path:
    return SANDBOX_ROOT / tenant_id / "rehearsal.json"


class TestRehearsalGeneratePersists:
    def test_tc01_generate_writes_rehearsal_json(self, client: TestClient):
        """TC-01: After /rehearsal/generate, rehearsal.json exists on disk."""
        resp = client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert "dialogs" in data
        assert len(data["dialogs"]) >= 10

        path = _rehearsal_path()
        assert path.exists(), f"Expected rehearsal.json at {path}"

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert "generated_at" in on_disk
        assert "demo_mode" in on_disk
        assert "dialogs" in on_disk
        assert len(on_disk["dialogs"]) == len(data["dialogs"])

    def test_tc02_all_dialogs_initial_status_pending(self, client: TestClient):
        """TC-02: Every persisted dialog has review_status='pending' initially."""
        resp = client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")
        assert resp.status_code == 200

        on_disk = json.loads(_rehearsal_path().read_text(encoding="utf-8"))
        for d in on_disk["dialogs"]:
            assert d["review_status"] == "pending"
            assert d.get("review_note", "") == ""
            assert d.get("reviewed_at") is None


class TestRehearsalReviewEndpoint:
    def test_tc03_review_updates_dialog(self, client: TestClient):
        """TC-03: /rehearsal/review sets review_status on the specific dialog."""
        gen = client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")
        assert gen.status_code == 200
        dialogs = gen.json()["dialogs"]
        target_id = dialogs[2]["id"]

        resp = client.post(
            "/api/rehearsal/review",
            json={
                "tenant_id": TENANT_ID,
                "dialog_id": target_id,
                "review_status": "approved",
                "review_note": "Looks good",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["dialog_id"] == target_id
        assert body["review_status"] == "approved"

        # Verify on disk
        on_disk = json.loads(_rehearsal_path().read_text(encoding="utf-8"))
        target = next(d for d in on_disk["dialogs"] if d["id"] == target_id)
        assert target["review_status"] == "approved"
        assert target["review_note"] == "Looks good"
        assert target["reviewed_at"] is not None

        # Other dialogs untouched
        for d in on_disk["dialogs"]:
            if d["id"] != target_id:
                assert d["review_status"] == "pending"

    def test_tc04_review_flagged_status(self, client: TestClient):
        """TC-04: 'flagged' status is accepted."""
        gen = client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")
        dialogs = gen.json()["dialogs"]
        target_id = dialogs[0]["id"]

        resp = client.post(
            "/api/rehearsal/review",
            json={
                "tenant_id": TENANT_ID,
                "dialog_id": target_id,
                "review_status": "flagged",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "flagged"

    def test_tc05_review_tenant_not_found(self, client: TestClient):
        """TC-05: 404 when tenant_id has no rehearsal.json yet."""
        resp = client.post(
            "/api/rehearsal/review",
            json={
                "tenant_id": "does_not_exist_tenant",
                "dialog_id": "dialog-000",
                "review_status": "approved",
            },
        )
        assert resp.status_code == 404

    def test_tc06_review_dialog_not_found(self, client: TestClient):
        """TC-06: 404 when dialog_id doesn't match any persisted dialog."""
        client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")

        resp = client.post(
            "/api/rehearsal/review",
            json={
                "tenant_id": TENANT_ID,
                "dialog_id": "no-such-dialog-id",
                "review_status": "approved",
            },
        )
        assert resp.status_code == 404

    def test_tc07_review_invalid_status(self, client: TestClient):
        """TC-07: 400 when review_status is not one of {pending, approved, flagged}."""
        gen = client.post(f"/api/rehearsal/generate?tenant_id={TENANT_ID}")
        target_id = gen.json()["dialogs"][0]["id"]

        resp = client.post(
            "/api/rehearsal/review",
            json={
                "tenant_id": TENANT_ID,
                "dialog_id": target_id,
                "review_status": "bogus_value",
            },
        )
        assert resp.status_code == 400
