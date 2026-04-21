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
