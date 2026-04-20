"""Shared fixtures for the T1S.1 end-to-end sandbox provisioning smoke test.

These fixtures assemble a FastAPI TestClient wired to the onboarding + api
routers, redirect every disk path used by the sandbox pipeline into an
isolated ``tmp_path``, and force deterministic non-LLM behaviour by stubbing
the two Claude entry points (``soul_generator._generate_with_claude`` and
``api_routes._get_llm_client``).

Each fixture is composable: ``isolated_layout`` only sets up paths; the
``e2e_client`` fixture layers the HTTP + LLM stubs on top.  Tests that only
need cc_pool or publish helpers can depend on ``isolated_layout`` alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Path isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect every sandbox-related disk path to ``tmp_path``.

    Patches:
      * ``autoservice.onboarding.SANDBOX_ROOT`` → ``<tmp>/.autoservice/sandbox``
      * ``autoservice.publish.SANDBOX_ROOT`` / ``ARCHIVED_ROOT`` / ``PUBLISHED_ROOT``
      * ``autoservice.soul_generator.PROJECT_ROOT`` / ``KB_DB_PATH``
      * ``cwd`` → ``tmp_path`` (so cc_pool + api_routes Path(".autoservice/...")
        resolve relative to the temp dir)

    Also clears URL env overrides so ``build_urls`` returns the default
    ``http://localhost:8000/t/<tid>/...`` form.
    """
    from autoservice import onboarding as onboarding_mod
    from autoservice import publish as publish_mod
    from autoservice import soul_generator as soul_mod

    sandbox_root = tmp_path / ".autoservice" / "sandbox"
    archived_root = tmp_path / ".autoservice" / "archived"
    published_root = tmp_path / ".autoservice" / "published"

    # onboarding writes sandbox configs + dream template + KB chunks here.
    monkeypatch.setattr(onboarding_mod, "SANDBOX_ROOT", sandbox_root)

    # publish flow reads/writes sandbox / archived / published roots.
    monkeypatch.setattr(publish_mod, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(publish_mod, "ARCHIVED_ROOT", archived_root)
    monkeypatch.setattr(publish_mod, "PUBLISHED_ROOT", published_root)

    # soul_generator.save_drafts resolves sandbox souls via PROJECT_ROOT.
    monkeypatch.setattr(soul_mod, "PROJECT_ROOT", tmp_path)
    # And _search_kb is pinned to a missing DB so the template fallback runs
    # (no Claude calls even if the mock below is bypassed).
    monkeypatch.setattr(soul_mod, "KB_DB_PATH", tmp_path / "nonexistent.db")

    # chdir so Path(".autoservice/sandbox/<tid>/...") in api_routes +
    # cc_pool._load_soul resolves under tmp_path.
    monkeypatch.chdir(tmp_path)

    # Deterministic URL form.
    for key in ("WEB_SCHEME", "WEB_HOST", "DEMO_PORT"):
        monkeypatch.delenv(key, raising=False)

    return {
        "root": tmp_path,
        "sandbox": sandbox_root,
        "archived": archived_root,
        "published": published_root,
    }


# ---------------------------------------------------------------------------
# Claude / Anthropic mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic, offline behaviour for both Claude entry points.

    1. ``soul_generator._generate_with_claude`` → raise to force the template
       fallback (mirrors what tests/onboarding/test_upload_persists_souls_and_kb.py
       does).  Calling it is a test bug, so we raise AssertionError.
    2. ``api_routes._get_llm_client`` → return ``None`` so rehearsal generation
       goes into demo-mode fallback (12 hardcoded dialogs).
    """
    import autoservice.soul_generator as soul_mod
    import autoservice.api_routes as api_mod

    def _must_not_call(*_a, **_kw):
        raise AssertionError(
            "Claude API must not be invoked in E2E tests — KB fallback path engaged"
        )

    monkeypatch.setattr(soul_mod, "_generate_with_claude", _must_not_call)
    monkeypatch.setattr(api_mod, "_get_llm_client", lambda: None)


@pytest.fixture
def neutral_compliance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``publish._run_compliance_scan`` to return ``"low"``.

    The stock ``ComplianceEngine`` flags the skeleton config produced by
    ``/upload + /activate`` as ``critical`` (16-rule scan on default-empty
    privacy_policy_url / consent / etc.).  Spec §10 tests the publish
    *mechanism*, not the compliance rule set — which is already covered
    under ``tests/compliance/``.  Mirrors the same neutralisation used in
    ``tests/publish/test_publish_gate_checks.py``.
    """
    from autoservice import publish as publish_mod

    monkeypatch.setattr(
        publish_mod, "_run_compliance_scan",
        lambda _tid, _cfg: "low",
    )


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_app() -> FastAPI:
    """Build a minimal FastAPI app with the onboarding + api routers mounted.

    We skip ``web_gateway.create_app`` because it pulls in the WebSocket
    gateway + engine + CCPool startup — none of which are exercised by the
    T1S.1 HTTP-level checks.
    """
    from autoservice.onboarding import onboard_router
    from autoservice.api_routes import api_router

    app = FastAPI()
    app.include_router(onboard_router)
    app.include_router(api_router)
    return app


@pytest.fixture
def e2e_client(
    e2e_app: FastAPI,
    isolated_layout: dict[str, Path],
    mock_claude: None,
    _reset_dream_session: None,
) -> TestClient:
    """A ready-to-use ``TestClient`` with all layout + mock fixtures applied."""
    return TestClient(e2e_app)


# ---------------------------------------------------------------------------
# Dream Engine singleton reset
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_dream_session():
    """Reset the module-level ``DreamConfigSession`` between tests.

    Otherwise a previous test's partial dialog leaks into the next.
    """
    from autoservice import api_routes

    api_routes._dream_config_session = None
    yield
    api_routes._dream_config_session = None


# ---------------------------------------------------------------------------
# Higher-level helpers exposed as fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_wizard(e2e_client: TestClient) -> Callable[..., dict[str, Any]]:
    """Walk through Step 0 → Step 4 and return a summary dict.

    Returns ``{tenant_id, upload, activate, rehearsal, review_count,
    publish_gate_ready}``.  The caller can then inspect disk state or follow
    up with ``/publish``.

    Each inner step reads the previous step's response for ``tenant_id``
    etc — exactly the data flow a UI would use.
    """
    import io

    def _run(
        *,
        brand_name: str = "acmecorp",
        industry: str = "ecommerce",
        channels: str = "web,feishu",
        include_files: bool = True,
        approve_all: bool = True,
    ) -> dict[str, Any]:
        # --- Step 0: /upload ---------------------------------------------------
        files_arg: list[tuple] = []
        if include_files:
            files_arg = [
                (
                    "files",
                    (
                        "intro.txt",
                        io.BytesIO(
                            (
                                f"{brand_name} is a {industry} company.\n"
                                "We offer widgets, gadgets, and subscription bundles.\n"
                                "Refund policy: 14 days, no questions asked.\n"
                            ).encode("utf-8")
                        ),
                        "text/plain",
                    ),
                ),
                (
                    "files",
                    (
                        "faq.md",
                        io.BytesIO(
                            (
                                "# FAQ\n\n"
                                "Q: How do I contact support?\n"
                                "A: support@example.com or use the widget.\n\n"
                                "Q: Shipping time?\n"
                                "A: 3–5 business days.\n"
                            ).encode("utf-8")
                        ),
                        "text/markdown",
                    ),
                ),
            ]

        upload_resp = e2e_client.post(
            "/api/onboard/upload",
            data={
                "brand_name": brand_name,
                "industry": industry,
                "website_url": "",
            },
            files=files_arg,
        )
        assert upload_resp.status_code == 200, upload_resp.text
        upload = upload_resp.json()
        tenant_id = upload["tenant_id"]

        # --- Step 1: /activate -------------------------------------------------
        activate_resp = e2e_client.post(
            "/api/onboard/activate",
            data={"tenant_id": tenant_id, "channels": channels},
        )
        assert activate_resp.status_code == 200, activate_resp.text
        activate = activate_resp.json()

        # --- Step 2: /rehearsal/generate + /rehearsal/review -------------------
        rehearsal_resp = e2e_client.post(
            "/api/rehearsal/generate",
            params={"tenant_id": tenant_id},
        )
        assert rehearsal_resp.status_code == 200, rehearsal_resp.text
        rehearsal = rehearsal_resp.json()
        dialogs = rehearsal["dialogs"]

        review_count = 0
        if approve_all:
            for d in dialogs:
                r = e2e_client.post(
                    "/api/rehearsal/review",
                    json={
                        "tenant_id": tenant_id,
                        "dialog_id": d["id"],
                        "review_status": "approved",
                        "review_note": "E2E auto-approve",
                    },
                )
                assert r.status_code == 200, r.text
                review_count += 1

        # --- Step 3: compliance is implicit for this smoke test — the
        # activate call already injected DEFAULT_COMPLIANCE, which yields
        # non-critical risk from the ComplianceEngine.  Dedicated compliance
        # tests live under tests/compliance/.
        #
        # --- Step 4: "sandbox ready" is the state right before /publish.  The
        # caller of run_wizard decides whether to fire /publish next.

        return {
            "tenant_id": tenant_id,
            "upload": upload,
            "activate": activate,
            "rehearsal": rehearsal,
            "review_count": review_count,
        }

    return _run
