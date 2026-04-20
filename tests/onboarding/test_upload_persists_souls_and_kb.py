"""T1B.1 — verify Step 0 `/api/onboard/upload` produces the sandbox schema on disk.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §2 / §3.1

Goals:
  1. `.autoservice/sandbox/<tid>/config.json` exists with tenant_id / brand_name /
     industry / status="sandbox" / created_at.
  2. `.autoservice/sandbox/<tid>/souls/` contains 4 LLM-draft soul files
     (customer / translate / lead / triage) + `_generation_meta.yaml` +
     `dream_soul.md` (static template copy).
  3. `.autoservice/sandbox/<tid>/kb/kb.db` exists and has >=1 row in `kb_chunks`.
  4. `dream_soul.md` is non-empty.

We mock:
  - soul_generator.KB_DB_PATH → a path that does not exist, so
    `_search_kb` returns [] → `generate_soul` uses the template
    fallback and never calls Claude.
  - anthropic module is irrelevant (fallback path avoids it entirely),
    but we also guard against accidental API calls.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    """Return a FastAPI app with only the onboarding router mounted."""
    from autoservice.onboarding import onboard_router

    app = FastAPI()
    app.include_router(onboard_router)
    return app


@pytest.fixture
def isolated_project_root(tmp_path, monkeypatch):
    """Redirect sandbox writes to a temp dir by monkeypatching module paths.

    Both `autoservice.onboarding.SANDBOX_ROOT` and
    `autoservice.soul_generator.PROJECT_ROOT` are overridden so all on-disk
    artifacts go into tmp_path, keeping the repo clean across test runs.
    """
    from autoservice import onboarding as onboarding_mod
    from autoservice import soul_generator as soul_mod

    fake_sandbox_root = tmp_path / ".autoservice" / "sandbox"
    monkeypatch.setattr(onboarding_mod, "SANDBOX_ROOT", fake_sandbox_root)

    # soul_generator.save_drafts uses PROJECT_ROOT/.autoservice/sandbox/<tid>/souls
    monkeypatch.setattr(soul_mod, "PROJECT_ROOT", tmp_path)

    # Force _search_kb to find nothing → fallback path avoids Claude API
    monkeypatch.setattr(soul_mod, "KB_DB_PATH", tmp_path / "nonexistent.db")

    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests for the helpers (fast path, no HTTP)
# ---------------------------------------------------------------------------

class TestSandboxHelpers:
    def test_init_sandbox_kb_creates_schema(self, tmp_path):
        from autoservice.onboarding import _init_sandbox_kb

        db_path = tmp_path / "kb.db"
        conn = _init_sandbox_kb(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
            assert "kb_chunks" in tables
            assert "kb_fts" in tables
        finally:
            conn.close()
        assert db_path.exists()

    def test_ingest_chunks_writes_rows(self, tmp_path, monkeypatch):
        from autoservice import onboarding as onboarding_mod

        monkeypatch.setattr(
            onboarding_mod, "SANDBOX_ROOT", tmp_path / ".autoservice" / "sandbox"
        )
        file_results = [
            {
                "status": "ok",
                "original_name": "brand.txt",
                "chunks": ["Welcome to brand X.", "Refund policy 14d."],
            },
            {"status": "skipped", "chunks": ["ignored"]},
        ]
        written = onboarding_mod._ingest_chunks_into_sandbox_kb("t_test", file_results)
        assert written == 2

        db = tmp_path / ".autoservice" / "sandbox" / "t_test" / "kb" / "kb.db"
        assert db.exists()
        conn = sqlite3.connect(str(db))
        try:
            (count,) = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
            assert count == 2
            # FTS index is searchable
            rows = conn.execute(
                "SELECT content FROM kb_fts WHERE kb_fts MATCH 'refund'"
            ).fetchall()
            assert any("Refund" in r[0] for r in rows)
        finally:
            conn.close()

    def test_write_sandbox_config_skeleton(self, tmp_path, monkeypatch):
        from autoservice import onboarding as onboarding_mod

        monkeypatch.setattr(
            onboarding_mod, "SANDBOX_ROOT", tmp_path / ".autoservice" / "sandbox"
        )
        path = onboarding_mod._write_sandbox_config_skeleton(
            "tenant_abc", "acme", "ecommerce"
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["tenant_id"] == "tenant_abc"
        assert data["brand_name"] == "acme"
        assert data["industry"] == "ecommerce"
        assert data["status"] == "sandbox"
        assert "created_at" in data and data["created_at"]

    def test_copy_dream_soul_template(self, tmp_path, monkeypatch):
        from autoservice import onboarding as onboarding_mod

        monkeypatch.setattr(
            onboarding_mod, "SANDBOX_ROOT", tmp_path / ".autoservice" / "sandbox"
        )
        dest = onboarding_mod._copy_dream_soul_template("tenant_xyz")
        assert dest is not None
        assert dest.exists()
        body = dest.read_text(encoding="utf-8")
        assert body.strip(), "dream_soul.md should not be empty"
        assert "Dream Engine" in body


# ---------------------------------------------------------------------------
# End-to-end: POST /api/onboard/upload
# ---------------------------------------------------------------------------

class TestUploadEndpointPersistsArtifacts:
    def test_upload_produces_sandbox_schema(self, isolated_project_root, monkeypatch):
        # Guard: if anthropic is somehow invoked, fail loudly rather than silently
        # sending a real request. The fallback path should mean zero calls.
        import autoservice.soul_generator as soul_mod

        def _must_not_call(*_a, **_kw):
            raise AssertionError(
                "Claude API must not be called in tests — KB fallback should engage"
            )

        monkeypatch.setattr(soul_mod, "_generate_with_claude", _must_not_call)

        app = _build_app()
        client = TestClient(app)

        # Two small uploaded files so the KB gets >= 1 chunk.
        files = [
            ("files", ("intro.txt", io.BytesIO(b"Hello world. Our brand sells widgets."), "text/plain")),
            ("files", ("faq.md", io.BytesIO(b"# FAQ\n\nQ: Refunds?\nA: Within 14 days."), "text/markdown")),
        ]
        data = {"brand_name": "acmecorp", "industry": "ecommerce", "website_url": ""}

        resp = client.post("/api/onboard/upload", data=data, files=files)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        tenant_id = body["tenant_id"]
        assert tenant_id.startswith("tenant_")
        assert body["files_parsed"] == 2
        assert body["kb_chunks_written"] >= 1

        sandbox = isolated_project_root / ".autoservice" / "sandbox" / tenant_id
        assert sandbox.exists(), "sandbox root must be created"

        # --- (1) config.json skeleton ---
        config = sandbox / "config.json"
        assert config.exists()
        cfg = json.loads(config.read_text(encoding="utf-8"))
        assert cfg["tenant_id"] == tenant_id
        assert cfg["brand_name"] == "acmecorp"
        assert cfg["industry"] == "ecommerce"
        assert cfg["status"] == "sandbox"
        assert cfg.get("created_at")

        # --- (2) souls/ with 4 LLM + dream + _generation_meta.yaml ---
        souls_dir = sandbox / "souls"
        assert souls_dir.exists()
        for role in ("customer", "translate", "lead", "triage", "dream"):
            soul_file = souls_dir / f"{role}_soul.md"
            assert soul_file.exists(), f"missing {soul_file}"
            content = soul_file.read_text(encoding="utf-8")
            assert content.strip(), f"{role}_soul.md must not be empty"

        # dream_soul.md content is from the static template
        dream = (souls_dir / "dream_soul.md").read_text(encoding="utf-8")
        assert "Dream Engine" in dream

        # _generation_meta.yaml is written when pyyaml is available; absence
        # is tolerated only when yaml lib is missing.
        meta = souls_dir / "_generation_meta.yaml"
        try:
            import yaml  # noqa: F401
            assert meta.exists(), "_generation_meta.yaml must be written"
            assert meta.read_text(encoding="utf-8").strip()
        except ImportError:  # pragma: no cover
            pass

        # --- (3) kb/kb.db exists and has >= 1 chunk ---
        kb_db = sandbox / "kb" / "kb.db"
        assert kb_db.exists(), "sandbox kb.db must be created"
        conn = sqlite3.connect(str(kb_db))
        try:
            (count,) = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
            assert count >= 1, "kb_chunks must have at least one row"
        finally:
            conn.close()

        # --- Response surface ---
        assert body["sandbox_dir"].endswith(tenant_id)
        assert body["souls"] and "error" not in body["souls"]
        saved_to = body["souls"].get("saved_to", {})
        # All 4 LLM roles should have persisted paths
        for role in ("customer", "translate", "lead", "triage"):
            assert role in saved_to, f"role {role} not in saved_to"
        assert "dream" in saved_to

    def test_upload_with_no_files_still_creates_skeleton(
        self, isolated_project_root, monkeypatch
    ):
        """Even with zero files, the sandbox config + souls dir should exist."""
        import autoservice.soul_generator as soul_mod

        monkeypatch.setattr(
            soul_mod,
            "_generate_with_claude",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                AssertionError("should not call Claude")
            ),
        )

        app = _build_app()
        client = TestClient(app)

        resp = client.post(
            "/api/onboard/upload",
            data={"brand_name": "minimal", "industry": "general"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        tenant_id = body["tenant_id"]
        sandbox = isolated_project_root / ".autoservice" / "sandbox" / tenant_id
        assert (sandbox / "config.json").exists()
        assert (sandbox / "souls" / "dream_soul.md").exists()
        # 4 LLM souls still written via fallback template
        for role in ("customer", "translate", "lead", "triage"):
            assert (sandbox / "souls" / f"{role}_soul.md").exists()
