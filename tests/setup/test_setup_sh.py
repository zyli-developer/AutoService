"""Subprocess tests for scripts/setup.sh (T7S.4, spec §3.5).

Each test sets up an isolated project layout in tmp_path, copies
scripts/setup.sh into it, and runs the script via bash. We do not touch
the real repo layout — only the temporary one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = PROJECT_ROOT / "scripts" / "setup.sh"


def _bash_exe() -> str:
    """Return bash executable path; prefer Git-Bash on Windows."""
    which = shutil.which("bash")
    if which:
        return which
    # Common Git-for-Windows locations.
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    pytest.skip("bash not available on PATH")
    return "bash"  # unreachable


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal AutoService-shaped project under tmp_path."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    (root / ".autoservice").mkdir()
    # Skill tree with two skills so plugin discovery has something to find.
    (root / "skills" / "alpha").mkdir(parents=True)
    (root / "skills" / "beta").mkdir()
    (root / "commands").mkdir()
    (root / "agents").mkdir()
    (root / "hooks").mkdir()
    (root / "plugins").mkdir()

    shutil.copy(SETUP_SH, root / "scripts" / "setup.sh")
    os.chmod(root / "scripts" / "setup.sh", 0o755)
    return root


def _run_setup(root: Path, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [_bash_exe(), "scripts/setup.sh"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_config(root: Path, body: str) -> None:
    (root / ".autoservice" / "config.local.yaml").write_text(body, encoding="utf-8")


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_fresh_install_defaults_to_master(tmp_path):
    """No config.local.yaml → master mode, runtime dirs created, exit 0."""
    root = _make_project(tmp_path)
    assert not (root / ".autoservice" / "config.local.yaml").exists()

    result = _run_setup(root)

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "deployment_mode=master" in result.stdout
    # Runtime dirs exist.
    for sub in ("logs", "data", "cache", "sandbox", "run", "database"):
        assert (root / ".autoservice" / sub).is_dir(), f"missing .autoservice/{sub}"


def test_explicit_master_mode(tmp_path):
    """Explicit deployment_mode: master behaves same as fresh install."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: master\ntenant_id: null\n")

    result = _run_setup(root)

    assert result.returncode == 0, result.stderr
    assert "deployment_mode=master" in result.stdout
    # .claude/skills should exist and point at ../skills (or be a copy).
    claude_skills = root / ".claude" / "skills"
    assert claude_skills.exists(), ".claude/skills should exist in master mode"
    # No per-tenant plugin dir magically appears.
    tenant_dirs = [p for p in (root / "plugins").iterdir() if p.is_dir()]
    assert tenant_dirs == [], f"unexpected plugins/ children in master: {tenant_dirs}"


def test_tenant_mode_requires_tenant_id(tmp_path):
    """deployment_mode=tenant without tenant_id exits non-zero with clear error."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: tenant\ntenant_id: null\n")

    result = _run_setup(root)

    assert result.returncode != 0, (
        f"expected non-zero exit; stdout={result.stdout} stderr={result.stderr}"
    )
    combined = (result.stderr + result.stdout).lower()
    assert "tenant_id" in combined, f"error should mention tenant_id: {combined}"


def test_tenant_mode_with_tenant_id(tmp_path):
    """deployment_mode=tenant + tenant_id creates plugins/<tid>/skills link."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: tenant\ntenant_id: foo\n")

    result = _run_setup(root)

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "deployment_mode=tenant" in result.stdout
    assert "tenant_id=foo" in result.stdout

    # plugins/foo/ and plugins/foo/skills exist.
    assert (root / "plugins" / "foo").is_dir()
    assert (root / "plugins" / "foo" / "skills").exists(), (
        "plugins/foo/skills should be linked/populated"
    )
    # Runtime dirs still created.
    assert (root / ".autoservice" / "logs").is_dir()


def test_idempotent_double_run(tmp_path):
    """Running setup twice in a row should both succeed with no stale links."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: master\n")

    first = _run_setup(root)
    assert first.returncode == 0, first.stderr

    second = _run_setup(root)
    assert second.returncode == 0, f"second run failed: {second.stderr}"

    # Should still have .claude/skills present after the second run.
    assert (root / ".claude" / "skills").exists()


def test_preserves_existing_sandbox_data(tmp_path):
    """Existing .autoservice/sandbox/ contents must survive setup."""
    root = _make_project(tmp_path)
    sandbox = root / ".autoservice" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    sentinel = sandbox / "keep-me.txt"
    sentinel.write_text("precious", encoding="utf-8")

    result = _run_setup(root)

    assert result.returncode == 0, result.stderr
    assert sentinel.exists(), "setup must not wipe .autoservice/sandbox/"
    assert sentinel.read_text(encoding="utf-8") == "precious"


def test_tenant_mode_skips_local_admin(tmp_path):
    """tenant mode plugin discovery must skip _local_admin."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: tenant\ntenant_id: foo\n")

    # Pre-create a tenant plugin tree with two skill dirs — one named
    # _local_admin (must be skipped), one regular.
    (root / "plugins" / "foo" / "skills" / "regular").mkdir(parents=True)
    (root / "plugins" / "foo" / "skills" / "_local_admin").mkdir()

    result = _run_setup(root)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    # Regular skill is linked back into skills/
    linked_regular = root / "skills" / "regular"
    assert linked_regular.exists(), "regular tenant plugin skill should be discovered"
    # _local_admin must NOT be linked.
    assert not (root / "skills" / "_local_admin").exists(), (
        "_local_admin must not be exposed as a skill"
    )


def test_master_mode_skips_example_plugin(tmp_path):
    """master mode plugin discovery must skip the _example plugin."""
    root = _make_project(tmp_path)
    _write_config(root, "deployment_mode: master\n")

    # Real plugin with a discoverable skill
    (root / "plugins" / "cinnox" / "skills" / "cinnox-demo").mkdir(parents=True)
    # _example plugin that should be skipped
    (root / "plugins" / "_example" / "skills" / "example-skill").mkdir(parents=True)

    result = _run_setup(root)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert (root / "skills" / "cinnox-demo").exists(), (
        "real plugin skills should be linked in master mode"
    )
    assert not (root / "skills" / "example-skill").exists(), (
        "_example plugin must be skipped in master mode"
    )
