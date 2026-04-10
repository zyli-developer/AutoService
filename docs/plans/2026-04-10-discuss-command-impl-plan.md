# Discuss Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `/discuss` command — a group discussion moderator in Feishu that guides free-form discussions, tracks consensus/divergence, and generates structured reports committed to git.

**Architecture:** Hybrid approach — channel-server handles routing (`runtime_mode: "discuss"`) and idle timeout detection; the discuss skill (loaded by channel.py) manages all discussion logic including worktree lifecycle, state tracking, agenda generation, and report output. State is persisted in worktree files for crash recovery.

**Tech Stack:** Python 3.11+, PyYAML, asyncio, websockets, git worktree, Claude Code skills (Markdown)

**Design Spec:** `docs/2026-04-10-discuss-command-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `skills/discuss/SKILL.md` | Create | Skill definition: trigger conditions, command routing, moderator behavior instructions |
| `skills/discuss/templates/topic-types.yaml` | Create | Topic type definitions with agenda hints |
| `skills/discuss/templates/report.md` | Create | Report generation template |
| `skills/discuss/templates/agenda.md` | Create | Agenda generation prompt template |
| `skills/discuss/scripts/init_discuss.py` | Create | Worktree + state file initialization script |
| `feishu/channel_server.py` | Modify | Add `/discuss` command handling, mode switching, idle timeout |
| `feishu/channel-instructions.md` | Modify | Add discuss mode routing rule, update runtime_mode enum |
| `tests/test_discuss_command.py` | Create | Tests for channel-server discuss routing + timeout |
| `tests/test_init_discuss.py` | Create | Tests for init_discuss.py script |

---

### Task 1: Channel-Server — `/discuss` Command Routing

Add `/discuss` command handling to `_handle_admin_message()` in channel-server, following the existing `/explain` pattern. This includes mode switching and recording the previous mode.

**Files:**
- Modify: `feishu/channel_server.py:43-44` (add `_discuss_prev_modes` field)
- Modify: `feishu/channel_server.py:339-404` (`_handle_admin_message` — add `/discuss` branch)
- Modify: `feishu/channel_server.py:1036-1053` (`help_text` — add `/discuss` entry)
- Test: `tests/test_discuss_command.py`

- [ ] **Step 1: Write test for `/discuss` start routing**

Create `tests/test_discuss_command.py`:

```python
"""Tests for /discuss command pipeline."""

import asyncio
import json

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from feishu.channel_server import ChannelServer


@pytest.fixture
def server():
    """Create a ChannelServer with Feishu disabled."""
    return ChannelServer(
        port=0,
        feishu_enabled=False,
        admin_chat_id="oc_admin_test",
    )


class TestDiscussCommand:

    @pytest.mark.asyncio
    async def test_discuss_no_topic_returns_usage(self, server):
        """'/discuss' with no arguments should return usage info."""
        server._reply_feishu = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/discuss"}
        await server._handle_admin_message(msg)
        server._reply_feishu.assert_called_once()
        reply_text = server._reply_feishu.call_args[0][1]
        assert "Usage" in reply_text or "/discuss" in reply_text

    @pytest.mark.asyncio
    async def test_discuss_start_routes_with_discuss_mode(self, server):
        """'/discuss "topic"' should route message with runtime_mode=discuss."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": '/discuss "优化登录流程"'}
        await server._handle_admin_message(msg)
        # Should acknowledge
        assert server._reply_feishu.call_count == 1
        # Should route with discuss mode
        server.route_message.assert_called_once()
        call_args = server.route_message.call_args
        routed_msg = call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert "优化登录流程" in routed_msg["text"]

    @pytest.mark.asyncio
    async def test_discuss_start_saves_previous_mode(self, server):
        """Starting discuss should save the previous runtime_mode."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "improve"
        msg = {"chat_id": "oc_admin_test", "text": '/discuss "topic"'}
        await server._handle_admin_message(msg)
        assert server._discuss_prev_modes.get("oc_admin_test") == "improve"
        assert server._chat_modes["oc_admin_test"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_end_restores_mode(self, server):
        """'/discuss end' should restore the previous runtime_mode."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "discuss"
        server._discuss_prev_modes["oc_admin_test"] = "production"
        msg = {"chat_id": "oc_admin_test", "text": "/discuss end"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert routed_msg["text"] == "/discuss end"
        # Mode restored after routing
        assert server._chat_modes["oc_admin_test"] == "production"
        assert "oc_admin_test" not in server._discuss_prev_modes

    @pytest.mark.asyncio
    async def test_discuss_status_routes(self, server):
        """'/discuss status' should route to channel instance."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        server._chat_modes["oc_admin_test"] = "discuss"
        msg = {"chat_id": "oc_admin_test", "text": "/discuss status"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_with_file_reference(self, server):
        """'/discuss @docs/prd.md' should include source in routed message."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()
        msg = {"chat_id": "oc_admin_test", "text": "/discuss @docs/prd.md"}
        await server._handle_admin_message(msg)
        server.route_message.assert_called_once()
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["runtime_mode"] == "discuss"
        assert "@docs/prd.md" in routed_msg["text"]

    @pytest.mark.asyncio
    async def test_help_includes_discuss(self, server):
        """Help text should list the /discuss command."""
        text = server.help_text()
        assert "/discuss" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_discuss_command.py -v`
Expected: FAIL — `_discuss_prev_modes` attribute not found, `/discuss` not handled

- [ ] **Step 3: Add `_discuss_prev_modes` field to ChannelServer**

In `feishu/channel_server.py`, after the existing `_chat_modes` class variable (line ~138):

```python
    _discuss_prev_modes: dict[str, str] = {}   # chat_id → mode before discuss
```

- [ ] **Step 4: Add `/discuss` handling to `_handle_admin_message`**

In `feishu/channel_server.py`, insert the `/discuss` block before the `/explain` block (before line 380). The handling goes after the `/inject` block and before `/explain`:

```python
        if text.startswith("/discuss"):
            args = text[len("/discuss"):].strip()

            # /discuss (no args) — show usage
            if not args:
                await self._reply_feishu(msg["chat_id"], (
                    "Usage:\n"
                    '  /discuss "话题描述"  — Start a discussion\n'
                    "  /discuss @docs/file.md  — Discuss a document\n"
                    '  /discuss @docs/file.md "聚焦方向"  — Document + focus\n'
                    "  /discuss end  — End discussion, generate report\n"
                    "  /discuss status  — Check discussion progress"
                ))
                return

            chat_id = msg["chat_id"]

            # /discuss end — route to skill, then restore mode
            if args == "end":
                discuss_msg = {
                    "type": "message",
                    "chat_id": chat_id,
                    "text": "/discuss end",
                    "message_id": f"discuss_{datetime.now(timezone.utc).timestamp():.0f}",
                    "user": "admin",
                    "user_id": "",
                    "runtime_mode": "discuss",
                    "business_mode": "customer_service",
                    "source": "admin",
                    "admin_chat_id": self.admin_chat_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                await self.route_message(chat_id, discuss_msg)
                # Restore previous mode
                prev_mode = self._discuss_prev_modes.pop(chat_id, "production")
                self._chat_modes[chat_id] = prev_mode
                # Clean up idle tracking
                self._discuss_sessions.pop(chat_id, None)
                return

            # /discuss status — route to skill
            if args == "status":
                discuss_msg = {
                    "type": "message",
                    "chat_id": chat_id,
                    "text": "/discuss status",
                    "message_id": f"discuss_{datetime.now(timezone.utc).timestamp():.0f}",
                    "user": "admin",
                    "user_id": "",
                    "runtime_mode": "discuss",
                    "business_mode": "customer_service",
                    "source": "admin",
                    "admin_chat_id": self.admin_chat_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                await self.route_message(chat_id, discuss_msg)
                return

            # /discuss "topic" or /discuss @file — start discussion
            # Save previous mode and switch to discuss
            prev_mode = self._chat_modes.get(chat_id, "production")
            self._discuss_prev_modes[chat_id] = prev_mode
            self._chat_modes[chat_id] = "discuss"

            await self._reply_feishu(chat_id, f"📋 正在启动讨论...")
            discuss_msg = {
                "type": "message",
                "chat_id": chat_id,
                "text": text,  # full command including /discuss prefix
                "message_id": f"discuss_{datetime.now(timezone.utc).timestamp():.0f}",
                "user": "admin",
                "user_id": "",
                "runtime_mode": "discuss",
                "business_mode": "customer_service",
                "source": "admin",
                "admin_chat_id": self.admin_chat_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await self.route_message(chat_id, discuss_msg)
            return
```

- [ ] **Step 5: Update `help_text` to include `/discuss`**

In `feishu/channel_server.py`, in the `help_text()` method, add after the `/explain` entry:

```python
            "/discuss <话题> — Start a group discussion\n"
            "  /discuss end — End discussion and generate report\n"
            "  /discuss status — Check discussion progress\n"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_discuss_command.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_discuss_command.py feishu/channel_server.py
git commit -m "feat(discuss): add /discuss command routing to channel-server

Add /discuss start/end/status command handling with mode switching.
Records previous mode and restores on /discuss end."
```

---

### Task 2: Channel-Server — Idle Timeout Detection

Add background timer that monitors discuss sessions and sends idle reminders.

**Files:**
- Modify: `feishu/channel_server.py:43-44` (add `_discuss_sessions` field, `DISCUSS_IDLE_TIMEOUT` constant)
- Modify: `feishu/channel_server.py:84-101` (`start()` — launch timer task)
- Modify: `feishu/channel_server.py:860-900` (`route_message()` — update timestamp)
- Test: `tests/test_discuss_command.py` (add timeout tests)

- [ ] **Step 1: Write tests for idle timeout**

Append to `tests/test_discuss_command.py`:

```python
import time


class TestDiscussIdleTimeout:

    @pytest.mark.asyncio
    async def test_discuss_message_updates_timestamp(self, server):
        """Messages with runtime_mode=discuss should update idle timestamp."""
        server._discuss_sessions = {}
        msg = {
            "type": "message",
            "chat_id": "oc_discuss_test",
            "text": "some discussion message",
            "runtime_mode": "discuss",
        }
        # Simulate route_message updating timestamp
        await server.route_message("oc_discuss_test", msg)
        assert "oc_discuss_test" in server._discuss_sessions

    @pytest.mark.asyncio
    async def test_idle_check_sends_reminder(self, server):
        """Idle checker should send reminder when timeout exceeded."""
        server._discuss_sessions = {
            "oc_idle_test": time.time() - 1000,  # long ago
        }
        # Register a mock wildcard instance to receive the reminder
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 0)
        from feishu.channel_server import Instance
        inst = Instance(
            ws=mock_ws,
            instance_id="test-channel",
            role="developer",
            chat_ids=["*"],
        )
        server.wildcard_instances.append(inst)
        server._ws_to_instance[mock_ws] = inst

        await server._check_discuss_idle()

        # Should have sent a discuss_idle_reminder
        assert mock_ws.send.call_count >= 1
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["type"] == "discuss_idle_reminder"
        assert sent_msg["chat_id"] == "oc_idle_test"

    @pytest.mark.asyncio
    async def test_idle_check_skips_active_sessions(self, server):
        """Idle checker should not send reminder for recently active sessions."""
        server._discuss_sessions = {
            "oc_active_test": time.time(),  # just now
        }
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 0)
        from feishu.channel_server import Instance
        inst = Instance(
            ws=mock_ws,
            instance_id="test-channel",
            role="developer",
            chat_ids=["*"],
        )
        server.wildcard_instances.append(inst)
        server._ws_to_instance[mock_ws] = inst

        await server._check_discuss_idle()

        mock_ws.send.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_discuss_command.py::TestDiscussIdleTimeout -v`
Expected: FAIL — `_discuss_sessions` and `_check_discuss_idle` not found

- [ ] **Step 3: Add idle timeout constants and field**

In `feishu/channel_server.py`, add constant after `ACK_EMOJI` (line ~28):

```python
DISCUSS_IDLE_TIMEOUT = 15 * 60  # 15 minutes
```

Add class variable after `_discuss_prev_modes`:

```python
    _discuss_sessions: dict[str, float] = {}   # chat_id → last_message_timestamp
```

- [ ] **Step 4: Update `route_message` to track discuss timestamps**

In `feishu/channel_server.py`, at the beginning of `route_message()` (after line 861), add:

```python
        # Track discuss session activity for idle detection
        if message.get("runtime_mode") == "discuss":
            self._discuss_sessions[chat_id] = time.time()
```

Add `import time` at the top of the file with the other imports.

- [ ] **Step 5: Implement `_check_discuss_idle` method**

In `feishu/channel_server.py`, add method to `ChannelServer` class (after `route_message`):

```python
    async def _check_discuss_idle(self) -> None:
        """Check for idle discuss sessions and send reminders."""
        now = time.time()
        idle_chats = [
            (chat_id, now - last_ts)
            for chat_id, last_ts in self._discuss_sessions.items()
            if now - last_ts > DISCUSS_IDLE_TIMEOUT
        ]
        for chat_id, idle_secs in idle_chats:
            idle_minutes = int(idle_secs // 60)
            reminder = {
                "type": "discuss_idle_reminder",
                "chat_id": chat_id,
                "idle_minutes": idle_minutes,
            }
            # Route to all instances that handle this chat_id
            for inst in self.wildcard_instances:
                await self._send(inst.ws, reminder)
            if chat_id in self.exact_routes:
                await self._send(self.exact_routes[chat_id].ws, reminder)
            log.info("Discuss idle reminder sent for %s (%d min)", chat_id, idle_minutes)
            # Update timestamp to avoid spamming — next reminder after another timeout period
            self._discuss_sessions[chat_id] = now
```

- [ ] **Step 6: Add background timer task to `start()`**

In `feishu/channel_server.py`, in the `start()` method, after the Feishu task creation (after line 99):

```python
        # Discuss idle checker — runs every 60 seconds
        idle_task = asyncio.create_task(self._run_discuss_idle_checker(), name="discuss-idle")
        self._tasks.append(idle_task)
```

And add the runner method:

```python
    async def _run_discuss_idle_checker(self) -> None:
        """Periodically check for idle discuss sessions."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # 60 seconds elapsed, do the check
            try:
                await self._check_discuss_idle()
            except Exception as e:
                log.warning("Discuss idle check error: %s", e)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_discuss_command.py -v`
Expected: All 10 tests PASS

- [ ] **Step 8: Commit**

```bash
git add feishu/channel_server.py tests/test_discuss_command.py
git commit -m "feat(discuss): add idle timeout detection for discuss sessions

Background timer checks every 60s, sends discuss_idle_reminder
after 15 min of inactivity. Reminder is sent to channel instances,
not directly to Feishu — the skill decides how to notify."
```

---

### Task 3: Update `channel-instructions.md`

Add discuss mode routing rule and update runtime_mode enum.

**Files:**
- Modify: `feishu/channel-instructions.md:6` (update enum)
- Modify: `feishu/channel-instructions.md` (add discuss mode section)

- [ ] **Step 1: Update runtime_mode enum**

In `feishu/channel-instructions.md`, line 6, change:

```markdown
- `runtime_mode`: "production" | "improve" | "explain"
```

to:

```markdown
- `runtime_mode`: "production" | "improve" | "explain" | "discuss"
```

- [ ] **Step 2: Add discuss mode routing section**

In `feishu/channel-instructions.md`, after the `### explain mode` section (after line 28), add:

```markdown
### discuss mode
Use /discuss skill. AI acts as discussion moderator for group conversations.
Messages in this mode are part of an ongoing group discussion session.
The discuss skill manages the full lifecycle: agenda generation, discussion tracking, and report generation.

When receiving a `discuss_idle_reminder` message (type field, not channel tag), remind the discussion initiator that the discussion has been idle and ask whether they want to end it and generate a report.
```

- [ ] **Step 3: Commit**

```bash
git add feishu/channel-instructions.md
git commit -m "docs(discuss): add discuss mode to channel-instructions

Update runtime_mode enum and add discuss mode routing rule."
```

---

### Task 4: `init_discuss.py` — Worktree + State Initialization

Create the script that initializes a git worktree and discussion state files.

**Files:**
- Create: `skills/discuss/scripts/init_discuss.py`
- Test: `tests/test_init_discuss.py`

- [ ] **Step 1: Write tests for init_discuss.py**

Create `tests/test_init_discuss.py`:

```python
"""Tests for discuss session initialization script."""

import json
import subprocess
import sys
import tempfile
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
        # Verify we can remove the worktree
        result = subprocess.run(
            ["git", "worktree", "remove", str(worktree_path)],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert not worktree_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init_discuss.py -v`
Expected: FAIL — script not found

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p skills/discuss/scripts
mkdir -p skills/discuss/templates
```

- [ ] **Step 4: Implement `init_discuss.py`**

Create `skills/discuss/scripts/init_discuss.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_init_discuss.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add skills/discuss/scripts/init_discuss.py tests/test_init_discuss.py
git commit -m "feat(discuss): add init_discuss.py for worktree + state setup

Creates git worktree on discuss/{slug} branch, initializes
session.yaml, transcript.md, agenda.md in .discuss/ directory."
```

---

### Task 5: Skill Templates

Create the topic types, agenda prompt, and report template files.

**Files:**
- Create: `skills/discuss/templates/topic-types.yaml`
- Create: `skills/discuss/templates/agenda.md`
- Create: `skills/discuss/templates/report.md`

- [ ] **Step 1: Create `topic-types.yaml`**

Create `skills/discuss/templates/topic-types.yaml`:

```yaml
general:
  label: "通用讨论"
  agenda_hint: "根据话题内容，生成 3-5 个讨论维度"

# --- 预留，第一版不实现 ---
# bug:
#   label: "Bug 讨论"
#   agenda_hint: "围绕复现步骤、影响范围、根因分析、修复方案展开"
#
# feature:
#   label: "功能需求讨论"
#   agenda_hint: "围绕用户场景、需求价值、技术可行性、优先级展开"
#
# deploy:
#   label: "部署方案讨论"
#   agenda_hint: "围绕变更内容、回滚策略、影响评估、上线计划展开"
```

- [ ] **Step 2: Create `agenda.md` template**

Create `skills/discuss/templates/agenda.md`:

```markdown
# Agenda Generation Guide

Given the discussion topic and optional source document, generate a focused agenda.

## Input
- **Topic:** {topic}
- **Source document:** {source} (if provided, read it first)
- **Topic type:** {topic_type}

## Rules
1. Generate 3-5 discussion dimensions relevant to the topic
2. Each dimension should be a concrete question, not a vague category
3. Order from foundational (context/problem) to actionable (solutions/priorities)
4. If a source document is provided, tailor questions to its content
5. Keep each question to one sentence

## Output format
Present the agenda as a numbered list. Example:

1. 当前登录流程的主要痛点是什么？
2. 有哪些改进方案？各自的优劣？
3. 对用户体验的影响评估
4. 安全性影响评估
5. 实施优先级和依赖项

Ask the discussion initiator to confirm or adjust the agenda before proceeding.
```

- [ ] **Step 3: Create `report.md` template**

Create `skills/discuss/templates/report.md`:

```markdown
# Report Generation Guide

Generate the final discussion report from the transcript and agenda.

## Input
- Session metadata from `.discuss/session.yaml`
- Confirmed agenda from `.discuss/agenda.md`
- Full transcript from `.discuss/transcript.md`

## Report structure

```
# 讨论报告：{topic}

| 字段 | 值 |
|------|-----|
| 发起人 | {started_by} |
| 日期 | {date} |
| 时长 | {duration} |
| 参与者 | {participants, comma-separated} |
| 素材 | {source, or "无"} |

## 议程

{numbered agenda items}

## 讨论纪要

### 1. {agenda_item}

**共识/分歧：** {one-line summary of whether consensus was reached}

- **{participant}**: {their viewpoint, condensed}
- **{participant}**: {their viewpoint, condensed}

{repeat for each agenda item}

## Action Items

- [ ] **{assignee}** — {specific task}, {deadline or TBD}

## 未决问题

- {any unresolved items that need follow-up}
```

## Rules
1. Organize by agenda topic, NOT chronologically
2. For each topic, clearly label as **共识** (consensus) or **分歧** (divergence)
3. Attribute viewpoints to specific participants
4. Extract concrete action items with assignees where mentioned
5. If no assignee was discussed, mark as TBD
6. List unresolved questions separately
7. If a topic had no discussion, note "未讨论" (not discussed)
```

- [ ] **Step 4: Commit**

```bash
git add skills/discuss/templates/
git commit -m "feat(discuss): add skill templates for agenda, report, and topic types"
```

---

### Task 6: `SKILL.md` — Discuss Skill Definition

Create the main skill file that defines how Claude Code handles the discuss command.

**Files:**
- Create: `skills/discuss/SKILL.md`

- [ ] **Step 1: Create `SKILL.md`**

Create `skills/discuss/SKILL.md`:

````markdown
---
name: discuss
description: "Group discussion moderator skill. Use when runtime_mode is 'discuss'. Manages discussion lifecycle: agenda generation, free-form group discussion tracking, consensus/divergence identification, and structured report generation. TRIGGER when: runtime_mode is 'discuss', user says '/discuss', or message type is 'discuss_idle_reminder'."
---

# /discuss — Group Discussion Moderator

When invoked, this skill moderates a structured group discussion in a Feishu chat. You guide free-form conversation, track viewpoints per participant, identify consensus and divergence, and generate a report at the end.

## Command Routing

Parse the incoming message to determine the action:

| Pattern | Action |
|---------|--------|
| `/discuss "topic"` or `/discuss @file` | **Start discussion** — go to [Start Discussion](#1-start-discussion) |
| `/discuss end` | **End discussion** — go to [End Discussion](#3-end-discussion) |
| `/discuss status` | **Show status** — go to [Discussion Status](#4-discussion-status) |
| `discuss_idle_reminder` message type | **Idle reminder** — go to [Idle Reminder](#5-idle-reminder) |
| Any other message while in discuss mode | **Discussion message** — go to [Process Message](#2-process-message) |

---

## 1. Start Discussion

**Trigger:** First message with `runtime_mode: "discuss"` containing `/discuss` prefix.

### Phase 1 — Initialize

1. **Parse the command** to extract topic and optional source document:
   - `/discuss "优化登录流程"` → topic="优化登录流程", source=null
   - `/discuss @docs/prd.md` → topic=filename, source="docs/prd.md"
   - `/discuss @docs/prd.md "重点讨论安全性"` → topic="重点讨论安全性", source="docs/prd.md"

2. **Derive slug** from topic: lowercase, replace spaces/special chars with hyphens, truncate to 50 chars.

3. **Run init script** to create worktree and state files:
   ```bash
   uv run skills/discuss/scripts/init_discuss.py \
     --topic "{topic}" \
     --slug "{slug}" \
     --chat-id "{chat_id}" \
     --started-by "{user}" \
     --source "{source}" \
     --repo-path "$(git rev-parse --show-toplevel)" \
     --worktree-path "/tmp/discuss-{chat_id}-$(date +%s)"
   ```

4. **If source document exists**, read it to understand the context.

### Phase 2 — Generate Agenda

1. Read `skills/discuss/templates/agenda.md` for the generation guide.
2. Read `skills/discuss/templates/topic-types.yaml` and use the `general` type's `agenda_hint`.
3. Generate 3-5 discussion questions tailored to the topic (and source document if provided).
4. Reply to the group with the proposed agenda. Ask the initiator to confirm or adjust.
5. Write the agenda to `.discuss/agenda.md` in the worktree.
6. Update `.discuss/session.yaml`: set `status: agenda_draft`.

### Phase 3 — Agenda Confirmation

When the initiator confirms (says "ok", "确认", "可以", "没问题", etc.) or adjusts:
- If confirmed: update `session.yaml` → `status: active`, `agenda_confirmed: true`
- If adjusted: update the agenda, ask for confirmation again
- Reply: "讨论正式开始，大家可以针对以上议题自由发言。"

## 2. Process Message

**Trigger:** Any message while `session.yaml` status is `active`.

For each incoming message:

1. **Identify the speaker** from the message `user` field.
2. **Add participant** to `session.yaml` if not already listed.
3. **Determine which agenda items** the message relates to. Tag with `[议题 N]`.
4. **Append to transcript** in `.discuss/transcript.md`:
   ```markdown
   ## {timestamp} — {user}
   [议题 {N}] {message content}
   ```
5. **Track consensus/divergence** mentally across the discussion.

### Moderator Behaviors

- **Pushing forward:** When one topic has sufficient discussion, suggest moving to the next: "议题 1 大家意见比较一致了，我们来看看议题 2？"
- **Off-topic redirect:** When messages are unrelated to any agenda item, gently redirect: "这个点很有意思，不过我们先聚焦在当前议题上？" Tag as `[题外]` in transcript.
- **Summary checkpoints:** After several messages on one topic, briefly summarize what's been said so far to keep everyone aligned.
- **Do NOT** reply to every single message — only intervene when it adds value (pushing forward, summarizing, redirecting).

## 3. End Discussion

**Trigger:** `/discuss end` message.

1. **Verify the sender** is the discussion initiator (`started_by` in `session.yaml`). If not, reply: "只有讨论发起人 {started_by} 可以结束讨论。"

2. **Generate report:**
   - Read `skills/discuss/templates/report.md` for the report structure guide.
   - Read `.discuss/session.yaml` for metadata.
   - Read `.discuss/agenda.md` for the agenda.
   - Read `.discuss/transcript.md` for the full transcript.
   - Generate the structured report following the template.

3. **Save and commit:**
   ```bash
   # Write report to worktree
   # (use Write tool to create the report file)

   # Copy to docs/discussions/ and commit
   cd {worktree_path}
   cp .discuss/report.md docs/discussions/{date}-{slug}.md
   git add docs/discussions/{date}-{slug}.md
   git commit -m "docs(discuss): {topic} — discussion report

   Participants: {participant_list}
   Duration: {duration}
   Action items: {count}"

   # Merge to main and cleanup
   cd $(git rev-parse --show-toplevel)
   git merge discuss/{slug}
   git worktree remove {worktree_path}
   git branch -d discuss/{slug}
   ```

4. **Reply to group** with a summary: the key conclusions, action items, and where the full report is saved.

5. **Update session.yaml** → `status: ended` (before cleanup, for crash recovery).

## 4. Discussion Status

**Trigger:** `/discuss status` message.

Read `.discuss/session.yaml` and `.discuss/transcript.md`, then reply with:
- Current status (agenda_draft / active / ended)
- Topic and agenda items
- Number of participants and their names
- Number of messages per agenda item
- Duration so far

## 5. Idle Reminder

**Trigger:** Message with `type: "discuss_idle_reminder"`.

Reply to the group:
"讨论已静默 {idle_minutes} 分钟。@{started_by} 是否要结束讨论并生成报告？发送 `/discuss end` 结束，或继续发言继续讨论。"

## Error Handling

| Scenario | Response |
|----------|----------|
| `/discuss` while another discuss is active | "当前已有讨论进行中，请先 `/discuss end` 结束当前讨论。" |
| Non-initiator sends `/discuss end` | "只有讨论发起人 {started_by} 可以结束讨论。" |
| `/discuss end` with no substantive messages | Generate minimal report noting no discussion occurred |
| Worktree creation fails | Reply with error, do not enter discuss state |
| Session recovery after restart | Read `.discuss/session.yaml`, resume from current status, notify group: "我回来了，讨论继续。" |
````

- [ ] **Step 2: Commit**

```bash
git add skills/discuss/SKILL.md
git commit -m "feat(discuss): add SKILL.md with full moderator behavior definition

Covers start/process/end/status/idle-reminder flows,
moderator behaviors, error handling, and session recovery."
```

---

### Task 7: Channel.py — Handle `discuss_idle_reminder` Message Type

Add handling for the `discuss_idle_reminder` internal message type in channel.py's message consumption.

**Files:**
- Modify: `feishu/channel.py:90-100` (`_message_loop` — handle new message type)

- [ ] **Step 1: Read current `_message_loop` implementation**

Read `feishu/channel.py` lines 90-105 to see message handling.

- [ ] **Step 2: Update `_message_loop` to handle discuss_idle_reminder**

In `feishu/channel.py`, in the `_message_loop` method, update the condition at line ~96 to also forward `discuss_idle_reminder` messages:

```python
    async def _message_loop(self, ws):
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "message":
                await self._message_queue.put(msg)
            elif msg.get("type") == "discuss_idle_reminder":
                # Convert to a message that Claude Code can process via the skill
                reminder_msg = {
                    "type": "message",
                    "chat_id": msg["chat_id"],
                    "text": f"[DISCUSS_IDLE_REMINDER] Discussion has been idle for {msg.get('idle_minutes', 15)} minutes.",
                    "message_id": f"idle_{msg['chat_id']}",
                    "user": "system",
                    "user_id": "",
                    "runtime_mode": "discuss",
                    "business_mode": "customer_service",
                    "source": "system",
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
                await self._message_queue.put(reminder_msg)
            elif msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif msg.get("type") == "error":
                log.error(f"Server error: {msg}")
```

- [ ] **Step 3: Commit**

```bash
git add feishu/channel.py
git commit -m "feat(discuss): handle discuss_idle_reminder in channel.py

Converts idle reminder from channel-server into a message
that Claude Code can process via the discuss skill."
```

---

### Task 8: Integration Test

Add an integration test that simulates the full discuss lifecycle through channel-server.

**Files:**
- Modify: `tests/test_discuss_command.py` (add integration test class)

- [ ] **Step 1: Write integration test**

Append to `tests/test_discuss_command.py`:

```python
class TestDiscussIntegration:
    """Integration tests simulating discuss lifecycle through channel-server."""

    @pytest.mark.asyncio
    async def test_discuss_lifecycle_mode_switching(self, server):
        """Full lifecycle: start → messages route as discuss → end → mode restored."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()

        chat_id = "oc_admin_test"

        # 1. Start discuss
        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": '/discuss "架构设计讨论"',
        })
        assert server._chat_modes[chat_id] == "discuss"
        assert server._discuss_prev_modes[chat_id] == "production"

        # 2. Simulate a regular message during discuss mode
        # In real flow, channel-server reads _chat_modes to set runtime_mode
        current_mode = server._chat_modes.get(chat_id, "production")
        assert current_mode == "discuss"

        # 3. End discuss
        server.route_message.reset_mock()
        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": "/discuss end",
        })
        # Mode should be restored
        assert server._chat_modes[chat_id] == "production"
        assert chat_id not in server._discuss_prev_modes
        # End command should have been routed
        routed_msg = server.route_message.call_args[0][1]
        assert routed_msg["text"] == "/discuss end"
        assert routed_msg["runtime_mode"] == "discuss"

    @pytest.mark.asyncio
    async def test_discuss_end_clears_idle_tracking(self, server):
        """Ending a discuss session should remove it from idle tracking."""
        server._reply_feishu = AsyncMock()
        server.route_message = AsyncMock()

        chat_id = "oc_admin_test"
        server._chat_modes[chat_id] = "discuss"
        server._discuss_prev_modes[chat_id] = "production"
        server._discuss_sessions[chat_id] = time.time()

        await server._handle_admin_message({
            "chat_id": chat_id,
            "text": "/discuss end",
        })

        assert chat_id not in server._discuss_sessions
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/test_discuss_command.py -v`
Expected: All 12 tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_discuss_command.py
git commit -m "test(discuss): add integration tests for discuss lifecycle

Tests full mode switching lifecycle and idle tracking cleanup."
```

---

### Task 9: Make Setup Integration

Ensure `make setup` symlinks the new discuss skill into `.claude/skills/`.

**Files:**
- Modify: `Makefile` (if skill symlinking is pattern-based, verify it picks up `discuss/`)

- [ ] **Step 1: Check current Makefile setup target**

Read the `Makefile` to understand how skill symlinking works.

- [ ] **Step 2: Run `make setup` and verify**

```bash
make setup
```

Verify that `skills/discuss/` is accessible:

```bash
ls -la .claude/skills/discuss/ 2>/dev/null || echo "Symlink not created — check Makefile"
```

- [ ] **Step 3: Run `make check` to verify plugin discovery**

```bash
make check
```

Expected: No errors related to discuss skill.

- [ ] **Step 4: Commit (if Makefile changes were needed)**

```bash
# Only if Makefile needed changes
git add Makefile
git commit -m "chore: add discuss skill to make setup"
```

---

## Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | Channel-server `/discuss` command routing | 7 tests |
| 2 | Idle timeout detection | 3 tests |
| 3 | Update channel-instructions.md | — |
| 4 | `init_discuss.py` worktree setup | 3 tests |
| 5 | Skill templates (agenda, report, topic-types) | — |
| 6 | `SKILL.md` moderator definition | — |
| 7 | Channel.py idle reminder handling | — |
| 8 | Integration tests | 2 tests |
| 9 | Make setup verification | — |

**Total: 9 tasks, 15 tests**

After all tasks complete, the `/discuss` command will be fully functional: routing through channel-server, skill-based moderation, worktree state management, report generation, and idle timeout reminders.
