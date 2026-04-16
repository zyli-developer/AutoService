"""Tests for T5B.1 docker-compose multi-tenant template."""
from __future__ import annotations

import os
import subprocess
import pytest
import yaml
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent.parent / "deploy"
PROJECT_ROOT = Path(__file__).parent.parent


def render_template(tenant="demo", port_offset=0, zchat_image="zchat/channel-server:latest"):
    """Render compose template with envsubst."""
    tmpl = DEPLOY_DIR / "docker-compose.tmpl.yaml"
    env = {
        **os.environ,
        "TENANT": tenant,
        "PORT_OFFSET": str(port_offset),
        "ZCHAT_IMAGE": zchat_image,
        "ANTHROPIC_API_KEY": "sk-test-placeholder",
        "CHANNEL_SERVER_URL": f"ws://channel-server:{9999 + port_offset}",
        "DEMO_PORT": str(8000 + port_offset),
        "TENANT_DATA_DIR": f"./data/{tenant}",
        "PORT_OFFSET_9999": str(9999 + port_offset),
        "PORT_OFFSET_5173": str(5173 + port_offset),
        "PORT_OFFSET_5174": str(5174 + port_offset),
        "PORT_OFFSET_5175": str(5175 + port_offset),
    }
    result = subprocess.run(
        ["envsubst"],
        input=tmpl.read_text(),
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"envsubst failed: {result.stderr}"
    return yaml.safe_load(result.stdout), result.stdout


# ---------------------------------------------------------------------------
# TC-001: Valid YAML, 6 services, no unresolved variables
# ---------------------------------------------------------------------------

def test_tc001_rendered_yaml_is_valid_with_six_services_and_no_unresolved_vars():
    """TC-001: rendered YAML is valid, has exactly 6 services, no unresolved ${."""
    compose, raw = render_template()
    assert compose is not None, "yaml.safe_load returned None"
    services = compose.get("services", {})
    assert len(services) == 6, f"Expected 6 services, got {len(services)}: {list(services)}"
    assert "${" not in raw, "Unresolved envsubst variables found in rendered output"


# ---------------------------------------------------------------------------
# TC-002: Default port mappings (offset=0)
# ---------------------------------------------------------------------------

def test_tc002_default_port_mappings():
    """TC-002: default offset=0 produces expected host:container port bindings."""
    compose, _ = render_template(port_offset=0)
    services = compose["services"]

    def host_ports(svc_name):
        """Return set of host ports declared for a service."""
        ports = services[svc_name].get("ports", [])
        result = set()
        for p in ports:
            # ports can be "HOST:CONTAINER" strings or dicts with 'published'
            if isinstance(p, str):
                result.add(int(p.split(":")[0]))
            elif isinstance(p, dict):
                result.add(int(p["published"]))
        return result

    assert 8000 in host_ports("autoservice"), "autoservice should expose host port 8000"
    assert 5173 in host_ports("customer-chat"), "customer-chat should expose host port 5173"
    assert 5174 in host_ports("operator-console"), "operator-console should expose host port 5174"
    assert 5175 in host_ports("admin-portal"), "admin-portal should expose host port 5175"
    assert 9999 in host_ports("channel-server"), "channel-server should expose host port 9999"


# ---------------------------------------------------------------------------
# TC-003: Two tenants with different offsets have zero port overlap
# ---------------------------------------------------------------------------

def test_tc003_port_offset_prevents_host_port_collision():
    """TC-003: rendering offset=0 and offset=100 produces zero overlapping host ports."""
    compose0, _ = render_template(tenant="demo", port_offset=0)
    compose100, _ = render_template(tenant="acme", port_offset=100)

    def all_host_ports(compose):
        ports = set()
        for svc in compose["services"].values():
            for p in svc.get("ports", []):
                if isinstance(p, str):
                    ports.add(int(p.split(":")[0]))
                elif isinstance(p, dict):
                    ports.add(int(p["published"]))
        return ports

    ports0 = all_host_ports(compose0)
    ports100 = all_host_ports(compose100)
    overlap = ports0 & ports100
    assert not overlap, f"Port collision between offset=0 and offset=100: {overlap}"


# ---------------------------------------------------------------------------
# TC-004: bridges network_mode and no ports/networks
# ---------------------------------------------------------------------------

def test_tc004_bridges_network_mode_service_channel_server():
    """TC-004: bridges service has network_mode 'service:channel-server', no ports, no networks."""
    compose, _ = render_template()
    services = compose["services"]
    assert "bridges" in services, "bridges service not found"
    bridges = services["bridges"]
    assert bridges.get("network_mode") == "service:channel-server", (
        f"bridges.network_mode should be 'service:channel-server', got {bridges.get('network_mode')}"
    )
    assert not bridges.get("ports"), "bridges should not declare ports"
    assert not bridges.get("networks"), "bridges should not declare networks"


# ---------------------------------------------------------------------------
# TC-005: autoservice CHANNEL_SERVER_URL uses "channel-server" hostname
# ---------------------------------------------------------------------------

def test_tc005_autoservice_channel_server_url_uses_service_hostname():
    """TC-005: autoservice environment CHANNEL_SERVER_URL contains 'channel-server', not 'localhost'."""
    compose, _ = render_template()
    autoservice = compose["services"]["autoservice"]
    env = autoservice.get("environment", {})
    # environment can be a list of "KEY=VALUE" or a dict
    if isinstance(env, list):
        env_dict = {}
        for item in env:
            if "=" in item:
                k, v = item.split("=", 1)
                env_dict[k] = v
        env = env_dict
    url = env.get("CHANNEL_SERVER_URL", "")
    assert "channel-server" in url, (
        f"CHANNEL_SERVER_URL should reference 'channel-server', got: {url!r}"
    )
    assert "localhost" not in url, (
        f"CHANNEL_SERVER_URL must not use 'localhost', got: {url!r}"
    )


# ---------------------------------------------------------------------------
# TC-006: autoservice.Dockerfile static structure check
# ---------------------------------------------------------------------------

def test_tc006_autoservice_dockerfile_has_required_directives():
    """TC-006: deploy/autoservice.Dockerfile exists with FROM, WORKDIR, CMD directives."""
    dockerfile = DEPLOY_DIR / "autoservice.Dockerfile"
    assert dockerfile.exists(), f"Missing file: {dockerfile}"
    text = dockerfile.read_text()
    assert "FROM" in text, "autoservice.Dockerfile must contain FROM directive"
    assert "WORKDIR" in text, "autoservice.Dockerfile must contain WORKDIR directive"
    assert "CMD" in text, "autoservice.Dockerfile must contain CMD directive"


# ---------------------------------------------------------------------------
# TC-007: frontend.Dockerfile multi-stage build check
# ---------------------------------------------------------------------------

def test_tc007_frontend_dockerfile_is_multistage_with_arg_app_name():
    """TC-007: deploy/frontend.Dockerfile exists, has two FROM lines (multi-stage), and ARG APP_NAME."""
    dockerfile = DEPLOY_DIR / "frontend.Dockerfile"
    assert dockerfile.exists(), f"Missing file: {dockerfile}"
    text = dockerfile.read_text()
    from_lines = [line for line in text.splitlines() if line.strip().upper().startswith("FROM")]
    assert len(from_lines) >= 2, (
        f"frontend.Dockerfile should have at least 2 FROM lines (multi-stage), found: {from_lines}"
    )
    assert "ARG APP_NAME" in text or "ARG app_name" in text.lower(), (
        "frontend.Dockerfile must declare ARG APP_NAME"
    )


# ---------------------------------------------------------------------------
# TC-008: .dockerignore excludes sensitive files
# ---------------------------------------------------------------------------

def test_tc008_dockerignore_excludes_sensitive_files():
    """TC-008: .dockerignore exists and excludes .env, credentials, .autoservice/, node_modules."""
    dockerignore = PROJECT_ROOT / ".dockerignore"
    assert dockerignore.exists(), f"Missing file: {dockerignore}"
    text = dockerignore.read_text()
    required_patterns = [
        ".env",
        ".feishu-credentials.json",
        ".autoservice/",
        "node_modules",
    ]
    for pattern in required_patterns:
        assert pattern in text, f".dockerignore must contain '{pattern}'"


# ---------------------------------------------------------------------------
# TC-009: healthchecks and depends_on with condition
# ---------------------------------------------------------------------------

def test_tc009_healthchecks_and_depends_on_condition():
    """TC-009: channel-server and autoservice have healthchecks; autoservice depends_on channel-server healthy."""
    compose, _ = render_template()
    services = compose["services"]

    assert "healthcheck" in services["channel-server"], (
        "channel-server must define a healthcheck"
    )
    assert "healthcheck" in services["autoservice"], (
        "autoservice must define a healthcheck"
    )

    depends_on = services["autoservice"].get("depends_on", {})
    # depends_on can be a list or dict
    if isinstance(depends_on, list):
        assert "channel-server" in depends_on, (
            "autoservice.depends_on must include channel-server"
        )
        # list form doesn't support conditions — flag as insufficient
        pytest.fail(
            "autoservice.depends_on is a list; condition: service_healthy requires dict form"
        )
    else:
        assert "channel-server" in depends_on, (
            "autoservice.depends_on must include channel-server"
        )
        condition = depends_on["channel-server"].get("condition")
        assert condition == "service_healthy", (
            f"autoservice depends_on channel-server condition should be 'service_healthy', got {condition!r}"
        )


# ---------------------------------------------------------------------------
# TC-010: .env.tmpl contains all required variable names
# ---------------------------------------------------------------------------

def test_tc010_env_tmpl_contains_required_variables():
    """TC-010: deploy/.env.tmpl declares all required variable names."""
    env_tmpl = DEPLOY_DIR / ".env.tmpl"
    assert env_tmpl.exists(), f"Missing file: {env_tmpl}"
    text = env_tmpl.read_text()
    required_vars = [
        "TENANT",
        "PORT_OFFSET",
        "ZCHAT_IMAGE",
        "ANTHROPIC_API_KEY",
        "DEMO_PORT",
        "CHANNEL_SERVER_URL",
    ]
    for var in required_vars:
        assert var in text, f".env.tmpl must contain variable '{var}'"


# ---------------------------------------------------------------------------
# TC-011: deploy/ directory has all required files
# ---------------------------------------------------------------------------

def test_tc011_deploy_directory_has_required_files():
    """TC-011: deploy/ directory contains all required files."""
    required_files = [
        "docker-compose.tmpl.yaml",
        "autoservice.Dockerfile",
        "frontend.Dockerfile",
        ".env.tmpl",
    ]
    for filename in required_files:
        path = DEPLOY_DIR / filename
        assert path.exists(), f"deploy/ is missing required file: {filename}"


# ---------------------------------------------------------------------------
# TC-012: autoservice volumes include tenant-isolated data directory
# ---------------------------------------------------------------------------

def test_tc012_autoservice_volumes_include_tenant_data_dir():
    """TC-012: autoservice service volumes include a tenant-isolated data directory."""
    compose, _ = render_template(tenant="demo")
    autoservice = compose["services"]["autoservice"]
    volumes = autoservice.get("volumes", [])
    assert volumes, "autoservice must declare at least one volume"

    # At least one volume should reference the tenant data directory or "./data/demo"
    volume_strings = []
    for v in volumes:
        if isinstance(v, str):
            volume_strings.append(v)
        elif isinstance(v, dict):
            volume_strings.append(v.get("source", "") + ":" + v.get("target", ""))

    tenant_volumes = [v for v in volume_strings if "demo" in v or "data" in v]
    assert tenant_volumes, (
        f"autoservice volumes must include a tenant-isolated data path; got: {volume_strings}"
    )
