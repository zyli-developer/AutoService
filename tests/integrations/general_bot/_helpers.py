"""Shared route-test helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoservice.integrations.general_bot.auth import _hash_key, KEY_FILE_NAME


def seed_api_key(sandbox: Path, tenant_id: str, raw: str = "test_key_xyz") -> str:
    import json
    entry = {
        "key_id": "k_test",
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
        "label": "test",
    }
    tdir = sandbox / ".autoservice" / "sandbox" / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / KEY_FILE_NAME).write_text(json.dumps([entry]), encoding="utf-8")
    # Also seed a config.json marker so tenant_resolver accepts the tid
    (tdir / "config.json").write_text("{}", encoding="utf-8")
    return raw


def parse_sse_events(body_bytes: bytes) -> list[dict | str]:
    """Decode an SSE response body into a list of events.

    `data:` lines → dicts (JSON-parsed). `:` comment lines → the comment string.
    """
    import json
    out: list[Any] = []
    for chunk in body_bytes.split(b"\n\n"):
        if not chunk:
            continue
        chunk_s = chunk.decode("utf-8").strip()
        if chunk_s.startswith(":"):
            out.append(chunk_s)
        elif chunk_s.startswith("data:"):
            payload = chunk_s[len("data:"):].strip()
            out.append(json.loads(payload))
    return out
