#!/usr/bin/env python3
"""
E2E test: /discuss command lifecycle via channel-server.

Starts channel-server (feishu_enabled=False), connects a wildcard instance,
and simulates the full /discuss lifecycle:
  1. /discuss "topic" → mode switch + message routed with runtime_mode=discuss
  2. Regular message in discuss mode → routed with runtime_mode=discuss
  3. /discuss status → routed with runtime_mode=discuss
  4. /discuss end → routed + mode restored
  5. Idle timeout → discuss_idle_reminder converted and sent
"""
import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import websockets

SERVER_PORT = 19991
PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


async def main():
    print("=== E2E: /discuss Command Lifecycle ===")
    print()

    from channels.feishu.channel_server import ChannelServer
    server = ChannelServer(
        port=SERVER_PORT,
        feishu_enabled=False,
        admin_chat_id="oc_admin_e2e",
    )
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.3)

    try:
        # Connect as wildcard instance (simulates channel.py)
        async with websockets.connect(f"ws://localhost:{SERVER_PORT}") as ws:
            await ws.send(json.dumps({
                "type": "register",
                "role": "developer",
                "chat_ids": ["*"],
                "instance_id": "e2e-discuss",
                "runtime_mode": "production",
            }))
            resp = json.loads(await ws.recv())
            assert resp["type"] == "registered", f"Registration failed: {resp}"
            ok("Registered wildcard instance")

            # --- Test 1: /discuss with no args → usage reply (no route) ---
            print()
            print("▶ Test 1: /discuss (no args) → usage text")
            server._reply_feishu = _capture_reply()
            admin_msg = {"chat_id": "oc_admin_e2e", "text": "/discuss"}
            await server._handle_admin_message(admin_msg)
            if server._reply_feishu._last_text and "/discuss" in server._reply_feishu._last_text:
                ok(f"Usage text returned: {server._reply_feishu._last_text[:50]}...")
            else:
                fail(f"Expected usage text, got: {server._reply_feishu._last_text}")

            # --- Test 2: /discuss "topic" → starts discussion ---
            print()
            print('▶ Test 2: /discuss "优化登录" → start discussion')
            server._reply_feishu = _capture_reply()
            admin_msg = {"chat_id": "oc_admin_e2e", "text": '/discuss "优化登录流程"'}
            await server._handle_admin_message(admin_msg)

            # Should receive the routed message
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("runtime_mode") == "discuss" and "优化登录流程" in msg.get("text", ""):
                ok(f"Routed with runtime_mode=discuss, text contains topic")
            else:
                fail(f"Wrong routing: runtime_mode={msg.get('runtime_mode')}, text={msg.get('text')}")

            # Mode should now be 'discuss'
            if server._chat_modes.get("oc_admin_e2e") == "discuss":
                ok("chat_mode switched to 'discuss'")
            else:
                fail(f"chat_mode is {server._chat_modes.get('oc_admin_e2e')}, expected 'discuss'")

            # Previous mode should be saved
            if server._discuss_prev_modes.get("oc_admin_e2e") == "production":
                ok("Previous mode 'production' saved")
            else:
                fail(f"prev_mode is {server._discuss_prev_modes.get('oc_admin_e2e')}")

            # --- Test 3: /discuss status → routes with discuss mode ---
            print()
            print("▶ Test 3: /discuss status → routes to skill")
            admin_msg = {"chat_id": "oc_admin_e2e", "text": "/discuss status"}
            await server._handle_admin_message(admin_msg)
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("runtime_mode") == "discuss" and msg.get("text") == "/discuss status":
                ok("Status message routed with runtime_mode=discuss")
            else:
                fail(f"Wrong status routing: {msg}")

            # --- Test 4: Regular message while in discuss mode ---
            print()
            print("▶ Test 4: Regular message in discuss mode uses discuss runtime_mode")
            # Verify the mode mapping is correct (what Feishu handler would use)
            current_mode = server._chat_modes.get("oc_admin_e2e", "production")
            if current_mode == "discuss":
                ok("Regular messages would get runtime_mode=discuss from _chat_modes")
            else:
                fail(f"Expected mode 'discuss', got '{current_mode}'")

            # --- Test 5: /discuss end → restores mode ---
            print()
            print("▶ Test 5: /discuss end → end + restore mode")
            # Add idle tracking to verify cleanup
            server._discuss_sessions["oc_admin_e2e"] = time.time()

            admin_msg = {"chat_id": "oc_admin_e2e", "text": "/discuss end"}
            await server._handle_admin_message(admin_msg)
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("text") == "/discuss end" and msg.get("runtime_mode") == "discuss":
                ok("End message routed with runtime_mode=discuss")
            else:
                fail(f"Wrong end routing: {msg}")

            if server._chat_modes.get("oc_admin_e2e") == "production":
                ok("Mode restored to 'production'")
            else:
                fail(f"Mode is {server._chat_modes.get('oc_admin_e2e')}, expected 'production'")

            if "oc_admin_e2e" not in server._discuss_prev_modes:
                ok("Previous mode mapping cleaned up")
            else:
                fail("Previous mode mapping not cleaned up")

            if "oc_admin_e2e" not in server._discuss_sessions:
                ok("Idle tracking cleaned up")
            else:
                fail("Idle tracking not cleaned up")

            # --- Test 6: /discuss with @file ---
            print()
            print("▶ Test 6: /discuss @docs/prd.md → includes file reference")
            server._reply_feishu = _capture_reply()
            admin_msg = {"chat_id": "oc_admin_e2e", "text": "/discuss @docs/prd.md"}
            await server._handle_admin_message(admin_msg)
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if "@docs/prd.md" in msg.get("text", "") and msg.get("runtime_mode") == "discuss":
                ok("File reference preserved in routed message")
            else:
                fail(f"File reference lost: {msg}")

            # Clean up from test 6
            server._discuss_prev_modes.pop("oc_admin_e2e", None)
            server._chat_modes["oc_admin_e2e"] = "production"

            # --- Test 7: Idle reminder delivery ---
            print()
            print("▶ Test 7: Idle reminder sent to instance")
            server._discuss_sessions["oc_idle_e2e"] = time.time() - 1000  # expired
            await server._check_discuss_idle()
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") == "discuss_idle_reminder" and msg.get("chat_id") == "oc_idle_e2e":
                ok(f"Idle reminder sent: type={msg['type']}, idle_minutes={msg.get('idle_minutes')}")
            else:
                fail(f"Expected discuss_idle_reminder, got: {msg}")

            # Clean up
            server._discuss_sessions.pop("oc_idle_e2e", None)

    finally:
        server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    print()
    print(f"=== Results: {PASS} passed, {FAIL} failed ===")
    return FAIL == 0


def _capture_reply():
    """Create an AsyncMock-like callable that captures the last reply."""
    async def mock_reply(chat_id, text):
        mock_reply._last_chat_id = chat_id
        mock_reply._last_text = text
    mock_reply._last_chat_id = None
    mock_reply._last_text = None
    return mock_reply


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
