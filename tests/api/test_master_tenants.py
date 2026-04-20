"""Tests for T1F.6 — GET /api/master/tenants endpoint.

The endpoint lists tenants from ``.autoservice/sandbox/<tid>/config.json``
(sandbox + published_pending_fork) and ``.autoservice/archived/<tid>_<ts>/``
(archived) — see autoservice.api_routes.list_master_tenants.

Tests chdir into an isolated ``tmp_path`` so the relative ``.autoservice/``
paths resolve to fixture dirs (matching how onboarding.py / publish.py write
configs under ``PROJECT_ROOT / ".autoservice" / "..."``).

See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice.api_routes import api_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app)


@pytest.fixture()
def sandbox_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """chdir into tmp_path so relative `.autoservice/*` resolves here."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_config(root: Path, tid: str, *, status: str, brand: str, industry: str) -> None:
    tid_dir = root / tid
    tid_dir.mkdir(parents=True, exist_ok=True)
    (tid_dir / "config.json").write_text(
        json.dumps(
            {
                "tenant_id": tid,
                "brand_name": brand,
                "industry": industry,
                "status": status,
                "created_at": "2026-04-20T00:00:00+00:00",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_empty_dir_returns_empty_list(sandbox_cwd: Path, client: TestClient) -> None:
    """No sandbox/archived dirs at all → the endpoint returns `[]` gracefully."""
    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    assert resp.json() == []


def test_lists_sandbox_tenants(sandbox_cwd: Path, client: TestClient) -> None:
    """Each `.autoservice/sandbox/<tid>/config.json` becomes one entry."""
    sandbox = sandbox_cwd / ".autoservice" / "sandbox"
    _write_config(sandbox, "acme", status="sandbox", brand="Acme", industry="retail")
    _write_config(sandbox, "globex", status="published_pending_fork", brand="Globex", industry="saas")

    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2

    by_id = {e["tenant_id"]: e for e in body}
    assert by_id["acme"]["status"] == "sandbox"
    assert by_id["acme"]["brand_name"] == "Acme"
    assert by_id["acme"]["industry"] == "retail"
    assert by_id["acme"]["created_at"] == "2026-04-20T00:00:00+00:00"
    assert by_id["globex"]["status"] == "published_pending_fork"
    assert by_id["globex"]["brand_name"] == "Globex"


def test_includes_archived_tenants_with_archived_status(
    sandbox_cwd: Path, client: TestClient,
) -> None:
    """Archived entries are included and always report `status=archived`.

    Even if the on-disk config.json still has `status=sandbox` (race window
    before publish.py stamps it), the listing forces `status=archived` so the
    UI renders them under the correct badge.
    """
    archived = sandbox_cwd / ".autoservice" / "archived"
    # Archived dirs follow the `<tid>_<ts>` naming (see publish._archived_root_for).
    _write_config(
        archived,
        "oldco_20260301T000000Z",
        status="sandbox",  # stale — endpoint must override to archived.
        brand="OldCo",
        industry="finance",
    )

    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "archived"
    assert body[0]["brand_name"] == "OldCo"


def test_mixed_sandbox_and_archived(sandbox_cwd: Path, client: TestClient) -> None:
    """Sandbox + archived entries appear together in one list."""
    sandbox = sandbox_cwd / ".autoservice" / "sandbox"
    archived = sandbox_cwd / ".autoservice" / "archived"
    _write_config(sandbox, "live1", status="sandbox", brand="Live1", industry="x")
    _write_config(archived, "dead1_20260101T000000Z", status="archived", brand="Dead1", industry="y")

    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    body = resp.json()
    ids = sorted(e["tenant_id"] for e in body)
    assert ids == ["dead1_20260101T000000Z", "live1"]


def test_skips_files_and_dirs_without_config(sandbox_cwd: Path, client: TestClient) -> None:
    """Stray files and half-bootstrapped dirs without config.json are ignored."""
    sandbox = sandbox_cwd / ".autoservice" / "sandbox"
    sandbox.mkdir(parents=True)
    # A file inside sandbox/ (not a dir) — must be skipped.
    (sandbox / ".DS_Store").write_text("noise", encoding="utf-8")
    # A dir with no config.json (e.g. half-bootstrapped) — must be skipped.
    (sandbox / "empty_tid").mkdir()
    # A valid entry.
    _write_config(sandbox, "ok", status="sandbox", brand="OK", industry="general")

    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == "ok"


def test_corrupt_config_is_skipped(sandbox_cwd: Path, client: TestClient) -> None:
    """A corrupt config.json is skipped rather than failing the whole list."""
    sandbox = sandbox_cwd / ".autoservice" / "sandbox"
    bad = sandbox / "broken"
    bad.mkdir(parents=True)
    (bad / "config.json").write_text("{not valid json", encoding="utf-8")
    _write_config(sandbox, "good", status="sandbox", brand="Good", industry="general")

    resp = client.get("/api/master/tenants")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == "good"
