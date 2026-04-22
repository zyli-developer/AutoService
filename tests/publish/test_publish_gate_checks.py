"""T1B.7 — publish gate + tarball + freeze/archive tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §6.

Covers
------
- Gate: happy path / critical compliance / unreviewed rehearsal / low KB warning
- Tarball: contents layout + sha256 recorded in publish record
- Freeze: sandbox moves to archived/ and config.status updates
- Runbook: auto-generated markdown contains fork + tar instructions
- 410 status flag: after publish, config shows archived status so Master
  runtime can reject /tenant/<tid>/* requests (actual HTTP 410 routing is
  outside publish.py).
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_layout(tmp_path, monkeypatch):
    """Redirect publish.SANDBOX_ROOT / ARCHIVED_ROOT / PUBLISHED_ROOT to tmp.

    Also neutralise the compliance scan by default (→ "low") so tests that
    exercise unrelated gate conditions don't accidentally fail on the 16
    compliance rules.  Tests that care about compliance can re-patch
    ``_run_compliance_scan`` to return ``"critical"``.
    """
    from autoservice import publish as pub_mod

    sandbox = tmp_path / "sandbox"
    archived = tmp_path / "archived"
    published = tmp_path / "published"

    monkeypatch.setattr(pub_mod, "SANDBOX_ROOT", sandbox)
    monkeypatch.setattr(pub_mod, "ARCHIVED_ROOT", archived)
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", published)

    # Default: non-critical compliance, so the gate doesn't block on
    # unrelated rules in tests that only care about other conditions.
    monkeypatch.setattr(
        pub_mod, "_run_compliance_scan",
        lambda _tid, _cfg: "low",
    )

    return {
        "sandbox": sandbox,
        "archived": archived,
        "published": published,
        "tmp": tmp_path,
    }


def _seed_sandbox(
    root: Path,
    tenant_id: str,
    *,
    reviewed: int = 12,
    total: int = 12,
    kb_chunks: int = 100,
    compliance_risk_critical: bool = False,
    souls: tuple[str, ...] = ("customer", "translate", "lead", "triage"),
    include_dream: bool = True,
    include_meta: bool = True,
) -> Path:
    """Build a complete sandbox directory so the gate can pass by default."""
    sandbox = root / tenant_id
    (sandbox / "souls").mkdir(parents=True, exist_ok=True)
    (sandbox / "kb").mkdir(parents=True, exist_ok=True)

    config = {
        "tenant_id": tenant_id,
        "brand_name": "acmecorp",
        "industry": "ecommerce",
        "status": "sandbox",
        "channels": ["web"],
        "created_at": "2026-04-20T10:00:00Z",
        # Satisfy the 16 compliance rules — use permissive defaults unless
        # compliance_risk_critical asks for a hostile state.
        "consent_collected": True,
        "data_retention_days": 90,
        "pii_redaction_enabled": not compliance_risk_critical,
        "soul": {
            "safety_guidelines_present": not compliance_risk_critical,
        },
    }
    (sandbox / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8",
    )

    for role in souls:
        (sandbox / "souls" / f"{role}_soul.md").write_text(
            f"# {role} soul\n\nAgent instructions for {role}.\n",
            encoding="utf-8",
        )
    if include_dream:
        (sandbox / "souls" / "dream_soul.md").write_text(
            "# Dream Engine\n\nPlaceholder.\n",
            encoding="utf-8",
        )
    if include_meta:
        (sandbox / "souls" / "_generation_meta.yaml").write_text(
            "source: test\n", encoding="utf-8",
        )

    # Rehearsal
    dialogs = []
    for i in range(total):
        dialogs.append({
            "id": f"d{i + 1}",
            "scenario": "complaint",
            "turns": [],
            "review_status": "approved" if i < reviewed else "pending",
            "review_note": "",
        })
    (sandbox / "rehearsal.json").write_text(
        json.dumps({"generated_at": "2026-04-20T10:30:00Z", "dialogs": dialogs}),
        encoding="utf-8",
    )

    # KB
    db_path = sandbox / "kb" / "kb.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kb_chunks (id TEXT PRIMARY KEY, content TEXT)"
        )
        for i in range(kb_chunks):
            conn.execute(
                "INSERT INTO kb_chunks (id, content) VALUES (?, ?)",
                (f"c{i}", f"chunk {i} content"),
            )
        conn.commit()
    finally:
        conn.close()

    return sandbox


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class TestGate:
    def test_gate_passes_happy_path(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_happy"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        gate = pub_mod.check_publish_gate(tid)

        assert gate.passed
        assert gate.blocking_reasons == []
        assert gate.rehearsal_reviewed == 12
        assert gate.rehearsal_total == 12
        assert gate.souls_saved == 4
        assert gate.kb_chunks >= 50

    def test_gate_blocks_on_unreviewed_rehearsal(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_unreviewed"
        _seed_sandbox(
            isolated_layout["sandbox"], tid,
            reviewed=8, total=12,
        )
        gate = pub_mod.check_publish_gate(tid)

        assert not gate.passed
        assert any("pending review" in r for r in gate.blocking_reasons)

    def test_gate_blocks_on_missing_souls(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_missing_souls"
        # Only 2 of the 4 required souls
        _seed_sandbox(
            isolated_layout["sandbox"], tid,
            souls=("customer", "translate"),
        )
        gate = pub_mod.check_publish_gate(tid)

        assert not gate.passed
        assert any("missing soul" in r for r in gate.blocking_reasons)
        assert gate.souls_saved == 2

    def test_gate_warns_but_passes_on_low_kb_chunks(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_low_kb"
        _seed_sandbox(isolated_layout["sandbox"], tid, kb_chunks=10)
        gate = pub_mod.check_publish_gate(tid)

        assert gate.passed
        assert gate.kb_chunks == 10
        assert any("kb.db" in w and "chunks" in w for w in gate.warnings)

    def test_gate_blocks_on_critical_compliance_without_override(
        self, isolated_layout, monkeypatch,
    ):
        from autoservice import publish as pub_mod

        tid = "tenant_critical"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        # Force compliance critical — isolates gate-condition logic from
        # the 16-rule ComplianceEngine behaviour.
        monkeypatch.setattr(
            pub_mod, "_run_compliance_scan",
            lambda _tid, _cfg: "critical",
        )

        gate = pub_mod.check_publish_gate(tid)
        assert not gate.passed
        assert gate.compliance_risk == "critical"
        assert any("critical" in r for r in gate.blocking_reasons)

        # With signer + override, the gate passes.
        gate_ok = pub_mod.check_publish_gate(
            tid, override=True, signer="admin@acme.com",
        )
        assert gate_ok.passed
        assert gate_ok.override is True

    def test_override_requires_signer(self, isolated_layout, monkeypatch):
        from autoservice import publish as pub_mod

        tid = "tenant_override"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        # Force a critical compliance state so override matters.
        monkeypatch.setattr(
            pub_mod, "_run_compliance_scan",
            lambda _tid, _cfg: "critical",
        )

        gate_noover = pub_mod.check_publish_gate(tid)
        assert not gate_noover.passed
        assert any("critical" in r for r in gate_noover.blocking_reasons)

        gate_bad = pub_mod.check_publish_gate(tid, override=True, signer=None)
        assert not gate_bad.passed  # override without signer still blocks

        gate_ok = pub_mod.check_publish_gate(
            tid, override=True, signer="admin@acme.com",
        )
        assert gate_ok.passed
        assert gate_ok.override is True
        assert gate_ok.signer == "admin@acme.com"

    def test_gate_raises_on_missing_sandbox(self, isolated_layout):
        from autoservice import publish as pub_mod

        with pytest.raises(FileNotFoundError):
            pub_mod.check_publish_gate("tenant_ghost")


# ---------------------------------------------------------------------------
# Tarball
# ---------------------------------------------------------------------------

class TestTarball:
    def test_archive_contents(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_tar"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        artifact = pub_mod.build_publish_archive(tid)

        assert artifact.exists()
        assert artifact.suffix == ".gz"
        assert tid in artifact.name
        assert artifact.parent == isolated_layout["published"]

        # Unpack and inspect layout.
        with tarfile.open(artifact, "r:gz") as tar:
            names = tar.getnames()

        prefix = f"plugins/{tid}/"
        # Core entries
        assert f"{prefix}plugin.yaml" in names
        assert f"{prefix}config.json" in names
        assert f"{prefix}README.md" in names
        assert f"{prefix}rehearsal_baseline.json" in names
        assert f"{prefix}kb/kb.db" in names

        # Souls — 4 required + dream + _generation_meta.yaml (6 total)
        for role in ("customer", "translate", "lead", "triage", "dream"):
            assert f"{prefix}souls/{role}_soul.md" in names, (
                f"missing souls/{role}_soul.md in tarball"
            )
        assert f"{prefix}souls/_generation_meta.yaml" in names

    def test_archive_plugin_yaml_has_tenant_metadata(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_yaml"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        artifact = pub_mod.build_publish_archive(tid)
        with tarfile.open(artifact, "r:gz") as tar:
            f = tar.extractfile(f"plugins/{tid}/plugin.yaml")
            assert f is not None
            text = f.read().decode("utf-8")

        assert f"name: {tid}" in text
        assert "version: 1.0.0" in text
        assert "mode: production" in text
        assert "mcp_tools: []" in text
        assert "acmecorp" in text  # brand_name shows up in description
        assert "ecommerce" in text

    def test_archive_sha256_in_record(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_sha"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        artifact = pub_mod.build_publish_archive(tid)
        gate = pub_mod.check_publish_gate(tid)
        record_path = pub_mod.write_publish_record(tid, artifact, gate)

        body = json.loads(record_path.read_text(encoding="utf-8"))
        assert body["tenant_id"] == tid
        assert body["artifact"].endswith(artifact.name)
        sha = body["artifact_sha256"]
        assert isinstance(sha, str) and len(sha) == 64  # hex digest

        # Re-hash independently
        import hashlib
        h = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert sha == h

        # Gate snapshot embedded
        checks = body["pre_publish_checks"]
        assert checks["souls_saved"] == 4
        assert checks["rehearsal_reviewed"] == 12


# ---------------------------------------------------------------------------
# Freeze + archive
# ---------------------------------------------------------------------------

class TestFreezeArchive:
    def test_freeze_flips_status(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_freeze"
        sb = _seed_sandbox(isolated_layout["sandbox"], tid)

        pub_mod.freeze_sandbox(tid)
        cfg = json.loads((sb / "config.json").read_text(encoding="utf-8"))
        assert cfg["status"] == "published_pending_fork"

    def test_archive_moves_sandbox_and_updates_status(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_arch"
        sb = _seed_sandbox(isolated_layout["sandbox"], tid)
        assert sb.exists()

        pub_mod.freeze_sandbox(tid)
        archived_dir = pub_mod.archive_sandbox(tid)

        assert not sb.exists(), "sandbox dir should have been moved"
        assert archived_dir.exists()
        assert archived_dir.parent == isolated_layout["archived"]
        assert archived_dir.name.startswith(f"{tid}_")

        # Status inside archive flips to "archived"
        cfg = json.loads(
            (archived_dir / "config.json").read_text(encoding="utf-8"),
        )
        assert cfg["status"] == "archived"

    def test_publish_end_to_end_happy_path(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_e2e"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        result = pub_mod.publish(tid)

        assert result["status"] == "published"
        assert result["tenant_id"] == tid
        assert Path(result["artifact"]).exists()
        assert Path(result["runbook"]).exists()
        assert Path(result["record"]).exists()
        assert Path(result["archived_to"]).exists()

        # Sandbox physically moved away
        assert not (isolated_layout["sandbox"] / tid).exists()

        # Record contains sha256 + archive pointer
        rec = json.loads(Path(result["record"]).read_text(encoding="utf-8"))
        assert rec["artifact_sha256"] == result["artifact_sha256"]
        assert rec["source_sandbox_archived_to"] == result["archived_to"]
        assert rec["status"] == "awaiting_fork"

    def test_410_on_sandbox_url_after_publish(self, isolated_layout):
        """After publish, the archived config.json carries status=archived.

        The HTTP layer uses this flag to return 410 Gone on `/tenant/<tid>/*` —
        we test only the data flag here; actual 410 routing is outside
        publish.py's responsibility.
        """
        from autoservice import publish as pub_mod

        tid = "tenant_410"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        result = pub_mod.publish(tid)

        cfg = json.loads(
            (Path(result["archived_to"]) / "config.json").read_text(
                encoding="utf-8"
            ),
        )
        assert cfg["status"] == "archived"

    def test_publish_blocked_returns_blocked_status(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_blocked"
        _seed_sandbox(
            isolated_layout["sandbox"], tid,
            reviewed=5, total=12,
        )
        result = pub_mod.publish(tid)

        assert result["status"] == "blocked"
        assert "gate" in result
        assert not result["gate"]["passed"]
        # Sandbox MUST remain on disk so the user can fix review state.
        assert (isolated_layout["sandbox"] / tid).exists()
        # No artifact produced
        assert not (isolated_layout["published"]).exists() or not any(
            isolated_layout["published"].glob(f"tenant_{tid}_publish_*.tar.gz")
        )


# ---------------------------------------------------------------------------
# Runbook
# ---------------------------------------------------------------------------

class TestRunbook:
    def test_runbook_contains_fork_instructions(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_runbook"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        artifact = pub_mod.build_publish_archive(tid)
        runbook = pub_mod.write_runbook(tid, artifact)

        assert runbook.exists()
        assert runbook.name == f"{tid}_PUBLISH_RUNBOOK.md"
        text = runbook.read_text(encoding="utf-8")

        assert "gh repo fork" in text
        assert "tar -xzf" in text
        assert "make check" in text
        assert tid in text
        assert str(artifact) in text


# ---------------------------------------------------------------------------
# ForkCreator abstraction
# ---------------------------------------------------------------------------

class TestForkCreator:
    def test_local_tarball_fork_creator_produces_runbook(self, isolated_layout):
        from autoservice import publish as pub_mod

        tid = "tenant_forkcreator"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        artifact = pub_mod.build_publish_archive(tid)
        creator = pub_mod.LocalTarballForkCreator()
        assert isinstance(creator, pub_mod.ForkCreator)

        result = creator.create(tid, artifact)
        assert result.tenant_id == tid
        assert result.artifact_path == artifact
        assert result.runbook_path.exists()
        assert result.repo_url is None  # M1 — no git automation

    def test_publish_accepts_custom_fork_creator(self, isolated_layout):
        """Inject a spy ForkCreator to assert the seam is wired up."""
        from autoservice import publish as pub_mod

        calls: list[tuple[str, Path]] = []

        class SpyCreator:
            def create(self, tenant_id: str, artifact_path: Path):
                calls.append((tenant_id, artifact_path))
                runbook = pub_mod.write_runbook(tenant_id, artifact_path)
                return pub_mod.ForkResult(
                    tenant_id=tenant_id,
                    artifact_path=artifact_path,
                    runbook_path=runbook,
                    repo_url="https://example/fake",
                )

        tid = "tenant_spy"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        result = pub_mod.publish(tid, fork_creator=SpyCreator())
        assert result["status"] == "published"
        assert len(calls) == 1
        assert calls[0][0] == tid


# ---------------------------------------------------------------------------
# select_fork_creator_from_config() — config-driven ForkCreator selection
#
# The HTTP route `/api/onboard/publish` does not itself know which creator
# to use; it calls this helper to resolve the admin's choice from
# `.autoservice/config.local.yaml`.  Tests here pin the selector's
# behavior independently of the route for fast iteration.
# ---------------------------------------------------------------------------


class TestSelectForkCreator:
    def test_returns_none_when_config_missing(self, tmp_path):
        """Missing config file → None (→ publish() defaults to Local)."""
        from autoservice.publish import select_fork_creator_from_config

        result = select_fork_creator_from_config(tmp_path / "nope.yaml")
        assert result is None

    def test_returns_none_when_fork_creator_unset(self, tmp_path):
        """Config exists, but `fork_creator` key missing → None."""
        from autoservice.publish import select_fork_creator_from_config

        cfg = tmp_path / "config.local.yaml"
        cfg.write_text("auth:\n  admin_emails: []\n", encoding="utf-8")
        assert select_fork_creator_from_config(cfg) is None

    def test_returns_none_when_fork_creator_local(self, tmp_path):
        """Explicit `fork_creator: local` → None (use default)."""
        from autoservice.publish import select_fork_creator_from_config

        cfg = tmp_path / "config.local.yaml"
        cfg.write_text("fork_creator: local\n", encoding="utf-8")
        assert select_fork_creator_from_config(cfg) is None

    def test_returns_github_api_when_configured_and_available(self, tmp_path):
        """`fork_creator: github_api` + gh authed → GitHubApiForkCreator."""
        from unittest.mock import patch

        from autoservice.publish import (
            GitHubApiForkCreator,
            select_fork_creator_from_config,
        )

        cfg = tmp_path / "config.local.yaml"
        cfg.write_text("fork_creator: github_api\n", encoding="utf-8")
        with patch.object(
            GitHubApiForkCreator, "available", return_value=True
        ):
            result = select_fork_creator_from_config(cfg)
        assert isinstance(result, GitHubApiForkCreator)

    def test_falls_back_when_gh_unavailable(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ):
        """github_api requested but gh unavailable → None + WARNING log.

        The fallback is non-destructive: publish() still runs via
        LocalTarballForkCreator, producing a tarball + runbook.  The log
        line is the only signal to the admin — tests pin it so it can't be
        silently swallowed.
        """
        import logging
        from unittest.mock import patch

        from autoservice.publish import (
            GitHubApiForkCreator,
            select_fork_creator_from_config,
        )

        cfg = tmp_path / "config.local.yaml"
        cfg.write_text("fork_creator: github_api\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="autoservice.publish"):
            with patch.object(
                GitHubApiForkCreator, "available", return_value=False
            ):
                result = select_fork_creator_from_config(cfg)

        assert result is None
        combined = " ".join(r.message for r in caplog.records)
        assert "fork_creator" in combined
        assert "gh" in combined.lower()

    def test_malformed_yaml_returns_none(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ):
        """Corrupt yaml → None + WARNING log; never raises."""
        import logging

        from autoservice.publish import select_fork_creator_from_config

        cfg = tmp_path / "config.local.yaml"
        cfg.write_text("this: is: not: yaml\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="autoservice.publish"):
            result = select_fork_creator_from_config(cfg)
        assert result is None


class TestRouteSelectsForkCreator:
    """Integration — `/api/onboard/publish` passes the selected creator to publish()."""

    def test_route_uses_github_api_creator_when_configured(
        self, isolated_layout, monkeypatch
    ):
        """Config says github_api + gh available → route runs via GitHubApiForkCreator.

        Guarantees the selector is actually plumbed through the route, not
        just tested in isolation.  Uses ``patch.object`` on
        ``GitHubApiForkCreator.create`` to capture the call — the real
        ``create()`` would hit subprocess.run.
        """
        from unittest.mock import patch

        from autoservice import publish as pub_mod
        from autoservice.publish import GitHubApiForkCreator

        tid = "tenant_route_gha"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        # Write a config file under the tmp dir and redirect the route to it.
        cfg_path = isolated_layout["tmp"] / "config.local.yaml"
        cfg_path.write_text("fork_creator: github_api\n", encoding="utf-8")

        from autoservice import api_routes
        monkeypatch.setattr(
            api_routes, "_PUBLISH_CONFIG_PATH", cfg_path
        )

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        app = FastAPI()
        app.include_router(api_routes.api_router)
        client = TestClient(app)

        captured: list[tuple[str, Path]] = []

        def fake_create(self, tenant_id: str, artifact_path: Path):
            captured.append((tenant_id, artifact_path))
            runbook = pub_mod.write_runbook(tenant_id, artifact_path)
            return pub_mod.ForkResult(
                tenant_id=tenant_id,
                artifact_path=artifact_path,
                runbook_path=runbook,
                repo_url="https://github.com/user/AutoService-" + tenant_id,
            )

        with patch.object(
            GitHubApiForkCreator, "available", return_value=True
        ), patch.object(GitHubApiForkCreator, "create", fake_create):
            resp = client.post(
                "/api/onboard/publish", json={"tenant_id": tid}
            )

        assert resp.status_code == 200, resp.text
        assert len(captured) == 1, (
            "GitHubApiForkCreator.create() must have been invoked by the route"
        )
        assert captured[0][0] == tid

    def test_route_defaults_to_local_creator(self, isolated_layout, monkeypatch):
        """No config file → route uses LocalTarballForkCreator (existing behavior).

        Regression guard: the selector change MUST NOT alter the default
        path for callers that don't opt in.
        """
        from autoservice import api_routes

        # Point the route at a non-existent config so selector returns None.
        monkeypatch.setattr(
            api_routes,
            "_PUBLISH_CONFIG_PATH",
            isolated_layout["tmp"] / "missing.yaml",
        )

        tid = "tenant_route_default"
        _seed_sandbox(isolated_layout["sandbox"], tid)

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        app = FastAPI()
        app.include_router(api_routes.api_router)
        client = TestClient(app)

        resp = client.post("/api/onboard/publish", json={"tenant_id": tid})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # No repo_url means LocalTarballForkCreator was used (M1 default).
        # The endpoint response doesn't surface repo_url, but the
        # runbook + archived_to must still exist.
        assert body["runbook"]
        assert body["archived_to"]


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

class TestPublishEndpoint:
    def _client(self, monkeypatch, layout):
        """Build a FastAPI test client with publish paths redirected."""
        from autoservice import publish as pub_mod
        monkeypatch.setattr(pub_mod, "SANDBOX_ROOT", layout["sandbox"])
        monkeypatch.setattr(pub_mod, "ARCHIVED_ROOT", layout["archived"])
        monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", layout["published"])

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from autoservice.api_routes import api_router

        app = FastAPI()
        app.include_router(api_router)
        return TestClient(app)

    def test_publish_happy_path(self, isolated_layout, monkeypatch):
        tid = "tenant_http"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        client = self._client(monkeypatch, isolated_layout)

        resp = client.post("/api/onboard/publish", json={"tenant_id": tid})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "published"
        assert body["tenant_id"] == tid
        for key in ("artifact", "artifact_sha256", "runbook", "record", "archived_to"):
            assert key in body
            assert body[key]

    def test_publish_missing_tenant_id_400(self, isolated_layout, monkeypatch):
        client = self._client(monkeypatch, isolated_layout)
        resp = client.post("/api/onboard/publish", json={})
        assert resp.status_code == 400
        assert "tenant_id" in resp.json()["error"]

    def test_publish_missing_sandbox_404(self, isolated_layout, monkeypatch):
        client = self._client(monkeypatch, isolated_layout)
        resp = client.post(
            "/api/onboard/publish", json={"tenant_id": "nope"},
        )
        assert resp.status_code == 404

    def test_publish_blocked_returns_409(self, isolated_layout, monkeypatch):
        tid = "tenant_blocked_http"
        _seed_sandbox(
            isolated_layout["sandbox"], tid,
            reviewed=3, total=12,
        )
        client = self._client(monkeypatch, isolated_layout)

        resp = client.post("/api/onboard/publish", json={"tenant_id": tid})
        assert resp.status_code == 409
        body = resp.json()
        assert body["tenant_id"] == tid
        assert body["status"] == "blocked"
        assert any(
            "pending review" in r for r in body["gate"]["blocking_reasons"]
        )

    def test_publish_override_requires_signer(self, isolated_layout, monkeypatch):
        tid = "tenant_override_http"
        _seed_sandbox(isolated_layout["sandbox"], tid)
        client = self._client(monkeypatch, isolated_layout)

        resp = client.post(
            "/api/onboard/publish",
            json={
                "tenant_id": tid,
                "override_compliance_critical": True,
                # signer deliberately missing
            },
        )
        assert resp.status_code == 400
        assert "signer" in resp.json()["error"]
