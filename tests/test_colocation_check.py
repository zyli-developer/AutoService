"""Tests for NFR-4 co-location check script (deploy/check-colocation.sh).

T5B.2 | 2026-04-16
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "check-colocation.sh"


def write_compose(path: Path, network_mode: str | None = None, bridges: bool = True) -> None:
    """Write a minimal docker-compose YAML for testing."""
    bridges_section = ""
    if bridges:
        nm_line = f'    network_mode: "{network_mode}"' if network_mode else ""
        bridges_section = textwrap.dedent(f"""\
          bridges:
            image: "zchat:latest"
        {nm_line}
            depends_on:
              channel-server:
                condition: service_healthy
        """)

    content = textwrap.dedent(f"""\
        version: "3.9"
        services:
          channel-server:
            image: "zchat:latest"
            ports:
              - "9999:9999"
          {bridges_section}
    """)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run_check(*args: str, script_dir: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if script_dir:
        env["SCRIPT_DIR"] = script_dir
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestCoLocationCheck:
    """Tests for deploy/check-colocation.sh."""

    def test_help_flag(self):
        result = run_check("--help")
        assert result.returncode == 0
        assert "NFR-4" in result.stdout

    def test_pass_valid_template(self, tmp_path: Path):
        compose = tmp_path / "docker-compose.tmpl.yaml"
        write_compose(compose, network_mode="service:channel-server")
        result = run_check("--file", str(compose))
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_fail_wrong_network_mode(self, tmp_path: Path):
        compose = tmp_path / "docker-compose.yml"
        write_compose(compose, network_mode="bridge")
        result = run_check("--file", str(compose))
        assert result.returncode == 1
        assert "FAIL" in result.stdout

    def test_fail_missing_network_mode(self, tmp_path: Path):
        compose = tmp_path / "docker-compose.yml"
        write_compose(compose, network_mode=None)
        result = run_check("--file", str(compose))
        assert result.returncode == 1
        assert "FAIL" in result.stdout

    def test_pass_real_template(self):
        """Verify the actual project template passes."""
        result = run_check("--file", str(REPO_ROOT / "deploy" / "docker-compose.tmpl.yaml"))
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_scan_tenants_dir(self, tmp_path: Path):
        """Verify scanning deploy dir with tenants/ subdirectory."""
        # Create a fake deploy dir structure
        tmpl = tmp_path / "docker-compose.tmpl.yaml"
        write_compose(tmpl, network_mode="service:channel-server")

        tenant_dir = tmp_path / "tenants" / "demo"
        tenant_compose = tenant_dir / "docker-compose.yml"
        write_compose(tenant_compose, network_mode="service:channel-server")

        result = run_check(script_dir=str(tmp_path))
        assert result.returncode == 0
        assert "All co-location checks passed" in result.stdout

    def test_scan_tenants_catches_violation(self, tmp_path: Path):
        """One bad tenant should fail the whole check."""
        tmpl = tmp_path / "docker-compose.tmpl.yaml"
        write_compose(tmpl, network_mode="service:channel-server")

        good = tmp_path / "tenants" / "good" / "docker-compose.yml"
        write_compose(good, network_mode="service:channel-server")

        bad = tmp_path / "tenants" / "bad" / "docker-compose.yml"
        write_compose(bad, network_mode="host")

        result = run_check(script_dir=str(tmp_path))
        assert result.returncode == 1
        assert "VIOLATION" in result.stdout
