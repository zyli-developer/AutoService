"""Per-tenant API key load + verify. Spec §5.

Storage: .autoservice/sandbox/<tenant_id>/api_keys.json
Schema:  [{"key_id","hash","created_at","revoked_at","label"}, ...]
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from autoservice import bootstrap

logger = logging.getLogger("autoservice.general_bot.auth")

KEY_FILE_NAME = "api_keys.json"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _keys_path(tenant_id: str) -> Path:
    return (
        bootstrap.PROJECT_ROOT
        / ".autoservice" / "sandbox" / tenant_id / KEY_FILE_NAME
    )


def _load_keys(tenant_id: str) -> list[dict]:
    path = _keys_path(tenant_id)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("api_keys.json parse failed for tenant=%s", tenant_id)
        return []


def verify_api_key(tenant_id: str, raw_key: str | None) -> bool:
    """Timing-safe verify of raw_key against any non-revoked entry."""
    if not raw_key or not isinstance(raw_key, str):
        return False
    expected_hash = _hash_key(raw_key)
    matched = False
    for entry in _load_keys(tenant_id):
        if entry.get("revoked_at"):
            continue
        stored = entry.get("hash") or ""
        # compare_digest still timing-safe even on length mismatch
        if secrets.compare_digest(expected_hash, stored):
            matched = True
            # do not break — keep loop time constant-ish across hits/misses
    return matched


def issue_key(tenant_id: str, *, label: str = "") -> tuple[str, str]:
    """Generate a new key, append hash to api_keys.json, return (raw, key_id).

    The raw key is returned ONCE. Caller is responsible for showing it to the
    operator who then shares it with the third-party platform; it is never
    stored server-side after this call.
    """
    raw = secrets.token_urlsafe(32)
    key_id = "k_" + secrets.token_hex(8)
    entry = {
        "key_id": key_id,
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
        "label": label,
    }
    path = _keys_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _load_keys(tenant_id)
    keys.append(entry)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return raw, key_id
