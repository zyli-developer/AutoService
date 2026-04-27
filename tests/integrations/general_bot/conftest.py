"""Shared fixtures for general_bot tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sandbox_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point bootstrap at a temp project root so api_keys.json writes
    don't pollute the real .autoservice/ folder."""
    root = tmp_path / "project"
    (root / ".autoservice" / "sandbox").mkdir(parents=True)
    monkeypatch.setattr(
        "autoservice.bootstrap.PROJECT_ROOT", root,
    )
    return root
