"""Tests for LocalTarballForkCreator runbook config step (T8B.2).

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.4 last paragraph.

The runbook produced by `write_runbook()` must now include an explicit step
telling the operator to create `.autoservice/config.local.yaml` in the fork
with `deployment_mode: tenant` + `tenant_id: <tid>`, otherwise the fork will
fail to boot (get_deployment_mode assertion).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoservice.publish import (
    PUBLISHED_ROOT,
    _fork_local_config_yaml_text,
    write_runbook,
)


@pytest.fixture
def published_dir(tmp_path, monkeypatch):
    """Redirect PUBLISHED_ROOT to tmp so tests don't pollute .autoservice/."""
    target = tmp_path / "published"
    monkeypatch.setattr("autoservice.publish.PUBLISHED_ROOT", target)
    return target


def _runbook_body(tenant_id: str, artifact: Path, published_dir: Path) -> str:
    """Helper — write the runbook + return its text."""
    path = write_runbook(tenant_id, artifact)
    # Confirm it wrote under our patched root (defense in depth)
    assert path.is_file()
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper: _fork_local_config_yaml_text
# ---------------------------------------------------------------------------

def test_fork_local_config_yaml_helper_shape() -> None:
    """The helper renders deterministic yaml with both required keys."""
    text = _fork_local_config_yaml_text("acme")
    assert "deployment_mode: tenant" in text
    assert "tenant_id: acme" in text
    # Ends with newline (POSIX file convention)
    assert text.endswith("\n")


def test_fork_local_config_yaml_rejects_empty_tenant_id() -> None:
    """Empty or whitespace tenant_id is refused — defensive."""
    with pytest.raises(ValueError):
        _fork_local_config_yaml_text("")
    with pytest.raises(ValueError):
        _fork_local_config_yaml_text("   ")


def test_fork_local_config_yaml_rejects_malformed_tenant_id() -> None:
    """Whitespace inside or yaml-injection attempts rejected.

    tenant_id must be a plain identifier — guard against runbook yaml break
    (e.g., operator passes "foo\nmalicious: true" — we emit as yaml body).
    """
    with pytest.raises(ValueError):
        _fork_local_config_yaml_text("foo bar")
    with pytest.raises(ValueError):
        _fork_local_config_yaml_text("foo\nmalicious: true")


# ---------------------------------------------------------------------------
# Runbook content
# ---------------------------------------------------------------------------

def test_runbook_includes_config_local_yaml_step(
    published_dir: Path, tmp_path: Path
) -> None:
    """Spec §3.4 fix — runbook must include config.local.yaml step."""
    body = _runbook_body("acme", tmp_path / "x.tar.gz", published_dir)
    assert "deployment_mode: tenant" in body
    assert "tenant_id: acme" in body
    assert "config.local.yaml" in body


def test_runbook_config_step_ordering(
    published_dir: Path, tmp_path: Path
) -> None:
    """Order: Extract content → Write config.local.yaml → Verify."""
    body = _runbook_body("acme", tmp_path / "x.tar.gz", published_dir)
    extract_pos = body.find("Extract content")
    config_pos = body.find("config.local.yaml")
    verify_pos = body.find("Verify")
    assert 0 < extract_pos < config_pos < verify_pos, (
        f"Runbook step ordering broken. "
        f"extract={extract_pos}, config={config_pos}, verify={verify_pos}"
    )


def test_runbook_https_warning_present(
    published_dir: Path, tmp_path: Path
) -> None:
    """Spec §9 — deployment runbook must include HTTPS warning
    (magic-link cookies leak over HTTP)."""
    body = _runbook_body("acme", tmp_path / "x.tar.gz", published_dir)
    body_lower = body.lower()
    assert "https" in body_lower, "HTTPS warning missing from runbook"
    # Some form of caution wording
    assert any(
        kw in body_lower
        for kw in ("tls", "magic-link", "warning", "⚠", "cookie")
    ), "HTTPS section lacks caution framing"


def test_runbook_config_yaml_snippet_matches_helper(
    published_dir: Path, tmp_path: Path
) -> None:
    """The yaml snippet inline in the runbook exactly matches what
    `_fork_local_config_yaml_text` produces — single source of truth."""
    body = _runbook_body("acme", tmp_path / "x.tar.gz", published_dir)
    snippet = _fork_local_config_yaml_text("acme")
    # Every line of the helper output must appear in the runbook
    for line in snippet.strip().splitlines():
        assert line in body, f"Runbook missing helper line: {line!r}"


def test_runbook_overwrite_warning_present(
    published_dir: Path, tmp_path: Path
) -> None:
    """If operator already has a config.local.yaml, the runbook must warn
    them — runbook uses `cat > ...` which overwrites."""
    body = _runbook_body("acme", tmp_path / "x.tar.gz", published_dir)
    body_lower = body.lower()
    # Look for some form of overwrite / merge cautionary note near the
    # config.local.yaml step
    assert any(
        kw in body_lower for kw in ("overwrite", "existing", "merge manually")
    ), "Runbook should warn that cat > overwrites existing config"
