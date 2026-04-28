"""Voice gateway — E2E-adapter ASR + TTS via Doubao realtime dialogue API.

Migrated from cc-openclaw/voice_gateway/ at commit 8632aa3 (feat/voice-doubao).
Kept the E2E-adapter pattern: each /asr or /tts WebSocket opens its own Doubao
realtime-dialogue connection and ignores unused event types. Creds come from
DOUBAO_APP_ID + DOUBAO_ACCESS_TOKEN env vars.
"""
