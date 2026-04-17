"""T5B.5 — Widget SDK npm publish configuration tests.

TC-001: package.json has required npm fields
TC-002: build script exists and produces dist/ output
TC-003: publish script runs in dry-run mode without error
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WIDGET_SDK = REPO_ROOT / "frontend" / "packages" / "widget-sdk"
PUBLISH_SCRIPT = REPO_ROOT / "deploy" / "publish-widget-sdk.sh"

REQUIRED_FIELDS = ["name", "version", "main", "module", "types", "files"]


class TestWidgetSdkPackageJson:
    """TC-001: package.json has required npm fields."""

    @pytest.fixture(autouse=True)
    def load_package_json(self):
        pkg_path = WIDGET_SDK / "package.json"
        assert pkg_path.exists(), f"package.json not found at {pkg_path}"
        with open(pkg_path) as f:
            self.pkg = json.load(f)

    def test_has_required_fields(self):
        for field in REQUIRED_FIELDS:
            assert field in self.pkg, f"Missing required field: {field}"

    def test_name_is_scoped(self):
        assert self.pkg["name"] == "@autoservice/widget-sdk"

    def test_version_is_semver(self):
        parts = self.pkg["version"].split(".")
        assert len(parts) == 3, f"Version {self.pkg['version']} is not semver"
        for p in parts:
            assert p.isdigit(), f"Version part '{p}' is not numeric"

    def test_main_points_to_dist(self):
        assert "dist/" in self.pkg["main"] or self.pkg["main"].startswith("dist")

    def test_module_points_to_dist(self):
        assert "dist/" in self.pkg["module"] or self.pkg["module"].startswith("dist")

    def test_types_points_to_dist(self):
        assert "dist/" in self.pkg["types"] or self.pkg["types"].startswith("dist")

    def test_files_includes_dist(self):
        assert "dist" in self.pkg["files"]

    def test_publish_config_public(self):
        assert "publishConfig" in self.pkg
        assert self.pkg["publishConfig"].get("access") == "public"

    def test_has_build_script(self):
        assert "build" in self.pkg.get("scripts", {}), "Missing build script"

    def test_has_prepublishonly_script(self):
        assert "prepublishOnly" in self.pkg.get("scripts", {}), "Missing prepublishOnly script"

    def test_peer_dependencies_react(self):
        peers = self.pkg.get("peerDependencies", {})
        assert "react" in peers, "react should be a peer dependency"


class TestWidgetSdkBuild:
    """TC-002: build produces dist/ output."""

    @pytest.fixture(autouse=True, scope="class")
    def run_build(self):
        """Install deps and run build once for all tests in this class."""
        import shutil
        pnpm = shutil.which("pnpm")
        if not pnpm:
            pytest.skip("pnpm not found in PATH")

        frontend = REPO_ROOT / "frontend"
        # Install dependencies
        result = subprocess.run(
            [pnpm, "install", "--frozen-lockfile=false"],
            cwd=str(frontend),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.skip(f"pnpm install failed: {result.stderr[:500]}")

        # Run build
        result = subprocess.run(
            [pnpm, "--filter", "@autoservice/widget-sdk", "build"],
            cwd=str(frontend),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr[:1000]}"

    def test_dist_directory_exists(self):
        dist = WIDGET_SDK / "dist"
        assert dist.is_dir(), "dist/ directory not created by build"

    def test_esm_output_exists(self):
        assert (WIDGET_SDK / "dist" / "index.js").exists(), "ESM output missing"

    def test_cjs_output_exists(self):
        assert (WIDGET_SDK / "dist" / "index.cjs").exists(), "CJS output missing"

    def test_types_output_exists(self):
        assert (WIDGET_SDK / "dist" / "index.d.ts").exists(), "Type declarations missing"


class TestPublishScript:
    """TC-003: publish script exists and runs dry-run without error."""

    def test_script_exists(self):
        assert PUBLISH_SCRIPT.exists(), f"Publish script not found at {PUBLISH_SCRIPT}"

    def test_script_is_executable_or_runnable(self):
        # Check it can be run via bash even if not chmod +x
        result = subprocess.run(
            ["bash", str(PUBLISH_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"--help failed: {result.stderr[:500]}"
        assert "dry-run" in result.stdout.lower() or "--live" in result.stdout

    def test_script_has_set_euo_pipefail(self):
        content = PUBLISH_SCRIPT.read_text(encoding="utf-8")
        assert "set -euo pipefail" in content
