"""Initialize a discuss session: create git worktree, branch, and state files."""

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


def main():
    parser = argparse.ArgumentParser(description="Initialize a discuss session")
    parser.add_argument("--topic", required=True, help="Discussion topic")
    parser.add_argument("--slug", required=True, help="Short slug for branch name")
    parser.add_argument("--chat-id", required=True, help="Feishu chat ID")
    parser.add_argument("--started-by", required=True, help="Who started the discussion")
    parser.add_argument("--source", default=None, help="Source document path (optional)")
    parser.add_argument("--repo-path", required=True, help="Path to the git repository")
    parser.add_argument("--worktree-path", required=True, help="Where to create the worktree")
    args = parser.parse_args()

    repo = Path(args.repo_path)
    worktree = Path(args.worktree_path)
    branch = f"discuss/{args.slug}"
    now = datetime.now(timezone.utc)

    # Create worktree with new branch
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree), "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to create worktree: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Created worktree at {worktree} on branch {branch}")

    # Create .discuss/ state directory
    discuss_dir = worktree / ".discuss"
    discuss_dir.mkdir(parents=True, exist_ok=True)

    # Create session.yaml
    session = {
        "topic": args.topic,
        "source": args.source,
        "topic_type": "general",
        "status": "agenda_draft",
        "chat_id": args.chat_id,
        "started_by": args.started_by,
        "started_at": now.isoformat(),
        "participants": [
            {
                "name": args.started_by,
                "first_seen": now.isoformat(),
            }
        ],
        "agenda_confirmed": False,
    }
    (discuss_dir / "session.yaml").write_text(
        yaml.dump(session, allow_unicode=True, sort_keys=False)
    )
    print(f"Created {discuss_dir / 'session.yaml'}")

    # Create empty transcript.md
    (discuss_dir / "transcript.md").write_text(
        f"# Discussion Transcript: {args.topic}\n\n"
    )
    print(f"Created {discuss_dir / 'transcript.md'}")

    # Create empty agenda.md
    (discuss_dir / "agenda.md").write_text("")
    print(f"Created {discuss_dir / 'agenda.md'}")

    # Ensure docs/discussions/ exists in worktree for later report output
    (worktree / "docs" / "discussions").mkdir(parents=True, exist_ok=True)

    print(f"Discuss session '{args.slug}' initialized.")
    print(f"  Worktree: {worktree}")
    print(f"  Branch:   {branch}")
    print(f"  State:    {discuss_dir}")


if __name__ == "__main__":
    main()
