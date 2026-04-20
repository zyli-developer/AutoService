"""T1B.2 — verify `/api/onboard/activate` is an idempotent merge.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §2.2 / §3.2

Goals:
  1. `/activate` reads the Step-0 skeleton `config.json`, merges channels +
     compliance + soul + dream defaults, and writes it back.
  2. A 2nd call to `/activate` doesn't clobber any data (all Step-0 fields +
     any user edits survive).
  3. Manually injected fields (e.g., `custom_field`) survive a 2nd `/activate`.
  4. Returned URLs are in the new path form `/t/<tenant_id>/...` (chat,
     operator, admin).
  5. The `channels` array passed in is persisted.

These tests live next to test_upload_persists_souls_and_kb.py and reuse the
same monkeypatch strategy (SANDBOX_ROOT → tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    from autoservice.onboarding import onboard_router

    app = FastAPI()
    app.include_router(onboard_router)
    return app


@pytest.fixture
def isolated_sandbox(tmp_path, monkeypatch):
    """Redirect SANDBOX_ROOT to tmp_path and clear any URL env overrides."""
    from autoservice import onboarding as onboarding_mod

    fake_sandbox_root = tmp_path / ".autoservice" / "sandbox"
    monkeypatch.setattr(onboarding_mod, "SANDBOX_ROOT", fake_sandbox_root)

    # Deterministic URL form — defaults from onboarding.py
    monkeypatch.delenv("WEB_SCHEME", raising=False)
    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.delenv("DEMO_PORT", raising=False)

    return tmp_path


def _write_skeleton(sandbox_root: Path, tenant_id: str, **extra) -> Path:
    """Simulate what Step 0 `/upload` writes — a minimal config.json skeleton."""
    tdir = sandbox_root / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "tenant_id": tenant_id,
        "brand_name": "acmecorp",
        "industry": "ecommerce",
        "status": "sandbox",
        "created_at": "2026-04-20T10:00:00+00:00",
    }
    skeleton.update(extra)
    cfg_path = tdir / "config.json"
    cfg_path.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")
    return cfg_path


# ---------------------------------------------------------------------------
# Unit-level: build_urls helper produces path form
# ---------------------------------------------------------------------------

class TestBuildUrls:
    def test_returns_path_based_urls(self, monkeypatch):
        from autoservice.onboarding import build_urls

        monkeypatch.delenv("WEB_SCHEME", raising=False)
        monkeypatch.delenv("WEB_HOST", raising=False)
        monkeypatch.delenv("DEMO_PORT", raising=False)

        urls = build_urls("tenant_abc", ["web"])
        assert urls["chat"] == "http://localhost:8000/t/tenant_abc/chat"
        assert urls["operator"] == "http://localhost:8000/t/tenant_abc/operator"
        assert urls["admin"] == "http://localhost:8000/t/tenant_abc/admin"
        # Must NOT use the old subdomain form
        for value in urls.values():
            assert "sandbox.localhost" not in value

    def test_honors_env_overrides(self, monkeypatch):
        from autoservice.onboarding import build_urls

        monkeypatch.setenv("WEB_SCHEME", "https")
        monkeypatch.setenv("WEB_HOST", "demo.example.com")
        monkeypatch.setenv("DEMO_PORT", "8443")

        urls = build_urls("tenant_xyz", ["web", "feishu"])
        assert urls["chat"] == "https://demo.example.com:8443/t/tenant_xyz/chat"
        assert urls["operator"] == "https://demo.example.com:8443/t/tenant_xyz/operator"
        assert urls["admin"] == "https://demo.example.com:8443/t/tenant_xyz/admin"


# ---------------------------------------------------------------------------
# End-to-end: POST /api/onboard/activate
# ---------------------------------------------------------------------------

class TestActivateIdempotentMerge:
    def test_first_activate_adds_channels_compliance_soul_dream(self, isolated_sandbox):
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_first"
        cfg_path = _write_skeleton(sandbox_root, tenant_id)

        client = TestClient(_build_app())
        resp = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web,feishu"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # URLs in path form
        urls = body["urls"]
        assert urls["chat"].endswith(f"/t/{tenant_id}/chat")
        assert urls["operator"].endswith(f"/t/{tenant_id}/operator")
        assert urls["admin"].endswith(f"/t/{tenant_id}/admin")

        # Config is merged on disk
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # Step-0 fields preserved
        assert cfg["tenant_id"] == tenant_id
        assert cfg["brand_name"] == "acmecorp"
        assert cfg["industry"] == "ecommerce"
        assert cfg["status"] == "sandbox"
        assert cfg["created_at"] == "2026-04-20T10:00:00+00:00"
        # Channels persisted (bug #3 fix)
        assert cfg["channels"] == ["web", "feishu"]
        # Compliance defaults filled
        assert "compliance" in cfg
        assert isinstance(cfg["compliance"], dict)
        # Soul defaults filled
        assert "soul" in cfg
        assert isinstance(cfg["soul"], dict)
        # Dream defaults filled per spec §2.2
        assert cfg["dream"]["trigger"] == "idle"
        assert cfg["dream"]["coverage"] == "all"
        assert cfg["dream"]["risk_threshold"] == "medium"
        assert cfg["dream"]["canary"] == {
            "stages": [5, 25, 100],
            "observe_hours": 24,
        }

    def test_second_activate_is_idempotent(self, isolated_sandbox):
        """Calling /activate twice must not lose any data from the first call."""
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_idem"
        cfg_path = _write_skeleton(sandbox_root, tenant_id)

        client = TestClient(_build_app())

        # First call
        r1 = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web"},
        )
        assert r1.status_code == 200
        cfg1 = json.loads(cfg_path.read_text(encoding="utf-8"))

        # User tweaks a compliance flag between activates
        cfg1["compliance"]["privacy_policy_url"] = "https://example.com/privacy"
        cfg1["compliance"]["consent_mechanism_enabled"] = True
        cfg1["soul"]["disclosure_enabled"] = True
        cfg_path.write_text(json.dumps(cfg1, indent=2), encoding="utf-8")

        # Second call (same channels)
        r2 = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web"},
        )
        assert r2.status_code == 200
        cfg2 = json.loads(cfg_path.read_text(encoding="utf-8"))

        # User's manual edits must survive — compliance/soul are setdefault'd
        assert cfg2["compliance"]["privacy_policy_url"] == "https://example.com/privacy"
        assert cfg2["compliance"]["consent_mechanism_enabled"] is True
        assert cfg2["soul"]["disclosure_enabled"] is True
        # Step-0 fields still intact
        assert cfg2["tenant_id"] == tenant_id
        assert cfg2["brand_name"] == "acmecorp"
        assert cfg2["status"] == "sandbox"
        assert cfg2["created_at"] == "2026-04-20T10:00:00+00:00"
        # Dream block still present unchanged
        assert cfg2["dream"]["trigger"] == "idle"

    def test_custom_fields_survive_second_activate(self, isolated_sandbox):
        """Fields not owned by /activate (e.g., user-added) must be preserved."""
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_custom"
        cfg_path = _write_skeleton(
            sandbox_root,
            tenant_id,
            custom_field="keep-me",
            nested_custom={"answer": 42},
        )

        client = TestClient(_build_app())
        # First activate
        assert client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web"},
        ).status_code == 200

        # Second activate
        assert client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web,feishu"},
        ).status_code == 200

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["custom_field"] == "keep-me"
        assert cfg["nested_custom"] == {"answer": 42}
        # channels update from 2nd call IS applied (channels is authoritative)
        assert cfg["channels"] == ["web", "feishu"]

    def test_channels_are_persisted(self, isolated_sandbox):
        """Bug #3 — verify the UI's channel selection lands in config.json."""
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_chan"
        cfg_path = _write_skeleton(sandbox_root, tenant_id)

        client = TestClient(_build_app())
        resp = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web,feishu,wecom"},
        )
        assert resp.status_code == 200
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["channels"] == ["web", "feishu", "wecom"]

    def test_returned_urls_are_path_form(self, isolated_sandbox):
        """Bug: response URL form should be /t/<tid>/... (spec §5.1)."""
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_urls"
        _write_skeleton(sandbox_root, tenant_id)

        client = TestClient(_build_app())
        resp = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": "web"},
        )
        assert resp.status_code == 200
        urls = resp.json()["urls"]
        assert urls["chat"] == f"http://localhost:8000/t/{tenant_id}/chat"
        assert urls["operator"] == f"http://localhost:8000/t/{tenant_id}/operator"
        assert urls["admin"] == f"http://localhost:8000/t/{tenant_id}/admin"
        # Old subdomain form must be gone
        for value in urls.values():
            assert "sandbox.localhost" not in value

    def test_missing_skeleton_returns_error(self, isolated_sandbox):
        """If Step-0 /upload was never run, /activate should surface a clear error."""
        # No skeleton written
        client = TestClient(_build_app())
        resp = client.post(
            "/api/onboard/activate",
            data={"tenant_id": "nonexistent_tenant", "channels": "web"},
        )
        # 404 or 400 — just ensure non-2xx so we don't silently create bad config
        assert resp.status_code >= 400

    def test_channels_array_variants(self, isolated_sandbox):
        """Accept empty-channels gracefully (stores []), non-empty strips whitespace."""
        sandbox_root = isolated_sandbox / ".autoservice" / "sandbox"
        tenant_id = "tenant_empty"
        cfg_path = _write_skeleton(sandbox_root, tenant_id)

        client = TestClient(_build_app())
        # Empty channels → stored as empty list
        r_empty = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": ""},
        )
        assert r_empty.status_code == 200
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["channels"] == []

        # With whitespace around tokens
        r_ws = client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": " web , feishu "},
        )
        assert r_ws.status_code == 200
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["channels"] == ["web", "feishu"]
