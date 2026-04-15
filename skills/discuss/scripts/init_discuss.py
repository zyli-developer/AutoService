"""Initialize a discuss session in the persistent dev worktree.

Behavior (v1.1):
- A single persistent worktree on branch ``discuss/dev`` hosts all discussions.
- Each session lives in ``.discuss/sessions/{date}-{slug}/`` inside that worktree.
- Final reports land in ``<worktree>/discussions/`` and are committed on ``discuss/dev``
  (they are NOT merged back to main).
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: uv pip install pyyaml", file=sys.stderr)
    sys.exit(1)

DEV_BRANCH = "discuss/dev"


def run_git(args, cwd, check=True):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        print(f"ERROR: git {' '.join(args)} failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result


def ensure_dev_worktree(repo: Path, worktree: Path) -> None:
    """Ensure the persistent dev worktree exists on branch discuss/dev."""
    if worktree.exists() and (worktree / ".git").exists():
        # Already a worktree — trust it
        return

    # Branch may already exist from a previous run whose worktree was removed
    branch_exists = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{DEV_BRANCH}"],
        cwd=repo,
        check=False,
    ).returncode == 0

    worktree.parent.mkdir(parents=True, exist_ok=True)

    if branch_exists:
        run_git(["worktree", "add", str(worktree), DEV_BRANCH], cwd=repo)
    else:
        run_git(["worktree", "add", "-b", DEV_BRANCH, str(worktree), "main"], cwd=repo)
    print(f"Created dev worktree at {worktree} on branch {DEV_BRANCH}")


def main():
    parser = argparse.ArgumentParser(description="Initialize a discuss session")
    parser.add_argument("--topic", required=True, help="Discussion topic")
    parser.add_argument("--slug", required=True, help="Short slug for session directory")
    parser.add_argument("--chat-id", required=True, help="Feishu chat ID")
    parser.add_argument("--started-by", required=True, help="Who started the discussion")
    parser.add_argument("--source", default=None, help="Source document path (optional)")
    parser.add_argument("--repo-path", required=True, help="Path to the git repository")
    parser.add_argument(
        "--worktree-path",
        required=True,
        help="Persistent dev worktree path (shared across sessions)",
    )
    args = parser.parse_args()

    repo = Path(args.repo_path).resolve()
    worktree = Path(args.worktree_path).resolve()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    session_name = f"{date_str}-{args.slug}"

    ensure_dev_worktree(repo, worktree)

    session_dir = worktree / ".discuss" / "sessions" / session_name
    if session_dir.exists():
        print(
            f"ERROR: session directory already exists: {session_dir}",
            file=sys.stderr,
        )
        sys.exit(1)
    session_dir.mkdir(parents=True)

    session = {
        "topic": args.topic,
        "source": args.source,
        "topic_type": "general",
        "status": "agenda_draft",
        "chat_id": args.chat_id,
        "started_by": args.started_by,
        "started_at": now.isoformat(),
        "participants": [
            {"name": args.started_by, "first_seen": now.isoformat()}
        ],
        "agenda_confirmed": False,
    }
    (session_dir / "session.yaml").write_text(
        yaml.dump(session, allow_unicode=True, sort_keys=False)
    )
    (session_dir / "transcript.md").write_text(
        f"# Discussion Transcript: {args.topic}\n\n"
    )
    (session_dir / "agenda.md").write_text("")

    (worktree / "discussions").mkdir(exist_ok=True)

    print(f"Discuss session '{session_name}' initialized.")
    print(f"  Worktree: {worktree}")
    print(f"  Branch:   {DEV_BRANCH}")
    print(f"  Session:  {session_dir}")


if __name__ == "__main__":
    main()
