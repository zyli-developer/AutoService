#!/usr/bin/env python3
"""
CLI chat tester — talk to CC Pool without Feishu/Web.

Supports streaming output (typewriter effect) when
`cc_pool.include_partial_messages: true` is set in config.local.yaml.

Usage:
    .venv/Scripts/python.exe scripts/chat_cli.py
    .venv/Scripts/python.exe scripts/chat_cli.py --chat-id oc_test_001
    .venv/Scripts/python.exe scripts/chat_cli.py --no-stream   # disable stream display
"""

import argparse
import asyncio
import sys
import time
import uuid
import warnings
from pathlib import Path

# Suppress Python 3.14 + Windows Proactor subprocess GC noise (harmless ResourceWarnings
# that appear as "Exception ignored while calling deallocator ..." during warmup).
warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channels.feishu.channel_server import _extract_partial_text  # noqa: E402


async def chat_loop(chat_id: str, stream_display: bool):
    from autoservice.cc_pool import get_pool, load_pool_config, shutdown_pool

    config = load_pool_config()
    print(f"[cli] Loading CC Pool (min={config.min_size}, max={config.max_size}, "
          f"stream={config.include_partial_messages}) ...")
    pool = await get_pool(config)
    print(f"[cli] Pool ready. chat_id={chat_id}")
    print(f"[cli] Type messages and press Enter. Ctrl+C to exit.\n")

    try:
        while True:
            try:
                text = input("You> ").strip()
            except EOFError:
                break
            if not text:
                continue

            prompt = (
                f"<channel chat_id={chat_id} user=cli_tester source=cli>\n"
                f"{text}\n"
                f"</channel>"
            )

            start = time.monotonic()
            first_byte_at = None
            stream_state = {
                "current_index": None,
                "buffer": "",
                "last_printed": "",
                "active": False,  # have we printed "Bot> " prefix yet
            }

            print()  # spacer
            async for msg in pool.session_query(chat_id, prompt):
                cls = type(msg).__name__

                if cls == "StreamEvent" and stream_display:
                    if first_byte_at is None:
                        first_byte_at = time.monotonic() - start
                    _handle_stream_event_cli(msg, stream_state)
                    continue

                # Fallback / non-stream messages
                if cls == "AssistantMessage" and not stream_display:
                    # Only print in non-stream mode to avoid duplicate with streaming
                    for block in getattr(msg, "content", []):
                        bcls = type(block).__name__
                        if bcls == "ToolUseBlock" and (block.name or "").endswith("reply"):
                            inp = block.input or {}
                            if "text" in inp:
                                print(f"Bot> {inp['text']}")
                        elif bcls == "TextBlock":
                            print(f"Bot> {block.text}")
                    continue

                if cls == "ResultMessage":
                    if stream_state["active"]:
                        print()  # newline after streamed text
                        stream_state["active"] = False
                    duration = (time.monotonic() - start)
                    fb = f"{first_byte_at:.1f}s" if first_byte_at else "n/a"
                    turns = getattr(msg, "num_turns", 0) or 0
                    cost = getattr(msg, "total_cost_usd", 0) or 0
                    print(f"  [done] first_byte={fb}, total={duration:.1f}s, "
                          f"turns={turns}, ${cost:.4f}")
                    continue

            if stream_state["active"]:
                print()
            print()

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[cli] Exiting...")
    finally:
        await shutdown_pool()
        print("[cli] Pool shut down.")


def _handle_stream_event_cli(msg, state: dict) -> None:
    """Print partial text as it streams (typewriter effect)."""
    event = getattr(msg, "event", None) or {}
    etype = event.get("type")

    if etype == "content_block_start":
        block = event.get("content_block", {}) or {}
        index = event.get("index")
        btype = block.get("type")
        bname = block.get("name") or ""

        if btype == "tool_use" and bname.endswith("reply"):
            state["current_index"] = index
            state["buffer"] = ""
            state["last_printed"] = ""
            if not state["active"]:
                print("Bot> ", end="", flush=True)
                state["active"] = True
        elif btype == "text":
            # Free-form text (rare — model usually uses reply tool)
            state["current_index"] = index
            state["buffer"] = "__text_block__"
            state["last_printed"] = ""
            if not state["active"]:
                print("Bot> ", end="", flush=True)
                state["active"] = True
        elif btype == "thinking":
            # Show a compact thinking indicator
            print("  [thinking...]", end="", flush=True)
        return

    if etype == "content_block_delta":
        if state["current_index"] is None or event.get("index") != state["current_index"]:
            return
        delta = event.get("delta", {}) or {}
        dtype = delta.get("type")

        if dtype == "input_json_delta":
            state["buffer"] += delta.get("partial_json") or ""
            text = _extract_partial_text(state["buffer"])
            if text is None:
                return
            if text != state["last_printed"] and text.startswith(state["last_printed"]):
                # Print only the new suffix
                suffix = text[len(state["last_printed"]):]
                print(suffix, end="", flush=True)
                state["last_printed"] = text
        elif dtype == "text_delta":
            chunk = delta.get("text") or ""
            print(chunk, end="", flush=True)
            state["last_printed"] += chunk
        return

    if etype == "content_block_stop":
        if state["current_index"] is not None and event.get("index") == state["current_index"]:
            state["current_index"] = None
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", default=f"cli_{uuid.uuid4().hex[:12]}",
                        help="chat_id for sticky session (default: random)")
    parser.add_argument("--no-stream", action="store_true",
                        help="Disable streaming display (fall back to final-message only)")
    args = parser.parse_args()

    try:
        asyncio.run(chat_loop(args.chat_id, stream_display=not args.no_stream))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
