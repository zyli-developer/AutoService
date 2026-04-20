"""T1B.7 — unfreeze (rollback) tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §7.3.

``/api/onboard/unfreeze {tenant_id, reason}`` reverses the publish archive
step — restores `.autoservice/archived/<tid>_<ts>/` → `.autoservice/sandbox/<tid>/`
and resets config.status back to ``"sandbox"``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.publish.test_publish_gate_checks import _seed_sandbox, isolated_layout  # noqa: F401


class TestUnfreezeModule:
    def test_unfreeze_restores_sandbox(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_unfreeze"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        # Publish first so archive exists.
        result = pub_mod.publish(tid)
        assert result["status"] == "published"
        archived_dir = Path(result["archived_to"])
        assert archived_dir.exists()
        assert not (isolated_layout["sandbox"] / tid).exists()

        # Now unfreeze.
        out = pub_mod.unfreeze(tid, reason="misfire")
        assert out["tenant_id"] == tid
        assert out["status"] == "sandbox"
        assert out["reason"] == "misfire"

        restored = isolated_layout["sandbox"] / tid
        assert restored.exists(), "sandbox should have been restored"
        assert not archived_dir.exists(), "archive should have been moved"

        cfg = json.loads(
            (restored / "config.json").read_text(encoding="utf-8"),
        )
        assert cfg["status"] == "sandbox"

    def test_unfreeze_updates_publish_record(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_unfreeze_record"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        pub_mod.publish(tid)

        record = isolated_layout["published"] / f"{tid}.json"
        before = json.loads(record.read_text(encoding="utf-8"))
        assert before["status"] == "awaiting_fork"

        pub_mod.unfreeze(tid, reason="rollback for debug")

        after = json.loads(record.read_text(encoding="utf-8"))
        assert after["status"] == "unfrozen"
        assert "unfrozen_at" in after
        assert after["unfreeze_reason"] == "rollback for debug"

    def test_unfreeze_requires_reason(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_no_reason"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        pub_mod.publish(tid)

        with pytest.raises(ValueError):
            pub_mod.unfreeze(tid, reason="")
        with pytest.raises(ValueError):
            pub_mod.unfreeze(tid, reason="   ")

    def test_unfreeze_fails_when_no_archive(self, isolated_layout):
        from autoservice import publish as pub_mod

        with pytest.raises(FileNotFoundError):
            pub_mod.unfreeze("tenant_never_published", reason="oops")

    def test_unfreeze_fails_when_sandbox_already_exists(self, isolated_layout):
        """Safety: never overwrite a live sandbox via unfreeze."""
        from autoservice import publish as pub_mod

        tid = "tenant_conflict"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        pub_mod.publish(tid)

        # Re-create a "live" sandbox at the destination
        _seed_sandbox(isolated_layout["sandbox"], tid)

        with pytest.raises(FileExistsError):
            pub_mod.unfreeze(tid, reason="shouldn't clobber")


class TestUnfreezeEndpoint:
    def _client(self, monkeypatch, layout):
        from autoservice import publish as pub_mod
        monkeypatch.setattr(pub_mod, "SANDBOX_ROOT", layout["sandbox"])
        monkeypatch.setattr(pub_mod, "ARCHIVED_ROOT", layout["archived"])
        monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", layout["published"])

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from autoservice.api_routes import api_router

        app = FastAPI()
        app.include_router(api_router)
        return TestClient(app)

    def test_unfreeze_happy_path(self, isolated_layout, monkeypatch):
        from autoservice import publish as pub_mod

        tid = "tenant_uf_http"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        pub_mod.publish(tid)

        client = self._client(monkeypatch, isolated_layout)
        resp = client.post(
            "/api/onboard/unfreeze",
            json={"tenant_id": tid, "reason": "debug"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "sandbox"
        assert body["reason"] == "debug"

        # Sandbox on disk
        assert (isolated_layout["sandbox"] / tid / "config.json").exists()

    def test_unfreeze_missing_fields_400(self, isolated_layout, monkeypatch):
        client = self._client(monkeypatch, isolated_layout)

        resp = client.post("/api/onboard/unfreeze", json={"tenant_id": "x"})
        assert resp.status_code == 400

        resp = client.post(
            "/api/onboard/unfreeze", json={"reason": "no tid"},
        )
        assert resp.status_code == 400

    def test_unfreeze_missing_archive_404(self, isolated_layout, monkeypatch):
        client = self._client(monkeypatch, isolated_layout)
        resp = client.post(
            "/api/onboard/unfreeze",
            json={"tenant_id": "nope", "reason": "none"},
        )
        assert resp.status_code == 404
