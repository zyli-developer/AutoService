"""T1S.1 · End-to-end sandbox provisioning smoke test.

Validates docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §10
acceptance criteria 1-9.  Each test maps to one step in the spec.

What "end-to-end" means here
----------------------------
These tests drive the full M1 sandbox pipeline through its *HTTP surface* —
the same surface the admin-portal wizard calls.  They do not spin up
``web_gateway.create_app`` (no WS + CCPool startup needed) because the spec
only requires the integration-level guarantees at steps 4/6/9, all of which
are checkable without a live WebSocket.

Mocks / shortcuts (all documented in conftest.py's ``mock_claude``)
  * ``soul_generator._generate_with_claude`` raises → template fallback runs.
  * ``api_routes._get_llm_client`` returns ``None`` → rehearsal demo fallback
    runs (the 12 hardcoded dialogs listed in ``api_routes._DEMO_DIALOGS``).
  * ``Path.cwd()`` + ``SANDBOX_ROOT``/``ARCHIVED_ROOT``/``PUBLISHED_ROOT``
    redirected to ``tmp_path`` so tests leave no trace in the repo's
    ``.autoservice/`` directory.
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Step 1 — A 打开 Master
# ---------------------------------------------------------------------------


def test_step1_master_tenants_empty(e2e_client: TestClient) -> None:
    """``GET /api/master/tenants`` returns ``[]`` on a fresh sandbox root."""
    resp = e2e_client.get("/api/master/tenants")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Step 2 — A 走向导 (Step 0 → Step 4)
# ---------------------------------------------------------------------------


def test_step2_wizard_full_flow(run_wizard) -> None:
    """The wizard walks from ``/upload`` through rehearsal review without
    raising.  Downstream artifact checks live in step 3."""
    out = run_wizard()

    assert out["tenant_id"].startswith("tenant_")
    assert out["upload"]["files_parsed"] == 2
    assert out["upload"]["kb_chunks_written"] >= 1

    activate = out["activate"]
    assert activate["status"] == "sandbox"
    assert activate["channels"] == ["web", "feishu"]
    assert activate["urls"]["chat"].endswith(f"/tenant/{out['tenant_id']}/chat")

    rehearsal = out["rehearsal"]
    assert rehearsal["demo_mode"] is True  # mock_claude forces demo fallback
    assert len(rehearsal["dialogs"]) == 12
    assert out["review_count"] == 12


# ---------------------------------------------------------------------------
# Step 3 — 沙盒产物齐全
# ---------------------------------------------------------------------------


def test_step3_sandbox_artifacts_complete(
    run_wizard, isolated_layout: dict[str, Path]
) -> None:
    """Every artifact required by spec §10.3 lives on disk under the sandbox root."""
    out = run_wizard()
    tid = out["tenant_id"]
    sandbox = isolated_layout["sandbox"] / tid
    assert sandbox.is_dir()

    # --- souls/ ---
    souls = sandbox / "souls"
    for role in ("customer", "translate", "lead", "triage", "dream"):
        path = souls / f"{role}_soul.md"
        assert path.is_file(), f"missing {path}"
        assert path.read_text(encoding="utf-8").strip(), f"{role}_soul.md is empty"

    meta = souls / "_generation_meta.yaml"
    try:
        import yaml  # noqa: F401
        assert meta.is_file(), "_generation_meta.yaml must be written when pyyaml is installed"
        assert meta.read_text(encoding="utf-8").strip()
    except ImportError:  # pragma: no cover — CI always has pyyaml
        pass

    # --- kb/kb.db ≥ 1 chunk ---
    kb_db = sandbox / "kb" / "kb.db"
    assert kb_db.is_file(), "kb.db must exist"
    conn = sqlite3.connect(str(kb_db))
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
        assert count >= 1, "kb.db must have at least one chunk"
    finally:
        conn.close()

    # --- rehearsal.json — 12 dialogs, none pending after review ---
    rehearsal_path = sandbox / "rehearsal.json"
    assert rehearsal_path.is_file()
    reh = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    dialogs = reh.get("dialogs", [])
    assert len(dialogs) == 12, f"expected 12 rehearsal dialogs, got {len(dialogs)}"
    pending = [d for d in dialogs if d.get("review_status", "pending") == "pending"]
    assert not pending, f"unreviewed dialogs after wizard: {[d['id'] for d in pending]}"

    # --- config.json — status=sandbox, channels + dream correct ---
    cfg = json.loads((sandbox / "config.json").read_text(encoding="utf-8"))
    assert cfg["status"] == "sandbox"
    assert cfg["channels"] == ["web", "feishu"]

    assert "dream" in cfg, "config.json must have a dream block"
    dream = cfg["dream"]
    # /activate sets the 4 default dream params (spec §2.2).
    assert set(dream.keys()) >= {"trigger", "coverage", "risk_threshold", "canary"}, (
        f"dream block missing required keys: got {sorted(dream.keys())}"
    )
    # The defaults written by /activate — NOT the runtime DreamConfigSession
    # keys (step 7 exercises the runtime keys separately).
    assert dream["trigger"] == "idle"
    assert dream["coverage"] == "all"
    assert dream["risk_threshold"] == "medium"
    assert dream["canary"] == {"stages": [5, 25, 100], "observe_hours": 24}


# ---------------------------------------------------------------------------
# Step 4 — Master 沙盒预览可用 (WS endpoint reachable)
# ---------------------------------------------------------------------------


def test_step4_preview_url_backend_reachable(run_wizard) -> None:
    """The backend WS endpoints the preview iframe will talk to exist.

    The task spec explicitly de-scopes a live WS session: we just verify the
    endpoint is mounted and the URL shape the wizard returns points at the
    right host/path.  The concrete WS protocol is covered by the contract +
    gateway test suites.
    """
    # Stand up the full gateway app (WS routes live there, not on the minimal
    # e2e_app used for HTTP checks).
    from autoservice.web_gateway import create_app

    app = create_app()

    # All three viewer roles must be registered as WS endpoints.
    ws_paths = {
        getattr(r, "path", None)
        for r in app.router.routes
    }
    for role in ("customer", "operator", "admin"):
        assert f"/ws/{role}" in ws_paths, (
            f"expected /ws/{role} to be registered, saw {sorted(ws_paths)}"
        )

    # /upload-generated URLs follow the spec §5.1 path form, so the frontend
    # iframe's ``src`` resolves onto ``/tenant/<tid>/chat``.
    out = run_wizard()
    urls = out["activate"]["urls"]
    tid = out["tenant_id"]
    assert urls["chat"] == f"http://localhost:8000/tenant/{tid}/chat"
    assert urls["operator"] == f"http://localhost:8000/tenant/{tid}/operator"
    assert urls["admin"] == f"http://localhost:8000/tenant/{tid}/admin"


# ---------------------------------------------------------------------------
# Step 5 — 多租户隔离 (cc_pool soul isolation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step5_multi_tenant_soul_isolation(
    isolated_layout: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sandboxes X and Y produce distinct SDK system prompts.

    We call ``cc_pool.create_cc_client`` directly (bypassing HTTP) because
    the spec §10.5 check is specifically about the soul-injection path inside
    ``_load_soul`` — not the WS dispatcher.
    """
    from autoservice import cc_pool
    from autoservice.cc_pool import PoolConfig, create_cc_client

    captured: list[dict] = []

    class _FakeSDKClient:
        def __init__(self, options):
            captured.append({"options": options})
            self._transport = None

        async def connect(self):
            return None

        async def disconnect(self):
            return None

    monkeypatch.setattr(cc_pool, "ClaudeSDKClient", _FakeSDKClient)

    # Seed two sandboxes with obviously-distinct souls.
    tenant_x = "tenant_x_step5"
    tenant_y = "tenant_y_step5"
    for tid, content in (
        (tenant_x, "# Tenant X Soul\n\nI only talk about widgets and widget pricing."),
        (tenant_y, "# Tenant Y Soul\n\nI only talk about subscriptions and SaaS contracts."),
    ):
        souls_dir = isolated_layout["sandbox"] / tid / "souls"
        souls_dir.mkdir(parents=True, exist_ok=True)
        (souls_dir / "customer_soul.md").write_text(content, encoding="utf-8")

    cfg = PoolConfig(cwd=str(isolated_layout["root"]))

    await create_cc_client(cfg, role="customer", tenant_id=tenant_x)
    prompt_x = captured[-1]["options"].system_prompt

    await create_cc_client(cfg, role="customer", tenant_id=tenant_y)
    prompt_y = captured[-1]["options"].system_prompt

    assert prompt_x is not None and prompt_y is not None
    assert "widgets" in prompt_x and "widgets" not in prompt_y
    assert "subscriptions" in prompt_y and "subscriptions" not in prompt_x
    assert prompt_x != prompt_y


# ---------------------------------------------------------------------------
# Step 6 — A 代入预览 (master tenants list contains the provisioned tid)
# ---------------------------------------------------------------------------


def test_step6_master_preview_route_works(
    e2e_client: TestClient, run_wizard
) -> None:
    """After the wizard runs, the provisioned tid shows up in
    ``GET /api/master/tenants`` — which is the data source the TenantListTab
    reads to populate the "代入预览" iframe link."""
    before = e2e_client.get("/api/master/tenants").json()
    assert before == []

    out = run_wizard()
    tid = out["tenant_id"]

    after = e2e_client.get("/api/master/tenants").json()
    ids = [t["tenant_id"] for t in after]
    assert tid in ids, f"{tid} missing from /api/master/tenants listing: {ids}"

    entry = next(t for t in after if t["tenant_id"] == tid)
    assert entry["status"] == "sandbox"
    assert entry["brand_name"] == "acmecorp"
    assert entry["industry"] == "ecommerce"


# ---------------------------------------------------------------------------
# Step 7 — Dream 配置落盘 (DreamConfigSession → config.json.dream)
# ---------------------------------------------------------------------------


def test_step7_dream_config_persisted(
    e2e_client: TestClient, run_wizard
) -> None:
    """Walk a DreamConfigSession to DONE; the 4 confirmed params land in
    ``config.json.dream`` (overwriting the Step-1 defaults)."""
    out = run_wizard()
    tid = out["tenant_id"]

    # Drive the dialog.  Each post returns the next prompt in the body —
    # we don't assert it here (that's covered in tests/dream/...), we just
    # make sure the final "yes" transitions to DONE and the sync fires.
    steps = [
        "/dream-config",   # start
        "1",               # trigger = low_peak
        "1",               # coverage = all_squads
        "0.3",             # risk_threshold = 0.3
        "1",               # canary = 10_30_100
        "yes",             # confirm
    ]
    for msg in steps:
        r = e2e_client.post(
            "/api/management/chat",
            params={"message": msg, "tenant_id": tid},
        )
        assert r.status_code == 200, r.text

    # Final message confirms DONE.
    assert "已保存" in r.json()["content"]

    # config.json.dream now holds the runtime keys (distinct from the
    # /activate defaults checked in step 3).
    cfg_path = Path(".autoservice/sandbox") / tid / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    dream = cfg["dream"]
    assert set(dream.keys()) == {"trigger", "coverage", "risk_threshold", "canary"}, (
        f"dream block should have exactly the 4 runtime keys, got {sorted(dream.keys())}"
    )
    assert dream["trigger"] == "low_peak"
    assert dream["coverage"] == "all_squads"
    assert dream["risk_threshold"] == 0.3
    assert dream["canary"] == "10_30_100"


# ---------------------------------------------------------------------------
# Step 8 — Publish 完整产物
# ---------------------------------------------------------------------------


def test_step8_publish_full_pipeline(
    e2e_client: TestClient,
    run_wizard,
    isolated_layout: dict[str, Path],
    neutral_compliance: None,
) -> None:
    """``POST /api/onboard/publish`` must produce 3 artifacts and archive
    the sandbox.  Spec §10.8."""
    out = run_wizard()
    tid = out["tenant_id"]
    sandbox_path = isolated_layout["sandbox"] / tid
    assert sandbox_path.is_dir()

    resp = e2e_client.post(
        "/api/onboard/publish", json={"tenant_id": tid}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "published"
    assert body["tenant_id"] == tid

    # --- 3 artifacts under .autoservice/published/ ---
    artifact = Path(body["artifact"])
    runbook = Path(body["runbook"])
    record = Path(body["record"])
    assert artifact.is_file(), f"tarball missing at {artifact}"
    assert runbook.is_file(), f"runbook missing at {runbook}"
    assert record.is_file(), f"publish record missing at {record}"

    assert artifact.parent == isolated_layout["published"]
    assert artifact.suffix == ".gz" and artifact.name.startswith(f"tenant_{tid}_publish_")

    record_body = json.loads(record.read_text(encoding="utf-8"))
    assert record_body["tenant_id"] == tid
    assert record_body["status"] == "awaiting_fork"
    assert record_body["artifact_sha256"] == body["artifact_sha256"]

    # --- Sandbox physically moved to .autoservice/archived/<tid>_<ts>/ ---
    archived_to = Path(body["archived_to"])
    assert archived_to.is_dir(), f"archive missing at {archived_to}"
    assert archived_to.parent == isolated_layout["archived"]
    assert archived_to.name.startswith(f"{tid}_")
    assert not sandbox_path.exists(), "sandbox dir must be moved after publish"

    # --- config.json.status flipped to "archived" inside the archive ---
    archived_cfg = json.loads(
        (archived_to / "config.json").read_text(encoding="utf-8")
    )
    assert archived_cfg["status"] == "archived"


# ---------------------------------------------------------------------------
# Step 9 — Fork 手工验证 (tarball layout)
# ---------------------------------------------------------------------------


def test_step9_tarball_fork_structure(
    e2e_client: TestClient,
    run_wizard,
    isolated_layout: dict[str, Path],
    neutral_compliance: None,
) -> None:
    """The publish tarball extracts into a valid ``plugins/<tid>/...`` shape.

    Concrete membership checks per spec §10.9:
      * ``plugins/<tid>/plugin.yaml``
      * ``plugins/<tid>/config.json``
      * ``plugins/<tid>/README.md``
      * ``plugins/<tid>/rehearsal_baseline.json``
      * ``plugins/<tid>/kb/kb.db``
      * ``plugins/<tid>/souls/{customer,translate,lead,triage,dream}_soul.md``  (5 files)
    """
    out = run_wizard()
    tid = out["tenant_id"]

    resp = e2e_client.post("/api/onboard/publish", json={"tenant_id": tid})
    assert resp.status_code == 200, resp.text
    artifact = Path(resp.json()["artifact"])
    assert artifact.is_file()

    prefix = f"plugins/{tid}/"
    required = {
        f"{prefix}plugin.yaml",
        f"{prefix}config.json",
        f"{prefix}README.md",
        f"{prefix}rehearsal_baseline.json",
        f"{prefix}kb/kb.db",
    }
    required_souls = {
        f"{prefix}souls/{role}_soul.md"
        for role in ("customer", "translate", "lead", "triage", "dream")
    }
    required |= required_souls

    with tarfile.open(artifact, "r:gz") as tar:
        names = set(tar.getnames())

    missing = required - names
    assert not missing, f"tarball is missing fork-structure entries: {sorted(missing)}"

    # All 5 souls together — belt & braces, guards against a regex pruning
    # regression in ``build_publish_archive``.
    soul_entries = {n for n in names if n.startswith(f"{prefix}souls/") and n.endswith(".md")}
    assert len(soul_entries) == 5, (
        f"expected 5 soul markdown files, got {len(soul_entries)}: "
        f"{sorted(soul_entries)}"
    )
