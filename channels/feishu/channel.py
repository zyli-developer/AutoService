#!/usr/bin/env python3
"""
autoservice-channel: Claude Code Channel MCP Server
Connects to channel-server.py via WebSocket, bridges messages to Claude Code via MCP stdio.

Architecture:
- ChannelClient connects to channel-server via WebSocket (auto-reconnect)
- MCP low-level Server + stdio_server()
- consume_messages reads from ChannelClient queue, injects into MCP write_stream
- server.run, ChannelClient.connect, and consume_messages run in parallel via anyio task group

Plugin tools from socialware.plugin_loader are dynamically registered
alongside the core reply/react tools.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import anyio
import websockets
import mcp.server.stdio
from mcp.server.lowlevel import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, Tool, TextContent

# -- Config ------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / ".autoservice" / "logs" / "channel.log"
INSTRUCTIONS_PATH = Path(__file__).parent / "channel-instructions.md"
IDENTITY_PATH = PROJECT_ROOT / ".autoservice" / "identity.yaml"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="[autoservice-channel] %(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
# File gets DEBUG, stderr gets INFO
logging.getLogger().handlers[0].setLevel(logging.DEBUG)
logging.getLogger().handlers[1].setLevel(logging.INFO)
log = logging.getLogger("autoservice-channel")
log.info(f"=== Channel started PID={os.getpid()} ===")


# -- Channel Server Client ---------------------------------------------------


class ChannelClient:
    """WebSocket client that connects to channel-server.py."""

    def __init__(self, server_url="ws://localhost:9999", chat_ids=None,
                 instance_id="", runtime_mode="production"):
        self.server_url = server_url
        self.chat_ids = chat_ids or ["*"]
        self.instance_id = instance_id or f"channel-{os.getpid()}"
        self.runtime_mode = runtime_mode
        self.ws = None
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self):
        """Connect to channel-server with auto-reconnect."""
        while True:
            try:
                async with websockets.connect(self.server_url) as ws:
                    self.ws = ws
                    await self._register(ws)
                    await self._message_loop(ws)
            except Exception as e:
                log.warning(f"channel-server disconnected ({type(e).__name__}: {e}), retrying in 3s...")
                self.ws = None
                await asyncio.sleep(3)

    async def _register(self, ws):
        await ws.send(json.dumps({
            "type": "register",
            "role": "developer" if "*" in self.chat_ids else "production",
            "chat_ids": self.chat_ids,
            "instance_id": self.instance_id,
            "runtime_mode": self.runtime_mode,
        }))
        resp = json.loads(await ws.recv())
        if resp.get("type") == "error":
            log.error(f"Registration failed: {resp}")
            raise RuntimeError(resp.get("message", "Registration failed"))
        log.info(f"Registered with channel-server: chat_ids={self.chat_ids}")

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

    async def send_reply(self, chat_id, text):
        if self.ws:
            await self.ws.send(json.dumps({
                "type": "reply", "chat_id": chat_id, "text": text,
            }))

    async def send_react(self, message_id, emoji_type):
        if self.ws:
            await self.ws.send(json.dumps({
                "type": "react", "message_id": message_id, "emoji_type": emoji_type,
            }))

    async def send_ux_event(self, chat_id, event, data=None):
        if self.ws:
            await self.ws.send(json.dumps({
                "type": "ux_event", "chat_id": chat_id, "event": event,
                "data": data or {},
            }))


# -- Module-level state for tool handlers ------------------------------------

_channel_client: ChannelClient | None = None
_event_loop: asyncio.AbstractEventLoop | None = None


# -- MCP Notification Injection -----------------------------------------------


async def inject_message(write_stream, msg: dict):
    """Send a channel notification to Claude Code via the MCP write stream."""
    # Build meta — omit None values to avoid potential issues with Claude Code
    meta = {
        "chat_id": msg["chat_id"],
        "message_id": msg.get("message_id", ""),
        "user": msg.get("user", "unknown"),
        "user_id": msg.get("user_id", ""),
        "runtime_mode": msg.get("runtime_mode", "production"),
        "business_mode": msg.get("business_mode", "sales"),
        "source": msg.get("source", "feishu"),
        "ts": msg.get("ts", datetime.now(tz=timezone.utc).isoformat()),
    }
    if msg.get("routed_to"):
        meta["routed_to"] = msg["routed_to"]
    if msg.get("file_path"):
        meta["file_path"] = msg["file_path"]
    if msg.get("admin_chat_id"):
        meta["admin_chat_id"] = msg["admin_chat_id"]

    params = {"content": msg["text"], "meta": meta}

    log.debug(f"inject_message params: {json.dumps(params, ensure_ascii=False)[:500]}")

    notification = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/claude/channel",
        params=params,
    )
    session_msg = SessionMessage(message=JSONRPCMessage(notification))
    log.debug(f"inject_message SessionMessage: {session_msg}")
    await write_stream.send(session_msg)
    log.info(f"Injected: '{msg['text'][:60]}...' from {msg.get('user', '?')}")


# -- MCP Server + Tools -------------------------------------------------------


_FALLBACK_INSTRUCTIONS = (
    "Messages from Feishu arrive as <channel> tags with chat_id, user, ts attributes. "
    "Reply with the reply tool -- your transcript never reaches the Feishu chat. "
    "When users send requests, use available plugin tools to process them, "
    "then reply with the result."
)
_instructions_mtime: float = 0.0
_identity_mtime: float = 0.0


def _load_identity() -> str:
    """Read identity.yaml and format as instructions preamble."""
    if not IDENTITY_PATH.exists():
        return ""
    try:
        import yaml
        data = yaml.safe_load(IDENTITY_PATH.read_text(encoding="utf-8"))
        lines = [f"## Identity\n"]
        lines.append(f"You are **{data.get('name', 'AI Bot')}** — {data.get('description', '')}.")
        modes = data.get("modes", {})
        for mode_key, mode_name in modes.items():
            lines.append(f"- In {mode_key} mode (`business_mode: {mode_key}`): introduce yourself as **{mode_name}**")
        for rule in data.get("rules", []):
            lines.append(f"- {rule}")
        return "\n".join(lines) + "\n\n"
    except Exception as e:
        log.warning("Failed to load identity.yaml: %s", e)
        return ""


def _build_instructions() -> str:
    """Combine identity + channel-instructions into full instructions text."""
    identity = _load_identity()
    if INSTRUCTIONS_PATH.exists():
        base = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    else:
        base = _FALLBACK_INSTRUCTIONS
    return identity + base


def _refresh_instructions(server: Server) -> None:
    """Reload instructions if channel-instructions.md or identity.yaml changed."""
    global _instructions_mtime, _identity_mtime
    if not INSTRUCTIONS_PATH.exists():
        return
    inst_mtime = INSTRUCTIONS_PATH.stat().st_mtime
    id_mtime = IDENTITY_PATH.stat().st_mtime if IDENTITY_PATH.exists() else 0.0
    if inst_mtime != _instructions_mtime or id_mtime != _identity_mtime:
        server.instructions = _build_instructions()
        _instructions_mtime = inst_mtime
        _identity_mtime = id_mtime
        log.info("Instructions reloaded (identity=%s)", "yes" if id_mtime else "no")


def create_server() -> Server:
    global _instructions_mtime, _identity_mtime
    text = _build_instructions()
    if INSTRUCTIONS_PATH.exists():
        _instructions_mtime = INSTRUCTIONS_PATH.stat().st_mtime
    if IDENTITY_PATH.exists():
        _identity_mtime = IDENTITY_PATH.stat().st_mtime
    return Server("autoservice-channel", instructions=text)


def register_tools(server: Server, plugin_tools: list):
    """Register channel tools on the MCP server (legacy stdio mode).

    Uses channel_tools.py definitions but with callbacks that route
    through the module-level _channel_client WebSocket connection.
    """
    from channels.feishu.channel_tools import REPLY_TOOL, REACT_TOOL

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        core = [REPLY_TOOL, REACT_TOOL]
        dynamic = [
            Tool(name=pt.name, description=pt.description, inputSchema=pt.input_schema)
            for pt in plugin_tools
        ]
        return core + dynamic

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "reply":
            return _handle_reply(arguments)
        elif name == "react":
            return _handle_react(arguments)
        for pt in plugin_tools:
            if pt.name == name:
                result = pt.handler(**arguments)
                if asyncio.iscoroutine(result):
                    result = await result
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        raise ValueError(f"Unknown tool: {name}")


def _handle_reply(args: dict) -> list[TextContent]:
    chat_id = args["chat_id"]
    text = args["text"]
    if _channel_client and _channel_client.ws and _event_loop:
        asyncio.run_coroutine_threadsafe(
            _channel_client.send_reply(chat_id, text), _event_loop,
        )
        log.info(f"Reply to {chat_id}: {text[:50]}...")
        return [TextContent(type="text", text=f"Sent to {chat_id}")]
    return [TextContent(type="text", text="Error: not connected to channel-server")]


def _handle_react(args: dict) -> list[TextContent]:
    if _channel_client and _channel_client.ws and _event_loop:
        asyncio.run_coroutine_threadsafe(
            _channel_client.send_react(args["message_id"], args["emoji_type"]),
            _event_loop,
        )
        return [TextContent(type="text", text=f"Reacted {args['emoji_type']}")]
    return [TextContent(type="text", text="Error: not connected to channel-server")]


# -- Main ---------------------------------------------------------------------


async def main():
    global _channel_client, _event_loop
    _event_loop = asyncio.get_running_loop()

    from socialware.plugin_loader import discover
    plugins = discover("plugins")
    all_tools = []
    for p in plugins:
        all_tools.extend(p.tools)

    chat_id_str = os.environ.get("AUTOSERVICE_CHAT_ID", "*")
    chat_ids = [chat_id_str]
    server_port = os.environ.get("CHANNEL_SERVER_PORT", "9999")
    server_url = f"ws://localhost:{server_port}"

    _channel_client = ChannelClient(
        server_url=server_url,
        chat_ids=chat_ids,
        runtime_mode=os.environ.get("AUTOSERVICE_RUNTIME_MODE", "production"),
    )

    server = create_server()
    register_tools(server, all_tools)

    init_opts = InitializationOptions(
        server_name="autoservice-channel",
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={"claude/channel": {}},
        ),
    )

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        async def consume_messages():
            while True:
                msg = await _channel_client._message_queue.get()
                log.info(f"consume_messages: got msg type={msg.get('type')} chat_id={msg.get('chat_id')} source={msg.get('source')} text={msg.get('text','')[:40]}")
                try:
                    _refresh_instructions(server)
                    await inject_message(write_stream, msg)
                except Exception as e:
                    log.error(f"inject error: {e}")

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(server.run, read_stream, write_stream, init_opts)
                tg.start_soon(_channel_client.connect)
                tg.start_soon(consume_messages)
        except Exception as e:
            log.error(f"Task group error: {e}")


def entry_point():
    asyncio.run(main())


if __name__ == "__main__":
    entry_point()
