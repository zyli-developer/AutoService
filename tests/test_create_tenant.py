"""Tests for T5B.3 create-tenant.sh — tenant creation script."""
from __future__ import annotations

import os
import subprocess
import pytest
import yaml
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent.parent / "deploy"
SCRIPT = DEPLOY_DIR / "create-tenant.sh"


def run_script(*args, check=True, env_override=None):
    """Run create-tenant.sh with given arguments."""
    env = {**os.environ}
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Script failed (rc={result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    return result


@pytest.fixture
def tenant_env(tmp_path):
    """Set up a temporary deploy directory for isolated tests.

    Copies templates into tmp_path/deploy/ and sets SCRIPT_DIR env var
    so the script operates in the temp directory.
    """
    # Copy templates to temp dir
    deploy_tmp = tmp_path / "deploy"
    deploy_tmp.mkdir()
    (deploy_tmp / ".env.tmpl").write_text((DEPLOY_DIR / ".env.tmpl").read_text())
    (deploy_tmp / "docker-compose.tmpl.yaml").write_text(
        (DEPLOY_DIR / "docker-compose.tmpl.yaml").read_text()
    )

    def run_script_in_tmp(*args, **kwargs):
        env = {**os.environ, "SCRIPT_DIR": str(deploy_tmp)}
        env.update(kwargs.pop("env_override", {}))
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True, text=True, env=env,
            **kwargs,
        )

    return {
        "deploy_dir": deploy_tmp,
        "tmp_path": tmp_path,
        "run": run_script_in_tmp,
    }


# ---------------------------------------------------------------------------
# TC-001: Creates tenant directory structure
# ---------------------------------------------------------------------------

def test_tc001_creates_tenant_directory_structure(tenant_env):
    """TC-001: create-tenant.sh creates the expected directory structure."""
    result = tenant_env["run"](
        "--tenant", "acme",
        "--port-offset", "100",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "acme"),
    )
    assert result.returncode == 0, f"Script failed:\n{result.stderr}"

    tenant_dir = tenant_env["deploy_dir"] / "tenants" / "acme"
    data_dir = tenant_env["tmp_path"] / "data" / "acme"

    assert tenant_dir.is_dir(), f"Tenant dir not created: {tenant_dir}"
    assert (tenant_dir / ".env").is_file(), ".env not created"
    assert (tenant_dir / "docker-compose.yml").is_file(), "docker-compose.yml not created"
    assert data_dir.is_dir(), f"Data dir not created: {data_dir}"


# ---------------------------------------------------------------------------
# TC-002: .env file has correct TENANT and PORT_OFFSET values
# ---------------------------------------------------------------------------

def test_tc002_env_file_has_correct_values(tenant_env):
    """TC-002: rendered .env contains correct TENANT and PORT_OFFSET."""
    tenant_env["run"](
        "--tenant", "beta",
        "--port-offset", "200",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "beta"),
    )

    env_file = tenant_env["deploy_dir"] / "tenants" / "beta" / ".env"
    content = env_file.read_text()

    # Check key values
    lines = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in content.splitlines() if "=" in l and not l.startswith("#")}

    assert lines.get("TENANT") == "beta", f"TENANT mismatch: {lines.get('TENANT')}"
    assert lines.get("PORT_OFFSET") == "200", f"PORT_OFFSET mismatch: {lines.get('PORT_OFFSET')}"
    assert lines.get("PORT_OFFSET_9999") == "10199", f"PORT_OFFSET_9999 mismatch: {lines.get('PORT_OFFSET_9999')}"
    assert lines.get("PORT_OFFSET_5173") == "5373", f"PORT_OFFSET_5173 mismatch: {lines.get('PORT_OFFSET_5173')}"
    assert lines.get("DEMO_PORT") == "8200", f"DEMO_PORT mismatch: {lines.get('DEMO_PORT')}"


# ---------------------------------------------------------------------------
# TC-003: docker-compose.yml is valid YAML after rendering
# ---------------------------------------------------------------------------

def test_tc003_compose_is_valid_yaml(tenant_env):
    """TC-003: rendered docker-compose.yml is valid YAML with expected services."""
    tenant_env["run"](
        "--tenant", "gamma",
        "--port-offset", "300",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "gamma"),
    )

    compose_file = tenant_env["deploy_dir"] / "tenants" / "gamma" / "docker-compose.yml"
    compose = yaml.safe_load(compose_file.read_text())

    assert compose is not None, "YAML parsed to None"
    services = compose.get("services", {})
    assert len(services) == 6, f"Expected 6 services, got {len(services)}"

    raw = compose_file.read_text()
    assert "${" not in raw, "Unresolved envsubst variables found"

    # Verify tenant label
    for svc_name, svc in services.items():
        if "labels" in svc:
            labels = svc["labels"]
            assert labels.get("app.autoservice/tenant") == "gamma", \
                f"Service {svc_name} has wrong tenant label"


# ---------------------------------------------------------------------------
# TC-004: Port conflict detection works
# ---------------------------------------------------------------------------

def test_tc004_port_conflict_detection(tenant_env):
    """TC-004: creating two tenants with same port-offset fails."""
    # Create first tenant
    result1 = tenant_env["run"](
        "--tenant", "first",
        "--port-offset", "100",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "first"),
    )
    assert result1.returncode == 0, f"First tenant failed:\n{result1.stderr}"

    # Try creating second tenant with same port offset
    result2 = tenant_env["run"](
        "--tenant", "second",
        "--port-offset", "100",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "second"),
    )
    assert result2.returncode != 0, "Should have failed due to port conflict"
    assert "CONFLICT" in result2.stderr or "conflict" in result2.stderr.lower(), \
        f"Expected conflict message, got: {result2.stderr}"


# ---------------------------------------------------------------------------
# TC-005: Idempotent — running twice doesn't break anything
# ---------------------------------------------------------------------------

def test_tc005_idempotent_rerun(tenant_env):
    """TC-005: running create-tenant twice for same tenant succeeds."""
    args = [
        "--tenant", "idem",
        "--port-offset", "400",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "idem"),
    ]

    # First run
    r1 = tenant_env["run"](*args)
    assert r1.returncode == 0, f"First run failed:\n{r1.stderr}"

    # Get content after first run
    env_path = tenant_env["deploy_dir"] / "tenants" / "idem" / ".env"
    content1 = env_path.read_text()

    # Second run
    r2 = tenant_env["run"](*args)
    assert r2.returncode == 0, f"Second run failed:\n{r2.stderr}"

    # Content should be the same
    content2 = env_path.read_text()
    assert content1 == content2, "Re-run produced different .env content"


# ---------------------------------------------------------------------------
# TC-006: --help flag shows usage
# ---------------------------------------------------------------------------

def test_tc006_help_flag():
    """TC-006: --help shows usage and exits 0."""
    result = run_script("--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--tenant" in result.stdout
    assert "--port-offset" in result.stdout
    assert "--dry-run" in result.stdout


# ---------------------------------------------------------------------------
# TC-007: --dry-run does not create files
# ---------------------------------------------------------------------------

def test_tc007_dry_run_no_files(tenant_env):
    """TC-007: --dry-run shows plan but creates no files."""
    result = tenant_env["run"](
        "--tenant", "drytest",
        "--port-offset", "500",
        "--data-dir", str(tenant_env["tmp_path"] / "data" / "drytest"),
        "--dry-run",
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout

    tenant_dir = tenant_env["deploy_dir"] / "tenants" / "drytest"
    assert not tenant_dir.exists(), "Dry run should not create tenant directory"


# ---------------------------------------------------------------------------
# TC-008: Invalid tenant name rejected
# ---------------------------------------------------------------------------

def test_tc008_invalid_tenant_name():
    """TC-008: invalid tenant names are rejected."""
    result = run_script("--tenant", "bad name!", "--port-offset", "0", check=False)
    assert result.returncode != 0
    assert "alphanumeric" in result.stderr.lower() or "ERROR" in result.stderr


# ---------------------------------------------------------------------------
# TC-009: Missing required args
# ---------------------------------------------------------------------------

def test_tc009_missing_required_args():
    """TC-009: script fails when required args are missing."""
    # Missing --port-offset
    r1 = run_script("--tenant", "test", check=False)
    assert r1.returncode != 0

    # Missing --tenant
    r2 = run_script("--port-offset", "0", check=False)
    assert r2.returncode != 0

    # No args at all
    r3 = run_script(check=False)
    assert r3.returncode != 0
