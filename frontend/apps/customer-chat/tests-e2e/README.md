# customer-chat E2E — voice call TODO

This directory is reserved for browser-driven E2E tests of the voice-call
feature (test-plan-004, TC-022-002/003/004/005/009). **Nothing is wired
up yet** — these cases require live external services that cannot run
on the default CI path.

## Why not in CI

The voice pipeline needs:

- `voice.ezagent.chat` (Cloudflare Tunnel → cc-openclaw `voice-web` on port 13036)
- `voice_gateway` listening on port 8089 (cc-openclaw repo)
- `channel_server` listening on port 8765 (cc-openclaw repo) providing the Claude Code actor
- Valid 豆包 E2E credentials (`DOUBAO_APP_ID`, `DOUBAO_ACCESS_TOKEN`)
- A headed / fake-media browser instance

Running these against real services costs real money (豆包 is billed per
minute of audio) and has non-deterministic latency, so the group is
gated behind `RUN_VOICE_E2E=1`.

## TODO test cases (source: test-plan-004)

| TC-ID | Scenario | Dependencies |
|---|---|---|
| TC-022-002 | Browser prompts for microphone permission | voice-web reachable |
| TC-022-003 | Greeting TTS audible within 3s of permission grant | voice_gateway + 豆包 |
| TC-022-004 | ASR → LLM → TTS P50 latency ≤ 3s | voice_gateway + channel_server + 豆包 |
| TC-022-005 | User speech interrupts bot TTS within 500ms | full stack |
| TC-022-009 | channel_server offline → user-visible fallback copy within 60s | voice_gateway alone; channel_server intentionally down; **requires cc-openclaw-side PR for fallback copy** |

## Prerequisites to activate

1. **Pick a driver**. Options:
   - **Playwright** — install `@playwright/test` + `pnpm add -D playwright` in this app, write `.spec.ts` files here. Best for mic permission (`--use-fake-ui-for-media-stream`).
   - **Bash + `agent-browser` CLI** — match the pattern used in root `tests/e2e/test_web_chat.sh`. Lower setup, but mic/audio harder to drive.
2. **Complete the eval-doc-022 §8 preflight check** to confirm the path
   `voice.ezagent.chat/ws → :8089` is routed correctly through Cloudflare
   Tunnel. Until this passes manually, no E2E code can work.
3. **Capture a stable credential rotation plan** — production 豆包 keys
   should not live in CI. Use a dedicated test tenant with a daily quota cap.

## Running (once wired)

```bash
# Enable
export RUN_VOICE_E2E=1

# Or inline
RUN_VOICE_E2E=1 pnpm --filter customer-chat test:e2e
```

Leave `RUN_VOICE_E2E` unset and the suite is skipped.

## Related

- test-plan: `.artifacts/test-plans/test-plan-voice-call-fab.md`
- eval-doc: `.artifacts/eval-docs/eval-voice-call-fab.md` (§8 preflight)
- GitHub issue: https://github.com/ezagent42/AutoService/issues/79
