"""Tests for discuss session initialization script."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo for testing worktree operations."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    # Create initial commit so we have a main branch
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


class TestInitDiscuss:

    def test_creates_worktree_and_state(self, git_repo, tmp_path):
        """init_discuss should create worktree, branch, and state files."""
        worktree_path = tmp_path / "discuss-worktree"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "skills" / "discuss" / "scripts" / "init_discuss.py"),
                "--topic", "优化登录流程",
                "--slug", "optimize-login",
                "--chat-id", "oc_test123",
                "--started-by", "dai.ming",
                "--repo-path", str(git_repo),
                "--worktree-path", str(worktree_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Verify worktree exists
        assert worktree_path.exists()

        # Verify branch was created
        branch_result = subprocess.run(
            ["git", "branch", "--list", "discuss/optimize-login"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert "discuss/optimize-login" in branch_result.stdout

        # Verify state files
        discuss_dir = worktree_path / ".discuss"
        assert discuss_dir.exists()

        session = yaml.safe_load((discuss_dir / "session.yaml").read_text())
        assert session["topic"] == "优化登录流程"
        assert session["status"] == "agenda_draft"
        assert session["chat_id"] == "oc_test123"
        assert session["started_by"] == "dai.ming"
        assert session["topic_type"] == "general"

        assert (discuss_dir / "transcript.md").exists()
        assert (discuss_dir / "agenda.md").exists()

    def test_with_source_document(self, git_repo, tmp_path):
        """init_discuss with --source should record the source path."""
        worktree_path = tmp_path / "discuss-worktree-src"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "skills" / "discuss" / "scripts" / "init_discuss.py"),
                "--topic", "Review PRD",
                "--slug", "review-prd",
                "--chat-id", "oc_test456",
                "--started-by", "allen",
                "--source", "docs/prd.md",
                "--repo-path", str(git_repo),
                "--worktree-path", str(worktree_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        session = yaml.safe_load((worktree_path / ".discuss" / "session.yaml").read_text())
        assert session["source"] == "docs/prd.md"

    def test_cleanup(self, git_repo, tmp_path):
        """Worktree should be removable after creation."""
        worktree_path = tmp_path / "discuss-cleanup"
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "skills" / "discuss" / "scripts" / "init_discuss.py"),
                "--topic", "test",
                "--slug", "test-cleanup",
                "--chat-id", "oc_cleanup",
                "--started-by", "test",
                "--repo-path", str(git_repo),
                "--worktree-path", str(worktree_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # Verify we can remove the worktree (--force needed because .discuss/ has untracked files)
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert not worktree_path.exists()
