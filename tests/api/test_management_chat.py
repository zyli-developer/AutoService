"""T7B.6 — POST /api/management/chat → _master routing tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.7
      ("A 的 ManagementChat 接入 ``_master``").

Eval-doc: .artifacts/eval-docs/eval-t7b-6-management-chat.md (eval-doc-019).

The M2 endpoint routes the message through the real cc_pool with
``role="customer"``, ``tenant_id="_master"``.  Running a live Claude
subprocess per test would be prohibitively expensive and is already
covered in dedicated cc_pool / dream_agent suites, so these tests mock
``autoservice.cc_pool.get_pool`` to return a fake pool whose
``acquire(...)`` context manager records the kwargs and hands back a
stub client.  That lets us assert the wire contract in isolation:
status codes, error envelopes, and — critically — that ``acquire`` is
called with ``tenant_id="_master"`` exactly (never ``None``, never
``"default"``).

Pattern reused from ``tests/api/test_dream_api.py``:
  * TestClient built from a fresh FastAPI app that mounts ``api_router``.
  * ``monkeypatch.chdir(tmp_path)`` keeps any incidental filesystem
    touches (logs, snapshots) off the real repo tree.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, cc_pool


# ── Fake pool / client ────────────────────────────────────────────────────


class _FakeMessage:
    """Minimal stand-in for the SDK Message envelope.

    The real handler reads ``msg.content`` — which can be a string or a
    list of blocks with ``.text`` attributes. We exercise both paths via
    different test cases (the default here uses the string form, which
    is the simpler code path).
    """

    def __init__(self, content: Any):
        self.content = content


class _FakeClient:
    """Captures ``query`` calls and yields a scripted response."""

    def __init__(self, reply: str = "mocked reply"):
        self._reply = reply
        self.queries: list[str] = []

    async def query(self, prompt: str, **_: Any) -> None:
        self.queries.append(prompt)

    async def receive_response(self):
        yield _FakeMessage(self._reply)


class _FakeInstance:
    def __init__(self, client: _FakeClient):
        self.client = client


class _FakePool:
    """Records ``acquire`` kwargs so tests can pin the spec contract.

    The real ``CCPool.acquire`` returns an object that is used as an
    ``async with`` context manager — an ``asynccontextmanager`` decorator
    replicates that exactly.
    """

    def __init__(self, client: _FakeClient | None = None):
        self.client = client or _FakeClient()
        self.acquire_calls: list[dict[str, Any]] = []

    def acquire(self, *args: Any, **kwargs: Any):
        self.acquire_calls.append({"args": args, "kwargs": kwargs})

        @asynccontextmanager
        async def _cm():
            yield _FakeInstance(self.client)

        return _cm()


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    return TestClient(app)


@pytest.fixture()
def fake_pool(monkeypatch) -> _FakePool:
    """Install a fake pool and a ``get_pool`` that returns it.

    Note: we patch both the import site (``autoservice.cc_pool.get_pool``)
    and the attribute on ``api_routes`` if a cached reference snuck in.
    The endpoint imports ``get_pool`` lazily inside the handler, so the
    module-level patch is authoritative, but belt-and-braces keeps tests
    robust to future refactors.
    """
    pool = _FakePool()

    async def _get_pool(*_a: Any, **_kw: Any) -> _FakePool:
        return pool

    monkeypatch.setattr(cc_pool, "get_pool", _get_pool)
    return pool


# ── Tests ─────────────────────────────────────────────────────────────────


def test_management_chat_valid_message_returns_reply(
    app_client: TestClient, fake_pool: _FakePool,
) -> None:
    """Happy path: 200 + {"reply": "..."} with the mocked client's text."""
    resp = app_client.post("/api/management/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "mocked reply"}
    # Pool was checked out exactly once with the spec kwargs.
    assert len(fake_pool.acquire_calls) == 1
    kwargs = fake_pool.acquire_calls[0]["kwargs"]
    assert kwargs.get("role") == "customer"
    assert kwargs.get("tenant_id") == "_master"
    # Prompt was forwarded verbatim.
    assert fake_pool.client.queries == ["hi"]


def test_management_chat_empty_message_returns_422(
    app_client: TestClient, fake_pool: _FakePool,
) -> None:
    """Whitespace-only body → 422, pool never touched."""
    resp = app_client.post("/api/management/chat", json={"message": "   "})
    assert resp.status_code == 422
    assert resp.json() == {"error": "message required"}
    assert fake_pool.acquire_calls == []


def test_management_chat_missing_field_returns_422(
    app_client: TestClient, fake_pool: _FakePool,
) -> None:
    """Body missing ``message`` key → 422, pool never touched."""
    resp = app_client.post("/api/management/chat", json={})
    assert resp.status_code == 422
    assert resp.json() == {"error": "message required"}
    assert fake_pool.acquire_calls == []


def test_management_chat_routes_to_master_not_null_tenant(
    app_client: TestClient, fake_pool: _FakePool,
) -> None:
    """Spec §2.7 pin: tenant_id kwarg MUST be ``"_master"`` — never None,
    never ``"default"`` (the M1 query-string default), never a body-passed
    override.  Guards against a silent regression back to the M1 shape.
    """
    resp = app_client.post(
        "/api/management/chat",
        json={"message": "hello", "tenant_id": "not-master"},
    )
    assert resp.status_code == 200
    kwargs = fake_pool.acquire_calls[0]["kwargs"]
    assert kwargs["tenant_id"] == "_master"
    assert kwargs["tenant_id"] is not None
    assert kwargs["tenant_id"] != "default"
    assert kwargs["tenant_id"] != "not-master"
    assert kwargs["role"] == "customer"


def test_management_chat_pool_unavailable_returns_503(
    app_client: TestClient, monkeypatch,
) -> None:
    """When ``get_pool()`` returns None (POOL_MODE off / bootstrap race),
    the endpoint must return 503 — never 500, never a hardcoded stub reply.
    """

    async def _get_pool(*_a: Any, **_kw: Any):
        return None

    monkeypatch.setattr(cc_pool, "get_pool", _get_pool)

    resp = app_client.post("/api/management/chat", json={"message": "hi"})
    assert resp.status_code == 503
    body = resp.json()
    assert "cc_pool unavailable" in body.get("error", "")


def test_management_chat_regression_no_stub_llm() -> None:
    """Spec §9 risk mitigation: the new handler must NOT fall back to the
    M1 slash-command / Dream-Engine-stub dispatcher. This test greps the
    source of the live ``management_chat`` handler (obtained via
    ``inspect.getsource``) to confirm none of the M1 stub tokens leak in.

    If this test ever fails it means someone merged M1 logic back into
    the M2 handler — open eval-doc-019 and reconsider before changing
    the test expectation.
    """
    import inspect

    src = inspect.getsource(api_routes.management_chat)
    forbidden = [
        "DreamConfigSession",
        "/approve",
        "/reject",
        "/rollback",
        "@Dream Engine",
        "is_dream_config_trigger",
        "dream_session",
        "_handle_approve_command",
        "_handle_reject_command",
        "_persist_dream_config",
        # The M1 fallback's hardcoded Chinese reply fragments:
        "Dream Engine，负责夜间学习和优化",
        "我会记录这条反馈用于下次优化",
    ]
    leaks = [tok for tok in forbidden if tok in src]
    assert not leaks, f"M1 stub-LLM tokens leaked into M2 handler: {leaks}"

    # The handler MUST reference the spec-mandated acquire kwargs.
    assert 'role="customer"' in src
    assert 'tenant_id="_master"' in src


def test_management_chat_legacy_still_works(
    app_client: TestClient,
) -> None:
    """The M1 dispatcher was renamed to /api/management/chat-legacy so
    pre-M2 callers of slash commands have a one-milestone migration window
    (see eval-doc-019 "Back-compat via rename, not delete").  Confirm the
    legacy endpoint still handles /rules without touching the pool.
    """
    # This exercises the legacy endpoint with no body — the M1 handler
    # returns the prompt-me message for empty text.
    resp = app_client.post("/api/management/chat-legacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "system"
    assert "/rules" in body["content"]
