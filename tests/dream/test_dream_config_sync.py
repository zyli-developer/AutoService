"""T1B.6 — Dream config sync to sandbox config.json.

Covers the one-way write from ``/api/management/chat`` on final confirmation
of the 4-parameter Dream Engine dialog.  Verifies:

1. Full dialog completion persists all 4 keys under ``dream`` in
   ``.autoservice/sandbox/<tenant_id>/config.json``.
2. Partial dialogs do NOT write to disk.
3. Cancelling at the confirmation step does NOT write to disk.
4. Re-running the dialog overwrites the previous ``dream`` block but
   preserves other keys in config.json.
5. Missing sandbox directory gracefully skips (no exception, no file
   created elsewhere).

Fixes bug #9 (see docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §3.5).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    """Relocate cwd so that `.autoservice/sandbox/...` writes land under tmp_path."""
    monkeypatch.chdir(tmp_path)
    sandbox = tmp_path / ".autoservice" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def reset_dream_session():
    """Reset the module-level DreamConfigSession singleton between tests."""
    from autoservice import api_routes
    api_routes._dream_config_session = None
    yield
    api_routes._dream_config_session = None


@pytest.fixture
def client(reset_dream_session):
    """FastAPI TestClient bound to the api_router (no middleware needed)."""
    from fastapi import FastAPI
    from autoservice.api_routes import api_router

    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app)


def _seed_sandbox(sandbox_root: Path, tenant_id: str, base_config: dict | None = None) -> Path:
    """Create sandbox/<tid>/ with a minimal config.json skeleton."""
    tdir = sandbox_root / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    cfg_path = tdir / "config.json"
    if base_config is None:
        base_config = {
            "tenant_id": tenant_id,
            "brand_name": "testco",
            "industry": "ecommerce",
            "status": "sandbox",
        }
    cfg_path.write_text(json.dumps(base_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_path


def _walk_dream_dialog_to_confirm(client: TestClient, tenant_id: str = "default") -> None:
    """Post messages to /api/management/chat to reach the CONFIRM step.

    Leaves the dialog at ASK_CONFIRM (i.e., one more yes/no away from DONE).
    Uses defaults for all four params by sending empty/default replies.
    """
    # 1. Trigger the dialog
    r = client.post("/api/management/chat", params={"message": "/dream-config", "tenant_id": tenant_id})
    assert r.status_code == 200
    assert "触发时机" in r.json()["content"], "step 1 prompt should ask about trigger"

    # 2. Trigger answer (use default)
    r = client.post("/api/management/chat", params={"message": "1", "tenant_id": tenant_id})
    assert "覆盖范围" in r.json()["content"]

    # 3. Coverage answer
    r = client.post("/api/management/chat", params={"message": "1", "tenant_id": tenant_id})
    assert "风险阈值" in r.json()["content"]

    # 4. Risk threshold answer
    r = client.post("/api/management/chat", params={"message": "0.3", "tenant_id": tenant_id})
    assert "灰度策略" in r.json()["content"]

    # 5. Canary answer
    r = client.post("/api/management/chat", params={"message": "1", "tenant_id": tenant_id})
    assert "确认" in r.json()["content"]


# ---------------------------------------------------------------------------
# TC-1: Full dialog completion → 4 keys persisted
# ---------------------------------------------------------------------------

def test_full_dialog_persists_all_four_keys(client, sandbox_root):
    tenant_id = "tenant_t1b6_full"
    cfg_path = _seed_sandbox(sandbox_root, tenant_id)

    _walk_dream_dialog_to_confirm(client, tenant_id=tenant_id)

    # 6. Confirm — should trigger disk sync
    r = client.post("/api/management/chat", params={"message": "yes", "tenant_id": tenant_id})
    assert r.status_code == 200
    assert "已保存" in r.json()["content"]

    # Assert: config.json now has "dream" block with all 4 keys
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "dream" in saved, "config.json should gain a 'dream' block"
    dream = saved["dream"]
    assert set(dream.keys()) == {"trigger", "coverage", "risk_threshold", "canary"}, \
        f"expected exactly 4 dream keys, got {sorted(dream.keys())}"
    assert dream["trigger"] == "low_peak"
    assert dream["coverage"] == "all_squads"
    assert dream["risk_threshold"] == 0.3
    assert dream["canary"] == "10_30_100"

    # Pre-existing keys preserved
    assert saved["tenant_id"] == tenant_id
    assert saved["brand_name"] == "testco"


# ---------------------------------------------------------------------------
# TC-2: Partial dialog (only some steps) → no disk write
# ---------------------------------------------------------------------------

def test_partial_dialog_does_not_write(client, sandbox_root):
    tenant_id = "tenant_t1b6_partial"
    cfg_path = _seed_sandbox(sandbox_root, tenant_id)
    baseline = cfg_path.read_text(encoding="utf-8")

    # Start and answer only 2 of 4 steps
    client.post("/api/management/chat", params={"message": "/dream-config", "tenant_id": tenant_id})
    client.post("/api/management/chat", params={"message": "1", "tenant_id": tenant_id})
    client.post("/api/management/chat", params={"message": "1", "tenant_id": tenant_id})

    # No confirmation reached — config.json must be unchanged
    assert cfg_path.read_text(encoding="utf-8") == baseline, \
        "partial dialog must NOT modify config.json on disk"


# ---------------------------------------------------------------------------
# TC-3: Cancellation at CONFIRM → no disk write
# ---------------------------------------------------------------------------

def test_cancel_at_confirm_does_not_write(client, sandbox_root):
    tenant_id = "tenant_t1b6_cancel"
    cfg_path = _seed_sandbox(sandbox_root, tenant_id)
    baseline = cfg_path.read_text(encoding="utf-8")

    _walk_dream_dialog_to_confirm(client, tenant_id=tenant_id)

    # User says "no" — dialog returns is_complete=True but via _reset (→ IDLE)
    r = client.post("/api/management/chat", params={"message": "no", "tenant_id": tenant_id})
    assert "取消" in r.json()["content"]

    # config.json must be unchanged (sync must NOT fire on cancel)
    assert cfg_path.read_text(encoding="utf-8") == baseline, \
        "cancelled dialog must NOT modify config.json on disk"


# ---------------------------------------------------------------------------
# TC-4: Re-run dialog overwrites dream block, preserves other keys
# ---------------------------------------------------------------------------

def test_rerun_overwrites_dream_preserves_other_keys(client, sandbox_root):
    tenant_id = "tenant_t1b6_rerun"
    base = {
        "tenant_id": tenant_id,
        "brand_name": "testco",
        "industry": "ecommerce",
        "status": "sandbox",
        "compliance": {"some_rule": "preserved"},
        "channels": ["web"],
    }
    cfg_path = _seed_sandbox(sandbox_root, tenant_id, base_config=base)

    # First run
    _walk_dream_dialog_to_confirm(client, tenant_id=tenant_id)
    client.post("/api/management/chat", params={"message": "yes", "tenant_id": tenant_id})

    first = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert first["dream"]["trigger"] == "low_peak"
    # Unrelated keys preserved
    assert first["compliance"] == {"some_rule": "preserved"}
    assert first["channels"] == ["web"]

    # Second run — override trigger to manual (option 3)
    client.post("/api/management/chat", params={"message": "/dream-config", "tenant_id": tenant_id})
    client.post("/api/management/chat", params={"message": "3", "tenant_id": tenant_id})  # manual
    client.post("/api/management/chat", params={"message": "2", "tenant_id": tenant_id})  # high_volume
    client.post("/api/management/chat", params={"message": "0.5", "tenant_id": tenant_id})
    client.post("/api/management/chat", params={"message": "2", "tenant_id": tenant_id})  # 5_25_100
    client.post("/api/management/chat", params={"message": "yes", "tenant_id": tenant_id})

    second = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert second["dream"]["trigger"] == "manual"
    assert second["dream"]["coverage"] == "high_volume"
    assert second["dream"]["risk_threshold"] == 0.5
    assert second["dream"]["canary"] == "5_25_100"
    # Unrelated keys still preserved after overwrite
    assert second["compliance"] == {"some_rule": "preserved"}
    assert second["channels"] == ["web"]


# ---------------------------------------------------------------------------
# TC-5: Missing sandbox dir → graceful skip (no exception, no rogue files)
# ---------------------------------------------------------------------------

def test_missing_sandbox_dir_skips_gracefully(client, sandbox_root):
    tenant_id = "tenant_t1b6_missing"  # no sandbox seeded
    assert not (sandbox_root / tenant_id).exists()

    _walk_dream_dialog_to_confirm(client, tenant_id=tenant_id)
    r = client.post("/api/management/chat", params={"message": "yes", "tenant_id": tenant_id})
    # Endpoint must still succeed; sync silently skipped
    assert r.status_code == 200
    assert "已保存" in r.json()["content"]

    # No config.json was created under the non-existent sandbox dir
    assert not (sandbox_root / tenant_id).exists(), \
        "missing sandbox dir must stay missing (no auto-create)"


# ---------------------------------------------------------------------------
# TC-6: DreamConfigSession read path unchanged (in-memory still authoritative)
# ---------------------------------------------------------------------------

def test_in_memory_read_path_unchanged(client, sandbox_root):
    """After a confirmed sync, session.get_config() still returns in-memory
    params without re-reading from disk. Guards against accidentally adding a
    read path that tries to lazily load from config.json.dream."""
    from autoservice.api_routes import _get_dream_session

    tenant_id = "tenant_t1b6_readpath"
    _seed_sandbox(sandbox_root, tenant_id)

    _walk_dream_dialog_to_confirm(client, tenant_id=tenant_id)
    client.post("/api/management/chat", params={"message": "yes", "tenant_id": tenant_id})

    session = _get_dream_session()
    cfg = session.get_config()
    # In-memory config populated by the state machine, independent of disk
    assert cfg["trigger"] == "low_peak"
    assert cfg["coverage"] == "all_squads"
    assert cfg["risk_threshold"] == 0.3
    assert cfg["canary"] == "10_30_100"
