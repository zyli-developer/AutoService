"""SIP-path client to AutoService cc_pool.

Naming follows docs/sip-deploy/08-minimal-cinnox-integration-code.md §1.2,
but the implementation deliberately diverges from 08:

08 spec: connect to ws://127.0.0.1:8000/ws/chat over WebSocket and
exchange JSON frames. That doesn't work in this codebase — /ws/chat
lives in channels/web/app.py (M1 legacy), NOT in autoservice.web_gateway
where /sip-audio is mounted. `make run-gateway` only exposes web_gateway.

This implementation: in-process call to autoservice.cc_pool.session_query()
directly. No JSON marshalling, no socket roundtrip, no auth puzzle —
the SIP controller and cc_pool live in the same uvicorn process.

session_query() with chat_id=call_sid sticky-binds one Claude Code
instance to the call's lifetime; close() releases it on hangup.

Reply text is built by concatenating TextBlock.text from each
AssistantMessage.content yielded by session_query. ToolUseBlock and
other non-text content blocks are silently dropped — the SIP path
speaks text only.

When /ws/chat is migrated into web_gateway in a future PR, this module
can be flipped to the WS-based 08 spec without touching SipVoiceController.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CCChatClient:
    def __init__(
        self,
        *,
        call_sid: str,
        caller: str,
        tenant_id: str | None = None,
        pool: Any = None,
    ):
        self.call_sid = call_sid
        self.caller = caller
        self.tenant_id = tenant_id
        self._pool = pool

    async def connect(self) -> None:
        """Lazy-init the pool unless one was injected (tests inject)."""
        if self._pool is None:
            from autoservice.cc_pool import get_pool
            self._pool = await get_pool()

    async def send(self, user_text: str) -> str:
        """Run one turn through cc_pool, return the assembled text reply."""
        if self._pool is None:
            raise RuntimeError("CCChatClient.connect() not called")

        chunks: list[str] = []
        async for msg in self._pool.session_query(
            chat_id=self.call_sid,
            prompt=user_text,
            tenant_id=self.tenant_id,
            tier="fast",
        ):
            content = getattr(msg, "content", None)
            if not content:
                continue
            for block in content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)

    async def close(self) -> None:
        """Release the sticky binding; safe to call before connect()."""
        if self._pool is None:
            return
        try:
            await self._pool.end_session(self.call_sid)
        except Exception:
            log.warning("[%s] end_session failed", self.call_sid, exc_info=True)
