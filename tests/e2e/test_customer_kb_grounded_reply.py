"""E2E: customer CC instance reply for mystore tenant must cite KB content.

This is the acceptance test for the tenant-soul + KB feature. It requires
a real Claude Agent SDK subprocess and the mystore tenant seeded via
scripts/seed_mystore_tenant.py. Marked @pytest.mark.slow - not part of
the default test run.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Participant,
    ParticipantRole,
)

pytestmark = pytest.mark.slow


# The prompt hardcodes "DID" in its <kb_context> block, so the regex must
# NOT include it — otherwise a reply that merely echoes the prompt would
# pass without proving the tenant soul or KB MCP tool actually loaded.
# These remaining terms only appear in the seeded mystore KB / customer soul.
_KB_KEYWORDS = re.compile(
    r"(CINNOX|IVR|PSTN|套餐|Essentials|Professional|Enterprise)",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def mystore_seeded():
    """Ensure the mystore tenant sandbox + KB are in place.

    Skips the test if the seed inputs are missing (e.g., running outside
    the full dev setup).
    """
    sandbox = Path(".autoservice/sandbox/mystore")
    kb_db = Path(".autoservice/database/knowledge_base/kb.db")
    if not sandbox.exists() or not kb_db.exists():
        pytest.skip(
            "mystore tenant not seeded - run scripts/seed_mystore_tenant.py "
            "before this test.",
        )


@pytest.mark.asyncio
async def test_mystore_services_question_cites_kb(mystore_seeded):
    """Full-stack: 'What services do you offer?' to mystore must cite KB.

    Uses CCPool.session_query with tenant_id='mystore' so the sticky
    instance is bound to the mystore customer soul + KB MCP tool. The
    prompt pre-includes a small <kb_context> snippet to prime the reply,
    mirroring what _generate_agent_reply assembles in production.
    """
    from autoservice.cc_pool import get_pool

    engine = LocalEngine()
    conv = await engine.create_conversation(
        channel="web", external_id="cust-test", metadata={"channel": "web"},
    )
    now = datetime.now(timezone.utc)
    await engine.join(
        conv.id,
        Participant(id="cust-test", role=ParticipantRole.CUSTOMER, joined_at=now),
    )
    await engine.join(
        conv.id,
        Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now),
    )

    pool = await get_pool()

    prompt = (
        "<kb_context>\n"
        "[1] glossary · DID\n"
        "DID 是 Direct Inward Dialling\n"
        "</kb_context>\n\n"
        "Customer message: 你们提供哪些服务\n\n"
        "基于 <kb_context> 回答。语言跟随客户。"
    )

    reply_text = ""
    from claude_agent_sdk.types import AssistantMessage, ResultMessage
    async for msg in pool.session_query(conv.id, prompt, tenant_id="mystore"):
        if isinstance(msg, AssistantMessage) and msg.content:
            for block in msg.content:
                if hasattr(block, "text"):
                    reply_text += block.text
        elif isinstance(msg, ResultMessage) and msg.result:
            reply_text = msg.result

    assert reply_text, "expected non-empty agent reply"
    assert _KB_KEYWORDS.search(reply_text), (
        f"reply must cite KB keywords (CINNOX/DID/IVR/PSTN/套餐/...) "
        f"but got: {reply_text!r}"
    )

    await pool.end_session(conv.id)
