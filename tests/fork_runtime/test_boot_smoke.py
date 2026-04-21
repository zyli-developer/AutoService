"""T7S.5 — Fork-mode boot smoke test (spec §3 + §8 acceptance step 3).

End-to-end assertion that a fresh tenant-fork checkout can stand up the full
FastAPI app: lifespan fires, `ensure_local_admin()` provisions
`plugins/_local_admin/`, `tenant_context_middleware` rewrites URL-flat paths,
and cross-tenant URLs are refused with 403 — all without CCPool / DreamScheduler
background work (they are gated via env vars so TestClient can finish synchronously).

This is the pytest mirror of spec §8 acceptance step 3
("Fork repo: `make setup && make run-web` boots cleanly").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from autoservice import bootstrap, master_tenant, web_gateway


TENANT_ID = "B"


@pytest.fixture(autouse=True)
def clear_bootstrap_cache():
    """get_deployment_mode / get_tenant_id are cached; reset between tests
    so each test starts from a clean resolution state."""
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


@pytest.fixture(autouse=True)
def disable_background_jobs(monkeypatch):
    """Disable CCPool warm-up + DreamScheduler loop so the lifespan that this
    smoke test exercises is hermetic — no Anthropic SDK, no async timers.

    This mirrors batch-12's `test_tenant_context.py` fixture.  The real
    production lifespan still does this boot work; we just skip the parts
    that would require network / background tasks in a unit-like smoke test.
    """
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("POOL_MODE", "0")


@pytest.fixture
def tenant_fork(tmp_path, monkeypatch):
    """Fresh tenant-fork layout under ``tmp_path``.

    Simulates the post-`setup.sh` state for ``deployment_mode=tenant`` +
    ``tenant_id=B``: `.autoservice/config.local.yaml` present,
    `plugins/B/config.json` with matching tenant_id.  Crucially we do NOT
    pre-create `plugins/_local_admin/` — the lifespan is expected to
    provision it on startup (T1B.5 / spec §2.8).
    """
    (tmp_path / ".autoservice").mkdir()
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(
        f"deployment_mode: tenant\ntenant_id: {TENANT_ID}\n",
        encoding="utf-8",
    )
    plugins = tmp_path / "plugins" / TENANT_ID
    plugins.mkdir(parents=True)
    (plugins / "config.json").write_text(
        json.dumps({"tenant_id": TENANT_ID}), encoding="utf-8"
    )
    # Direct every path-resolving module at this fresh root.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _attach_chat_echo(app):
    """Install a `/chat` echo route so the URL-flat rewrite from
    `/t/<self>/chat` has a concrete handler to land on.  Without this
    the rewritten path would 404 — which is still a valid pass (framework
    healthy, route unpinned), but adding the route lets us assert the
    *scope path* actually changed."""

    async def echo(request: Request):
        return {
            "scope_path": request.scope["path"],
            "deployment_mode": getattr(request.state, "deployment_mode", None),
            "tenant_id": getattr(request.state, "tenant_id", None),
        }

    app.add_api_route("/chat", echo, methods=["GET"])
    return app


class TestForkModeBootSmoke:
    """spec §8 step 3 — a fresh tenant fork stands up without exceptions."""

    def test_tenant_mode_boot_creates_local_admin(self, tenant_fork):
        """Lifespan startup invokes `ensure_local_admin()`; `plugins/_local_admin/`
        materialises with config.json + souls/ + kb/ on first boot."""
        app = web_gateway.create_app()
        admin_root = tenant_fork / "plugins" / "_local_admin"
        # Before startup the folder must not exist (fresh fork).
        assert not admin_root.exists()

        with TestClient(app):
            # Entering the context triggers @app.on_event("startup") handlers.
            assert admin_root.is_dir(), "ensure_local_admin() did not run"
            assert (admin_root / "config.json").exists()
            cfg = json.loads((admin_root / "config.json").read_text(encoding="utf-8"))
            assert cfg["tenant_id"] == "_local_admin"
            assert cfg["kind"] == "fork"
            # Souls + kb are the other deliverables of ensure_local_admin.
            assert (admin_root / "souls").is_dir()
            assert (admin_root / "kb" / "kb.db").exists()

    def test_tenant_mode_root_route_not_500(self, tenant_fork):
        """A known route (`/api/session/mode`) responds non-500 after tenant-mode
        boot — proof that the ASGI chain (CORS + TenantContext + routers) is
        wired without explosions.  The status code itself is not load-bearing
        (it may be 401, 200, 404 etc. depending on auth wiring) — only that
        the framework did not raise."""
        app = web_gateway.create_app()
        with TestClient(app) as client:
            resp = client.get("/api/session/mode")
        assert resp.status_code < 500, (
            f"tenant-mode framework returned 5xx on a known route: "
            f"{resp.status_code} {resp.text!r}"
        )

    def test_tenant_mode_self_tenant_url_prefix_rewrites(self, tenant_fork):
        """`/t/B/chat` → `/chat` in tenant-mode fork (URL-flat routing, spec §3.2).

        Asserts the TenantContext middleware did its job: the downstream
        handler sees the rewritten path AND `request.state` is populated.
        This is the pytest surrogate for spec §8 step 4 ("browser hits
        /chat without /t/<tid>/ prefix").
        """
        app = _attach_chat_echo(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get(f"/t/{TENANT_ID}/chat")
        assert resp.status_code == 200, (
            f"self-tenant URL was not served: {resp.status_code} {resp.text!r}"
        )
        data = resp.json()
        assert data["scope_path"] == "/chat"
        assert data["deployment_mode"] == "tenant"
        assert data["tenant_id"] == TENANT_ID

    def test_tenant_mode_cross_tenant_denies(self, tenant_fork):
        """`/t/other/chat` on tenant B fork → 403 (spec §3.2, cross-tenant
        refusal).  Exercises the TenantContext middleware's single-tenant
        enforcement in a full boot context."""
        app = _attach_chat_echo(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/t/other/chat")
        assert resp.status_code == 403
        body = resp.json()
        assert "cross-tenant" in body.get("error", "")

    def test_tenant_mode_lifespan_shutdown_clean(self, tenant_fork):
        """The full startup → shutdown cycle completes without exception.

        This is the smoke-test red-line: neither CCPool shutdown nor
        DreamScheduler shutdown may raise.  With POOL_MODE=0 +
        DREAM_SCHEDULER_DISABLED=1 the relevant hooks become no-ops but
        the event handlers still fire — so the `async with` must exit
        cleanly (no unhandled task exceptions, no hung background work)."""
        app = web_gateway.create_app()
        # TestClient as a context manager drives the full lifespan: enter
        # triggers startup, exit triggers shutdown.  A raise on either end
        # propagates out here and fails the test.
        with TestClient(app) as client:
            # One trivial request confirms the app loop is live between the
            # lifespan hooks — a stronger guarantee than just entering the ctx.
            resp = client.get("/api/session/mode")
            assert resp.status_code < 500
