"""Tests for ``autoservice.sandbox_gc`` (M3 T4S.5).

Contract: docs/contracts/m3/e6-ops-gc-playwright.md §2.1.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoservice.sandbox_gc import GCReport, run_gc


def _seed_sandbox(
    root: Path, tenant_id: str, *, status="sandbox",
    ttl_days=None, mtime_days_ago=0,
) -> Path:
    """Create a sandbox dir with config.json, set mtime to `mtime_days_ago`."""
    sbox = root / tenant_id
    sbox.mkdir(parents=True, exist_ok=True)
    cfg = {"tenant_id": tenant_id, "status": status}
    if ttl_days is not None:
        cfg["sandbox_ttl_days"] = ttl_days
    (sbox / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    if mtime_days_ago:
        target = datetime.now(tz=timezone.utc) - timedelta(days=mtime_days_ago)
        ts = target.timestamp()
        os.utime(sbox, (ts, ts))
    return sbox


@pytest.fixture()
def sandbox_root(tmp_path, monkeypatch):
    """Isolated sandbox_root + archived_root so GC tests don't touch disk."""
    sandbox_dir = tmp_path / "sandbox"
    archived_dir = tmp_path / "archived"
    sandbox_dir.mkdir()
    archived_dir.mkdir()

    import autoservice.publish as publish
    monkeypatch.setattr(publish, "SANDBOX_ROOT", sandbox_dir)
    monkeypatch.setattr(publish, "ARCHIVED_ROOT", archived_dir)
    # sandbox_gc imports SANDBOX_ROOT at module load — patch there too
    import autoservice.sandbox_gc as gc_mod
    monkeypatch.setattr(gc_mod, "SANDBOX_ROOT", sandbox_dir)
    monkeypatch.setattr(gc_mod, "ARCHIVED_ROOT", archived_dir)
    return sandbox_dir


# ──────────────────────────────────────────────────────────────────────────
# Empty / missing sandbox root
# ──────────────────────────────────────────────────────────────────────────


def test_empty_sandbox_returns_empty_report(sandbox_root):
    report = run_gc(sandbox_root=sandbox_root)
    assert isinstance(report, GCReport)
    assert report.scanned_count == 0
    assert report.archived == []
    assert report.errors == []


# ──────────────────────────────────────────────────────────────────────────
# Age filtering
# ──────────────────────────────────────────────────────────────────────────


def test_fresh_sandbox_skipped(sandbox_root):
    _seed_sandbox(sandbox_root, "fresh-corp", mtime_days_ago=5)
    report = run_gc(sandbox_root=sandbox_root, default_ttl_days=30)
    assert report.archived == []
    assert "fresh-corp" in report.skipped_fresh


def test_stale_sandbox_archived(sandbox_root):
    _seed_sandbox(sandbox_root, "stale-corp", mtime_days_ago=45)
    report = run_gc(sandbox_root=sandbox_root, default_ttl_days=30)
    assert "stale-corp" in report.archived
    # Original dir no longer exists
    assert not (sandbox_root / "stale-corp").exists()


def test_exactly_at_threshold_archived(sandbox_root):
    _seed_sandbox(sandbox_root, "edge-corp", mtime_days_ago=30)
    report = run_gc(sandbox_root=sandbox_root, default_ttl_days=30)
    # age >= ttl → archive
    assert "edge-corp" in report.archived


# ──────────────────────────────────────────────────────────────────────────
# Published tenants protected
# ──────────────────────────────────────────────────────────────────────────


def test_published_tenant_never_archived_even_when_old(sandbox_root):
    _seed_sandbox(
        sandbox_root, "prod-corp", status="published", mtime_days_ago=365,
    )
    report = run_gc(sandbox_root=sandbox_root)
    assert "prod-corp" in report.skipped_published
    assert "prod-corp" not in report.archived
    assert (sandbox_root / "prod-corp").exists()


# ──────────────────────────────────────────────────────────────────────────
# Per-tenant TTL override
# ──────────────────────────────────────────────────────────────────────────


def test_tenant_ttl_override_respected(sandbox_root):
    # Tenant with 60-day override; default is 30
    _seed_sandbox(
        sandbox_root, "vip-corp", ttl_days=60, mtime_days_ago=45,
    )
    report = run_gc(sandbox_root=sandbox_root, default_ttl_days=30)
    # 45 days old < 60-day override → skip
    assert "vip-corp" in report.skipped_fresh
    assert (sandbox_root / "vip-corp").exists()


def test_tenant_ttl_override_shorter_than_default(sandbox_root):
    _seed_sandbox(
        sandbox_root, "short-corp", ttl_days=7, mtime_days_ago=10,
    )
    report = run_gc(sandbox_root=sandbox_root, default_ttl_days=30)
    # 10 days old > 7-day override → archive
    assert "short-corp" in report.archived


def test_invalid_ttl_override_recorded_as_error(sandbox_root):
    _seed_sandbox(
        sandbox_root, "bad-ttl", ttl_days="not-a-number", mtime_days_ago=45,
    )
    report = run_gc(sandbox_root=sandbox_root)
    assert any(tid == "bad-ttl" for tid, _ in report.errors)
    # Not archived — error blocks the transition
    assert "bad-ttl" not in report.archived


def test_zero_ttl_override_rejected(sandbox_root):
    _seed_sandbox(
        sandbox_root, "zero-ttl", ttl_days=0, mtime_days_ago=1,
    )
    report = run_gc(sandbox_root=sandbox_root)
    assert any(tid == "zero-ttl" for tid, _ in report.errors)


# ──────────────────────────────────────────────────────────────────────────
# Dry run
# ──────────────────────────────────────────────────────────────────────────


def test_dry_run_decides_but_does_not_archive(sandbox_root):
    _seed_sandbox(sandbox_root, "will-be-archived", mtime_days_ago=45)
    report = run_gc(sandbox_root=sandbox_root, dry_run=True)
    assert "will-be-archived" in report.archived  # decision recorded
    assert report.dry_run is True
    # But dir still present
    assert (sandbox_root / "will-be-archived").exists()


# ──────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────


def test_running_gc_twice_is_safe(sandbox_root):
    _seed_sandbox(sandbox_root, "a", mtime_days_ago=45)
    _seed_sandbox(sandbox_root, "b", mtime_days_ago=5)

    r1 = run_gc(sandbox_root=sandbox_root)
    assert "a" in r1.archived
    assert "b" in r1.skipped_fresh

    # Second run — "a" is gone, "b" still fresh
    r2 = run_gc(sandbox_root=sandbox_root)
    assert r2.archived == []
    assert "b" in r2.skipped_fresh


# ──────────────────────────────────────────────────────────────────────────
# Error isolation
# ──────────────────────────────────────────────────────────────────────────


def test_single_bad_tenant_does_not_halt_full_scan(sandbox_root):
    # "good-corp" is stale + valid; "bad-corp" has bad TTL
    _seed_sandbox(sandbox_root, "good-corp", mtime_days_ago=45)
    _seed_sandbox(sandbox_root, "bad-corp", ttl_days=0, mtime_days_ago=10)

    report = run_gc(sandbox_root=sandbox_root)
    # Good one archived
    assert "good-corp" in report.archived
    # Bad one reported as error
    assert any(tid == "bad-corp" for tid, _ in report.errors)


def test_sandbox_without_config_json_skipped(sandbox_root):
    """Sandbox dir missing config.json → skipped (not error, just incomplete)."""
    (sandbox_root / "no-config").mkdir()
    report = run_gc(sandbox_root=sandbox_root)
    assert "no-config" in report.skipped_fresh
    assert not any(tid == "no-config" for tid, _ in report.errors)


def test_dotfiles_ignored(sandbox_root):
    """Hidden dirs starting with '.' are not sandboxes (system dirs)."""
    (sandbox_root / ".hidden").mkdir()
    report = run_gc(sandbox_root=sandbox_root)
    assert report.scanned_count == 0


# ──────────────────────────────────────────────────────────────────────────
# Deterministic clock
# ──────────────────────────────────────────────────────────────────────────


def test_clock_injection_makes_ttl_deterministic(sandbox_root):
    _seed_sandbox(sandbox_root, "t1", mtime_days_ago=20)
    t_now = datetime.now(tz=timezone.utc)
    fake_future = t_now + timedelta(days=20)  # now pretend another 20 days passed
    report = run_gc(
        sandbox_root=sandbox_root, now=fake_future, default_ttl_days=30
    )
    # Effective age from sandbox perspective: 20 (real) + 20 (fake) = 40 > 30
    assert "t1" in report.archived
