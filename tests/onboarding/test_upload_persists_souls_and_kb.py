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
    def test_kb_store_creates_trigram_schema(self, tmp_path):
        from autoservice.kb_core import KBStore
        with KBStore(tmp_path / "kb.db") as store:
            conn = sqlite3.connect(str(store.db_path))
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='kb_fts'"
            ).fetchone()[0]
            conn.close()
            assert "trigram" in sql


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

        # Two uploaded files, each with at least one paragraph above
        # KBStore's CHUNK_MIN_CHARS (50) threshold so the KB gets >= 1 chunk.
        intro = (
            b"Welcome to AcmeCorp! We are a retailer that sells a wide range of "
            b"widgets and accessories to businesses across the globe."
        )
        faq = (
            b"# FAQ\n\nQ: What is your refund policy?\nA: We accept returns within "
            b"14 days of purchase, provided items are in original condition and "
            b"accompanied by the original receipt or order confirmation email."
        )
        files = [
            ("files", ("intro.txt", io.BytesIO(intro), "text/plain")),
            ("files", ("faq.md", io.BytesIO(faq), "text/markdown")),
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


class TestUploadBugFixes:
    """Regression tests for the three bugs identified in the KB audit
    (2026-04-22 KB unification plan §Phase 4)."""

    def test_reupload_same_file_does_not_duplicate_chunks(
        self, isolated_project_root, monkeypatch,
    ):
        """Re-ingesting the same file_bytes via the same source_id keeps count stable."""
        app = _build_app()
        client = TestClient(app)

        # First upload creates a tenant with N chunks for that file.
        file_body = b"Alpha paragraph with enough text to pass the minimum threshold. " * 5
        resp = client.post(
            "/api/onboard/upload",
            data={"brand_name": "Dedup Co", "industry": "retail"},
            files={"files": ("note.txt", file_body, "text/plain")},
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()
        tid = first["tenant_id"]
        db = isolated_project_root / ".autoservice" / "sandbox" / tid / "kb" / "kb.db"
        conn = sqlite3.connect(str(db))
        first_count = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
        conn.close()

        # Now simulate a re-ingest WITHIN the same tenant by opening KBStore
        # directly and calling ingest_text with the same source_id a second
        # time (the wizard creates a new tenant each call, but the source_id
        # scheme is deterministic on file bytes). If the scheme is correct,
        # count stays stable.
        import hashlib
        from autoservice.kb_core import KBStore
        source_id = f"file:{hashlib.sha256(file_body).hexdigest()[:16]}"

        with KBStore(db) as store:
            before = store.count()
            n = store.ingest_text(
                file_body.decode("utf-8"),
                source_id=source_id,
                source_name="note.txt", source_type="text",
            )
            # Count stays stable: clear_source(source_id) wiped previous rows,
            # ingest_text reseeded the same content with the same id pattern.
            assert store.count() == before
            assert n == first_count  # same chunk count as the wizard call

    def test_upload_with_website_url_ingests_into_kb(
        self, isolated_project_root, monkeypatch,
    ):
        """website_url content must end up in kb_chunks (not silently dropped)."""
        from autoservice import kb_core

        html = "<html><body><main><h2>Services</h2><p>We sell widgets of many varieties, including premium and standard lines. Each widget has comprehensive documentation for integration.</p></main></body></html>"

        class _FakeResp:
            def __init__(self, text):
                self.text = text
                self.status_code = 200
            def raise_for_status(self): pass

        class _FakeSession:
            def get(self, *a, **kw):
                return _FakeResp(html)

        monkeypatch.setattr(kb_core, "_make_http_session", lambda: _FakeSession())
        monkeypatch.setattr(kb_core.time, "sleep", lambda _s: None)

        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/api/onboard/upload",
            data={"brand_name": "Web Co", "industry": "retail", "website_url": "https://example.com/"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        tid = payload["tenant_id"]

        db = isolated_project_root / ".autoservice" / "sandbox" / tid / "kb" / "kb.db"
        conn = sqlite3.connect(str(db))
        n = conn.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE source_id = 'website'"
        ).fetchone()[0]
        conn.close()
        assert n >= 1
        # Response payload should also mention the URL ingestion.
        assert payload.get("url_result", {}).get("status") == "ok"
        assert payload.get("url_result", {}).get("chunks_written", 0) >= 1
