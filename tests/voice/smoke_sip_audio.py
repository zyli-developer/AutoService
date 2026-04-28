"""Local smoke test for /sip-audio.

Run:
  1. Start the gateway:  make run-gateway   (in another terminal)
  2. Run this script:    uv run python tests/voice/smoke_sip_audio.py

Verifies end-to-end:
  - /sip-audio endpoint accepts WebSocket connections
  - SipVoiceController boots ASR/TTS/CC clients without crashing
  - TTS path actually returns PCM bytes (greeting fires immediately)

Does NOT verify (would need real audio input):
  - ASR transcription
  - cc_pool reply path

This is a development utility, NOT part of the test suite (no pytest).
"""
import asyncio
import json
import sys

import websockets

URL = "ws://localhost:8000/sip-audio"
LISTEN_SECONDS = 10


async def main() -> int:
    print(f"[smoke] connecting to {URL}")
    try:
        ws = await websockets.connect(URL)
    except Exception as e:
        print(f"[smoke] connect failed: {e}")
        print("[smoke] is the gateway running? -> make run-gateway")
        return 2

    async with ws:
        print("[smoke] connected — sending start frame")
        await ws.send(json.dumps({
            "event": "start",
            "callSid": "smoke-test-001",
            "from": "+85299999999",
            "to": "+85288888888",
        }))

        print(f"[smoke] listening for up to {LISTEN_SECONDS}s")
        binary_bytes = 0
        chunk_count = 0
        text_msgs: list[str] = []
        deadline = asyncio.get_event_loop().time() + LISTEN_SECONDS

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                print("[smoke] listen window elapsed")
                break
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                print("[smoke] timeout waiting for next frame")
                break
            except websockets.ConnectionClosed as e:
                print(f"[smoke] server closed: {e}")
                break

            if isinstance(msg, bytes):
                chunk_count += 1
                binary_bytes += len(msg)
                if chunk_count <= 3 or chunk_count % 20 == 0:
                    print(f"[smoke]   binary #{chunk_count}: {len(msg)} bytes (total {binary_bytes})")
            else:
                print(f"[smoke]   text: {msg[:200]}")
                text_msgs.append(msg)

        print("[smoke] ----- summary -----")
        print(f"[smoke] binary chunks: {chunk_count}")
        print(f"[smoke] binary bytes:  {binary_bytes}")
        print(f"[smoke] text frames:   {len(text_msgs)}")
        if binary_bytes > 0:
            print("[smoke] PASS — TTS greeting PCM streamed back")
            return 0
        else:
            print("[smoke] FAIL — no PCM received")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
