"""Per-tenant API key auth tests. Spec §5."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice.integrations.general_bot.auth import (
    KEY_FILE_NAME,
    issue_key,
    verify_api_key,
    _hash_key,
)


def _seed_keys(sandbox: Path, tid: str, *, key_id: str = "k1", revoked: bool = False) -> str:
    """Seed an api_keys.json with one entry; return raw key."""
    raw = "test_raw_key_" + key_id
    entry = {
        "key_id": key_id,
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": datetime.now(timezone.utc).isoformat() if revoked else None,
        "label": "test",
    }
    tdir = sandbox / ".autoservice" / "sandbox" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / KEY_FILE_NAME).write_text(json.dumps([entry]), encoding="utf-8")
    return raw


def test_verify_valid_key(sandbox_dir: Path):
    raw = _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", raw) is True


def test_verify_unknown_tenant_returns_false(sandbox_dir: Path):
    # No api_keys.json for tenant "ghost"
    assert verify_api_key("ghost", "anything") is False


def test_verify_wrong_key_returns_false(sandbox_dir: Path):
    _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", "wrong") is False


def test_verify_revoked_key_returns_false(sandbox_dir: Path):
    raw = _seed_keys(sandbox_dir, "tenantA", revoked=True)
    assert verify_api_key("tenantA", raw) is False


def test_verify_empty_key_returns_false(sandbox_dir: Path):
    _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", "") is False
    assert verify_api_key("tenantA", None) is False  # type: ignore[arg-type]


def test_issue_key_creates_file_and_returns_raw(sandbox_dir: Path):
    (sandbox_dir / ".autoservice" / "sandbox" / "tenantB").mkdir(parents=True)
    raw, key_id = issue_key("tenantB", label="cinnox-prod")
    assert isinstance(raw, str) and len(raw) >= 32
    assert key_id.startswith("k_")
    # Verify roundtrip
    assert verify_api_key("tenantB", raw) is True


def test_issue_key_appends_not_overwrites(sandbox_dir: Path):
    (sandbox_dir / ".autoservice" / "sandbox" / "tenantC").mkdir(parents=True)
    raw1, _ = issue_key("tenantC", label="first")
    raw2, _ = issue_key("tenantC", label="second")
    assert raw1 != raw2
    assert verify_api_key("tenantC", raw1) is True
    assert verify_api_key("tenantC", raw2) is True


def test_issue_key_creates_sandbox_dir_if_missing(sandbox_dir: Path):
    # Don't pre-create the sandbox/<tid>/ dir
    raw, _ = issue_key("tenantD", label="autocreate")
    assert verify_api_key("tenantD", raw) is True


def test_hash_is_sha256_hex(sandbox_dir: Path):
    h = _hash_key("hello")
    assert len(h) == 64
    int(h, 16)  # raises if not hex
