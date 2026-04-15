"""Tests for discuss session initialization script (v1.1 persistent worktree)."""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

SCRIPT = Path(__file__).parent.parent / "skills" / "discuss" / "scripts" / "init_discuss.py"


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo for testing worktree operations."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _run_init(repo, worktree, *, topic, slug, chat_id, started_by, source=None):
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--topic", topic,
        "--slug", slug,
        "--chat-id", chat_id,
        "--started-by", started_by,
        "--repo-path", str(repo),
        "--worktree-path", str(worktree),
    ]
    if source:
        cmd.extend(["--source", source])
    return subprocess.run(cmd, capture_output=True, text=True)


class TestInitDiscuss:

    def test_creates_persistent_worktree_and_session(self, git_repo, tmp_path):
        """First invocation creates the dev worktree and a session dir inside it."""
        worktree = tmp_path / ".discuss-worktree"

        result = _run_init(
            git_repo, worktree,
            topic="优化登录流程", slug="optimize-login",
            chat_id="oc_test123", started_by="dai.ming",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        assert worktree.exists()
        # Persistent branch name is discuss/dev, not per-discussion
        branches = subprocess.run(
            ["git", "branch", "--list"],
            cwd=git_repo, capture_output=True, text=True,
        ).stdout
        assert "discuss/dev" in branches
        assert "discuss/optimize-login" not in branches

        # Session lives under .discuss/sessions/{date}-{slug}/
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_dir = worktree / ".discuss" / "sessions" / f"{today}-optimize-login"
        assert session_dir.exists()

        session = yaml.safe_load((session_dir / "session.yaml").read_text())
        assert session["topic"] == "优化登录流程"
        assert session["status"] == "agenda_draft"
        assert session["chat_id"] == "oc_test123"
        assert session["started_by"] == "dai.ming"
        assert session["topic_type"] == "general"

        assert (session_dir / "transcript.md").exists()
        assert (session_dir / "agenda.md").exists()

        # discussions/ directory prepared for final reports
        assert (worktree / "discussions").is_dir()

    def test_with_source_document(self, git_repo, tmp_path):
        worktree = tmp_path / ".discuss-worktree"
        result = _run_init(
            git_repo, worktree,
            topic="Review PRD", slug="review-prd",
            chat_id="oc_test456", started_by="allen",
            source="docs/prd.md",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_dir = worktree / ".discuss" / "sessions" / f"{today}-review-prd"
        session = yaml.safe_load((session_dir / "session.yaml").read_text())
        assert session["source"] == "docs/prd.md"

    def test_reuses_existing_worktree_for_new_session(self, git_repo, tmp_path):
        """Second invocation reuses the worktree and adds a new session dir."""
        worktree = tmp_path / ".discuss-worktree"
        first = _run_init(
            git_repo, worktree,
            topic="topic-A", slug="slug-a",
            chat_id="oc_A", started_by="a",
        )
        assert first.returncode == 0, f"stderr: {first.stderr}"

        second = _run_init(
            git_repo, worktree,
            topic="topic-B", slug="slug-b",
            chat_id="oc_B", started_by="b",
        )
        assert second.returncode == 0, f"stderr: {second.stderr}"

        # Only one worktree registered
        worktrees = subprocess.run(
            ["git", "worktree", "list"], cwd=git_repo,
            capture_output=True, text=True,
        ).stdout
        assert worktrees.count(str(worktree)) == 1

        # Both sessions present
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert (worktree / ".discuss" / "sessions" / f"{today}-slug-a").exists()
        assert (worktree / ".discuss" / "sessions" / f"{today}-slug-b").exists()

    def test_rejects_duplicate_session(self, git_repo, tmp_path):
        """Running twice with the same slug on the same date should fail."""
        worktree = tmp_path / ".discuss-worktree"
        first = _run_init(
            git_repo, worktree,
            topic="dup", slug="dup-slug",
            chat_id="oc_dup", started_by="d",
        )
        assert first.returncode == 0

        second = _run_init(
            git_repo, worktree,
            topic="dup", slug="dup-slug",
            chat_id="oc_dup", started_by="d",
        )
        assert second.returncode != 0
        assert "session directory already exists" in second.stderr
