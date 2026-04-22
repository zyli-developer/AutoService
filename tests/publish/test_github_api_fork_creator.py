"""Tests for GitHubApiForkCreator (T8B.1).

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.4

Red-line invariants (spec §9):
- NEVER auto-deletes forks (no `gh repo delete` invocation anywhere in the class)
- ForkCreationError.fork_name populated on ALL post-create-success failures
  so humans know which repo to clean up manually
- subprocess timeout always explicit + stderr never silently swallowed
"""

from __future__ import annotations

import inspect
import logging
import subprocess
from unittest.mock import patch

import pytest

from autoservice.publish import ForkCreationError, GitHubApiForkCreator


# ---------------------------------------------------------------------------
# available() — gh CLI probe
# ---------------------------------------------------------------------------

def test_available_returns_true_when_gh_authed() -> None:
    """Happy path — `gh auth status` exits 0 → available() returns True.

    Also pins the subprocess argv + timeout shape we depend on.
    """
    creator = GitHubApiForkCreator()
    completed = subprocess.CompletedProcess(
        args=["gh", "auth", "status"], returncode=0, stdout="", stderr=""
    )
    with patch("subprocess.run", return_value=completed) as mock_run:
        assert creator.available() is True
    # Assert exact argv + timeout
    args, kwargs = mock_run.call_args
    assert args[0] == ["gh", "auth", "status"]
    assert kwargs["timeout"] == 30
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_available_returns_false_when_gh_missing() -> None:
    """gh CLI not installed → FileNotFoundError → available() False (no raise)."""
    creator = GitHubApiForkCreator()
    with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
        assert creator.available() is False


def test_available_returns_false_when_not_authed() -> None:
    """gh installed but not logged in → non-zero exit → available() False."""
    creator = GitHubApiForkCreator()
    err = subprocess.CalledProcessError(
        returncode=1, cmd=["gh", "auth", "status"], stderr="You are not logged in"
    )
    with patch("subprocess.run", side_effect=err):
        assert creator.available() is False


# ---------------------------------------------------------------------------
# create_fork() — happy path
# ---------------------------------------------------------------------------

def test_create_fork_success_returns_url() -> None:
    """Happy path — gh prints fork URL; we parse & return it.

    Also pins argv shape: gh repo fork <source> --fork-name=<target>.
    """
    creator = GitHubApiForkCreator(source_repo="ezagent42/AutoService")
    completed = subprocess.CompletedProcess(
        args=["gh", "repo", "fork"],
        returncode=0,
        stdout="https://github.com/user/AutoService-acme\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=completed) as mock_run:
        url = creator.create_fork("acme")
    assert url == "https://github.com/user/AutoService-acme"
    args, kwargs = mock_run.call_args
    argv = args[0]
    assert argv[0] == "gh"
    assert argv[1] == "repo"
    assert argv[2] == "fork"
    assert "ezagent42/AutoService" in argv
    # fork name flag present
    assert any("AutoService-acme" in a for a in argv), argv
    assert kwargs["timeout"] == 60
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_create_fork_with_org_prefix() -> None:
    """org="h2oslabs" → fork target name prefixed with org."""
    creator = GitHubApiForkCreator(
        source_repo="ezagent42/AutoService", org="h2oslabs"
    )
    completed = subprocess.CompletedProcess(
        args=["gh", "repo", "fork"],
        returncode=0,
        stdout="https://github.com/h2oslabs/AutoService-acme\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=completed) as mock_run:
        url = creator.create_fork("acme")
    assert url == "https://github.com/h2oslabs/AutoService-acme"
    argv = mock_run.call_args[0][0]
    # org-qualified fork name must appear
    assert any("h2oslabs/AutoService-acme" in a for a in argv), argv


# ---------------------------------------------------------------------------
# create_fork() — failure modes (spec §9 partial-failure recovery)
# ---------------------------------------------------------------------------

def test_create_fork_partial_failure_includes_fork_name() -> None:
    """gh exits non-zero AFTER being invoked → ForkCreationError must carry
    fork_name so the admin knows which repo to manually clean up.

    Red-line invariant: NEVER auto-delete on error.
    """
    creator = GitHubApiForkCreator()
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "repo", "fork"],
        stderr="network down",
    )
    with patch("subprocess.run", side_effect=err):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create_fork("acme")
    e = excinfo.value
    assert e.fork_name == "AutoService-acme", (
        "fork_name MUST be populated so humans know what to clean up"
    )
    assert e.phase == "gh-repo-fork"
    assert e.stderr == "network down"
    assert "network down" in str(e)


def test_create_fork_NEVER_calls_gh_repo_delete() -> None:
    """Regression guard — spec §9: failure does NOT auto-delete forks.

    Greps the class source for any mention of `gh repo delete` / similar —
    zero hits required.
    """
    src = inspect.getsource(GitHubApiForkCreator)
    src += inspect.getsource(ForkCreationError)
    assert "repo delete" not in src, (
        "GitHubApiForkCreator must never invoke `gh repo delete` — "
        "spec §9 red line: human confirmation required for cleanup."
    )
    assert "repo-delete" not in src
    # Also guard against "gh", "delete" pair in any list-literal-ish form:
    assert '"delete"' not in src
    assert "'delete'" not in src


def test_create_fork_timeout_raises_with_fork_name() -> None:
    """TimeoutExpired mid-invoke → ForkCreationError with fork_name.

    The fork *might* have been partly created; err on the side of surfacing
    the name so the admin checks + cleans if needed.
    """
    creator = GitHubApiForkCreator()
    err = subprocess.TimeoutExpired(cmd=["gh", "repo", "fork"], timeout=60)
    with patch("subprocess.run", side_effect=err):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create_fork("acme")
    e = excinfo.value
    assert e.fork_name == "AutoService-acme"
    assert e.phase == "gh-repo-fork"
    assert "timed out" in str(e).lower() or "timeout" in str(e).lower()


def test_create_fork_gh_missing_raises_actionable_error() -> None:
    """gh binary not found → ForkCreationError(phase="gh-check") with
    fork_name=None (nothing was created yet) and an actionable message
    pointing at the install URL."""
    creator = GitHubApiForkCreator()
    with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create_fork("acme")
    e = excinfo.value
    assert e.fork_name is None, (
        "Pre-invoke failure → no fork exists → fork_name=None is correct"
    )
    assert e.phase == "gh-check"
    msg = str(e)
    assert "gh" in msg.lower()
    # Actionable install hint
    assert "cli.github.com" in msg or "install" in msg.lower()


def test_create_fork_stderr_logged_not_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    """On CalledProcessError, stderr MUST be WARNING-logged.

    Silent swallow of stderr is a debug disaster; spec §9 Yellow concern.
    """
    creator = GitHubApiForkCreator()
    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "repo", "fork"],
        stderr="RATE_LIMITED: x-ratelimit-reset 60s",
    )
    with caplog.at_level(logging.WARNING, logger="autoservice.publish"):
        with patch("subprocess.run", side_effect=err):
            with pytest.raises(ForkCreationError):
                creator.create_fork("acme")
    # The stderr content must appear somewhere in captured logs
    combined = " ".join(r.message for r in caplog.records)
    assert "RATE_LIMITED" in combined, (
        f"stderr was silently swallowed — expected in WARNING log. "
        f"Captured: {combined!r}"
    )


def test_create_fork_empty_tenant_id_rejected() -> None:
    """Empty / whitespace tenant_id → raise early (don't invoke subprocess)."""
    creator = GitHubApiForkCreator()
    with patch("subprocess.run") as mock_run:
        with pytest.raises((ValueError, ForkCreationError)):
            creator.create_fork("")
        with pytest.raises((ValueError, ForkCreationError)):
            creator.create_fork("   ")
    # subprocess never called — early validation
    assert mock_run.call_count == 0


# ---------------------------------------------------------------------------
# create() — full pipeline orchestrator (fork + clone + unpack + config + push)
#
# Protocol contract: ForkCreator.create(tenant_id, artifact_path) -> ForkResult.
# GitHubApiForkCreator.create() must:
#   1. reuse create_fork() to produce the fork
#   2. clone the fork to a local working dir
#   3. extract the tarball (artifact_path) under the clone
#   4. write .autoservice/config.local.yaml (reuses _fork_local_config_yaml_text)
#   5. git add + commit + push
#   6. return ForkResult with repo_url populated and runbook_path written
# ---------------------------------------------------------------------------

import tarfile as _tarfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

import autoservice.publish as pub_mod  # noqa: E402
from autoservice.publish import (  # noqa: E402
    ForkResult,
    _fork_local_config_yaml_text,
)


def _make_fake_artifact(tmp_path: _Path, tenant_id: str) -> _Path:
    """Produce a minimal tarball shaped like a real publish archive.

    Contains ``plugins/<tid>/plugin.yaml`` + ``plugins/<tid>/config.json``.
    """
    stage = tmp_path / "stage"
    plug = stage / "plugins" / tenant_id
    plug.mkdir(parents=True)
    (plug / "plugin.yaml").write_text("name: " + tenant_id + "\n", encoding="utf-8")
    (plug / "config.json").write_text("{}\n", encoding="utf-8")
    artifact = tmp_path / f"{tenant_id}.tar.gz"
    with _tarfile.open(artifact, "w:gz") as tf:
        tf.add(stage / "plugins", arcname="plugins")
    return artifact


def _make_subprocess_dispatcher(
    call_log: list,
    fork_url: str = "https://github.com/user/AutoService-acme",
    fail_on: str | None = None,
    fail_stderr: str = "",
):
    """Build a ``subprocess.run`` side_effect that dispatches by argv.

    ``fail_on`` is a marker matched against a classification of the argv:
      * "gh-fork", "gh-clone", "git-add", "git-commit", "git-push"
    When matched, the invocation raises CalledProcessError(returncode=1).
    """

    def classify(argv: list) -> str:
        if argv[:3] == ["gh", "repo", "fork"]:
            return "gh-fork"
        if argv[:3] == ["gh", "repo", "clone"]:
            return "gh-clone"
        if argv[:2] == ["git", "clone"]:
            return "gh-clone"  # alias — impl may use git clone directly
        if argv[:2] == ["git", "add"]:
            return "git-add"
        if argv[:2] == ["git", "commit"]:
            return "git-commit"
        if argv[:2] == ["git", "push"]:
            return "git-push"
        return "unknown"

    def fake_run(argv, **kwargs):
        kind = classify(argv)
        call_log.append((kind, list(argv), kwargs))
        if fail_on and kind == fail_on:
            raise subprocess.CalledProcessError(
                returncode=1, cmd=argv, stderr=fail_stderr
            )
        stdout = ""
        if kind == "gh-fork":
            stdout = fork_url + "\n"
        if kind == "gh-clone":
            # Materialize a fake clone dir: last arg is the dest path
            dest = _Path(argv[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / ".git").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=stdout, stderr=""
        )

    return fake_run


def test_create_happy_path_returns_fork_result(tmp_path, monkeypatch) -> None:
    """Happy path — fork + clone + unpack + config + push all succeed.

    ForkResult must carry: tenant_id, artifact_path, runbook_path (written),
    repo_url (from gh fork stdout).  config.local.yaml must be written into
    the clone with the exact helper output.
    """
    # Redirect PUBLISHED_ROOT so write_runbook writes under tmp, not repo.
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", tmp_path / "published")
    artifact = _make_fake_artifact(tmp_path, "acme")

    creator = GitHubApiForkCreator()
    call_log: list = []
    with patch(
        "subprocess.run",
        side_effect=_make_subprocess_dispatcher(
            call_log,
            fork_url="https://github.com/user/AutoService-acme",
        ),
    ):
        result = creator.create("acme", artifact)

    # Return value shape
    assert isinstance(result, ForkResult)
    assert result.tenant_id == "acme"
    assert result.artifact_path == artifact
    assert result.repo_url == "https://github.com/user/AutoService-acme"
    assert result.runbook_path.exists(), "runbook must be written"

    # Ordered pipeline invocation
    phases = [kind for (kind, _a, _k) in call_log]
    assert "gh-fork" in phases
    assert "gh-clone" in phases
    assert "git-add" in phases
    assert "git-commit" in phases
    assert "git-push" in phases
    # Clone must precede git-add (can't add files in a non-existent clone)
    assert phases.index("gh-clone") < phases.index("git-add")
    # Fork must precede clone
    assert phases.index("gh-fork") < phases.index("gh-clone")

    # config.local.yaml must be written with exact helper output
    # Find the clone dir — it's the last arg of the gh-clone call
    clone_argv = next(a for (k, a, _k) in call_log if k == "gh-clone")
    clone_dir = _Path(clone_argv[-1])
    cfg_path = clone_dir / ".autoservice" / "config.local.yaml"
    assert cfg_path.exists(), (
        "create() must write .autoservice/config.local.yaml in clone"
    )
    assert cfg_path.read_text(encoding="utf-8") == _fork_local_config_yaml_text(
        "acme"
    )

    # Tarball must have been extracted — plugins/acme/ exists in clone
    assert (clone_dir / "plugins" / "acme" / "plugin.yaml").exists()


def test_create_raises_on_clone_failure(tmp_path, monkeypatch) -> None:
    """Clone failure → ForkCreationError(phase="gh-repo-clone") + fork_name.

    Red-line: the fork WAS created (gh fork succeeded), so fork_name must
    be populated so admin knows what to clean up. Never auto-delete.
    """
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", tmp_path / "published")
    artifact = _make_fake_artifact(tmp_path, "acme")

    creator = GitHubApiForkCreator()
    call_log: list = []
    dispatcher = _make_subprocess_dispatcher(
        call_log, fail_on="gh-clone", fail_stderr="Permission denied"
    )
    with patch("subprocess.run", side_effect=dispatcher):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create("acme", artifact)

    e = excinfo.value
    assert e.phase == "gh-repo-clone"
    assert e.fork_name == "AutoService-acme", (
        "fork_name must be populated — gh fork succeeded, admin needs to "
        "know which repo to manually clean up if desired"
    )
    assert "Permission denied" in (e.stderr or "")


def test_create_raises_on_tar_extract_failure(tmp_path, monkeypatch) -> None:
    """Corrupt tarball → ForkCreationError(phase="tar-extract")."""
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", tmp_path / "published")

    # Write an artifact that tarfile.open will reject
    bad_artifact = tmp_path / "corrupt.tar.gz"
    bad_artifact.write_bytes(b"not a real tarball")

    creator = GitHubApiForkCreator()
    call_log: list = []
    with patch(
        "subprocess.run",
        side_effect=_make_subprocess_dispatcher(call_log),
    ):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create("acme", bad_artifact)

    assert excinfo.value.phase == "tar-extract"
    assert excinfo.value.fork_name == "AutoService-acme"


def test_create_raises_on_git_push_failure(tmp_path, monkeypatch) -> None:
    """git push fail → ForkCreationError(phase="git-push") + fork_name + stderr.

    At this point fork exists AND has a local commit that wasn't pushed —
    admin needs fork_name to decide cleanup or retry.
    """
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", tmp_path / "published")
    artifact = _make_fake_artifact(tmp_path, "acme")

    creator = GitHubApiForkCreator()
    call_log: list = []
    dispatcher = _make_subprocess_dispatcher(
        call_log, fail_on="git-push", fail_stderr="remote rejected: protected branch"
    )
    with patch("subprocess.run", side_effect=dispatcher):
        with pytest.raises(ForkCreationError) as excinfo:
            creator.create("acme", artifact)

    e = excinfo.value
    assert e.phase == "git-push"
    assert e.fork_name == "AutoService-acme"
    assert "protected branch" in (e.stderr or "")


def test_create_writes_config_with_helper_output(tmp_path, monkeypatch) -> None:
    """The config.local.yaml written into the clone MUST byte-match
    ``_fork_local_config_yaml_text(tenant_id)``.  Regression guard: if
    create() ever drifts from the helper the fork will refuse to boot.
    """
    monkeypatch.setattr(pub_mod, "PUBLISHED_ROOT", tmp_path / "published")
    artifact = _make_fake_artifact(tmp_path, "acme")

    creator = GitHubApiForkCreator()
    call_log: list = []
    with patch(
        "subprocess.run",
        side_effect=_make_subprocess_dispatcher(call_log),
    ):
        creator.create("acme", artifact)

    clone_argv = next(a for (k, a, _k) in call_log if k == "gh-clone")
    cfg_path = _Path(clone_argv[-1]) / ".autoservice" / "config.local.yaml"
    assert cfg_path.read_text(encoding="utf-8") == (
        "deployment_mode: tenant\ntenant_id: acme\n"
    )


def test_create_never_calls_gh_repo_delete() -> None:
    """Regression — the full create() method must also never issue `gh repo delete`.

    The check in test_create_fork_NEVER_calls_gh_repo_delete only covered the
    class as of T8B.1; widening here to catch any future drift in create().
    """
    src = inspect.getsource(GitHubApiForkCreator)
    assert "repo delete" not in src
    assert '"delete"' not in src
    assert "'delete'" not in src
