"""T5S.14 / T3B.5 — unit tests for CCClient.call_with_tools.

Spec: docs/plans/m3.5-mini-sprint.md §1.4 "cc_pool tool-use surface".
Red-line: CON-06 (dream pool isolation) + critical user directive that the
LLM transport is ``claude_agent_sdk`` local SDK, NOT the ``anthropic`` cloud
SDK.  These tests assert:

1. A Dream-role acquired client gains ``call_with_tools`` that returns a
   Message-shape response the existing dream_agent loop already consumes.
2. Tool-use blocks from the SDK's ``AssistantMessage`` are translated into
   Anthropic-shape ``{"type": "tool_use", "id", "name", "input"}`` dicts.
3. A second call with the tool_result appended continues the conversation
   (the wrapper speaks JSON-in / JSON-out — no bash subprocess delegation).
4. Non-dream clients (customer / operator / triage) raise on call, so the
   surface is strictly dream-scoped.
5. Tool definitions are passed through verbatim — they are the caller's
   schemas (emit_proposal / kb_search / list_souls), not mutated here.

All LLM traffic is mocked — zero network, zero real CLI subprocesses.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from autoservice import cc_pool as cc_pool_mod
from autoservice.cc_pool import CCClient


# ---------------------------------------------------------------------------
# SDK fakes — enough to exercise the wrapper's tool-use translation loop
# ---------------------------------------------------------------------------


class _FakeToolUseBlock:
    """Duck-types claude_agent_sdk.types.ToolUseBlock."""

    def __init__(self, id: str, name: str, input: dict):  # noqa: A002
        self.id = id
        self.name = name
        self.input = input


class _FakeTextBlock:
    """Duck-types claude_agent_sdk.types.TextBlock."""

    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    """Duck-types claude_agent_sdk.types.AssistantMessage.

    The wrapper under test checks isinstance against the real SDK classes,
    so we patch those classes at the cc_pool module level in each test.
    """

    def __init__(
        self,
        content: list,
        *,
        stop_reason: str | None = None,
        usage: dict | None = None,
        model: str = "claude-fake",
    ):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage
        self.model = model


class _FakeResultMessage:
    """Duck-types claude_agent_sdk.types.ResultMessage (terminates the
    receive_response iterator)."""

    def __init__(self, stop_reason: str | None = "end_turn", usage: dict | None = None):
        self.stop_reason = stop_reason
        self.usage = usage
        self.subtype = "success"
        self.is_error = False


class _FakeStream:
    """Async-iterator that yields pre-scripted SDK messages for one
    ``receive_response()`` call, then terminates."""

    def __init__(self, items: list):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class _FakeSDKClient:
    """Minimal ClaudeSDKClient stand-in — captures query() prompts and
    plays back scripted responses for each invocation."""

    def __init__(self, scripts: list[list[Any]]):
        self._scripts = list(scripts)
        self.connected = False
        self.disconnected = False
        self.prompts: list[str] = []

        class _Proc:
            returncode = None

        class _Transport:
            _process = _Proc()

        self._transport = _Transport()

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def query(self, prompt, **kwargs):
        self.prompts.append(prompt if isinstance(prompt, str) else repr(prompt))

    async def set_model(self, model):  # pragma: no cover — unused here
        return None

    def receive_response(self):
        if not self._scripts:
            raise AssertionError(
                "receive_response called more times than responses scripted",
            )
        return _FakeStream(self._scripts.pop(0))


def _patch_sdk_types(monkeypatch) -> None:
    """Patch the SDK type handles the wrapper uses for isinstance checks."""
    monkeypatch.setattr(cc_pool_mod, "AssistantMessage", _FakeAssistantMessage, raising=False)
    monkeypatch.setattr(cc_pool_mod, "ToolUseBlock", _FakeToolUseBlock, raising=False)
    monkeypatch.setattr(cc_pool_mod, "TextBlock", _FakeTextBlock, raising=False)
    monkeypatch.setattr(cc_pool_mod, "ResultMessage", _FakeResultMessage, raising=False)


def _dream_client(sdk: _FakeSDKClient) -> CCClient:
    """Build a CCClient and flag it as dream-role (the surface gate)."""
    client = CCClient(sdk)
    client._dream_role = True  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_single_tool_use_round_returns_message(monkeypatch):
    """Happy path: one tool_use round returns an Anthropic-shape Message.

    The fake SDK yields a single AssistantMessage whose content has one
    ToolUseBlock.  ``call_with_tools`` must translate that into a dict
    where ``content[0]["type"] == "tool_use"`` so the existing
    :func:`dream_agent._extract_tool_uses` loop consumes it unchanged.
    """
    _patch_sdk_types(monkeypatch)
    sdk = _FakeSDKClient([
        [
            _FakeAssistantMessage(
                content=[
                    _FakeToolUseBlock(
                        id="tu_1", name="emit_proposal",
                        input={"title": "hello", "risk_level": "low"},
                    ),
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 17, "output_tokens": 3},
            ),
            _FakeResultMessage(stop_reason="tool_use"),
        ],
    ])
    client = _dream_client(sdk)

    resp = asyncio.run(client.call_with_tools(
        system="dream soul",
        messages=[{"role": "user", "content": "observe + propose"}],
        tools=[{"name": "emit_proposal", "input_schema": {}}],
    ))

    # Anthropic-shape response dict the existing dream_agent loop expects.
    blocks = resp["content"] if isinstance(resp, dict) else resp.content  # noqa: B012
    assert len(blocks) == 1
    b = blocks[0]
    btype = b["type"] if isinstance(b, dict) else getattr(b, "type", None)
    assert btype == "tool_use"
    bname = b["name"] if isinstance(b, dict) else b.name
    assert bname == "emit_proposal"
    binput = b["input"] if isinstance(b, dict) else b.input
    assert binput == {"title": "hello", "risk_level": "low"}

    stop = resp["stop_reason"] if isinstance(resp, dict) else resp.stop_reason
    assert stop == "tool_use"


def test_two_round_tool_loop_feeds_tool_results(monkeypatch):
    """The wrapper must support a multi-round tool loop.

    Round 1: SDK emits a tool_use.  Caller executes it, appends a
    ``tool_result`` to ``messages``, and calls again.  Round 2: SDK emits
    a final text response.  The wrapper must have issued TWO SDK queries
    and returned the final text block shape on round 2.
    """
    _patch_sdk_types(monkeypatch)
    sdk = _FakeSDKClient([
        # Round 1 — tool_use
        [
            _FakeAssistantMessage(
                content=[_FakeToolUseBlock(id="tu_a", name="kb_search",
                                          input={"query": "pricing"})],
                stop_reason="tool_use",
                usage={"input_tokens": 10, "output_tokens": 4},
            ),
            _FakeResultMessage(stop_reason="tool_use"),
        ],
        # Round 2 — final text
        [
            _FakeAssistantMessage(
                content=[_FakeTextBlock("done observing")],
                stop_reason="end_turn",
                usage={"input_tokens": 12, "output_tokens": 5},
            ),
            _FakeResultMessage(stop_reason="end_turn"),
        ],
    ])
    client = _dream_client(sdk)

    async def drive():
        msgs = [{"role": "user", "content": "start"}]
        r1 = await client.call_with_tools(system="s", messages=msgs, tools=[])
        # Simulate the dream_agent loop: append assistant turn + tool_result.
        msgs.append({"role": "assistant", "content": r1["content"]})
        msgs.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "tu_a",
                "content": "[]",
            }],
        })
        r2 = await client.call_with_tools(system="s", messages=msgs, tools=[])
        return r1, r2

    r1, r2 = asyncio.run(drive())

    # Two rounds, two SDK queries.
    assert len(sdk.prompts) == 2
    # Round 1's response had a tool_use block.
    assert any(
        (b["type"] if isinstance(b, dict) else getattr(b, "type", None)) == "tool_use"
        for b in (r1["content"] if isinstance(r1, dict) else r1.content)
    )
    # Round 2's response is a text block / end_turn.
    stop2 = r2["stop_reason"] if isinstance(r2, dict) else r2.stop_reason
    assert stop2 == "end_turn"
    blocks2 = r2["content"] if isinstance(r2, dict) else r2.content
    assert any(
        (b["type"] if isinstance(b, dict) else getattr(b, "type", None)) == "text"
        for b in blocks2
    )


def test_non_dream_client_rejects_call_with_tools(monkeypatch):
    """Customer / operator / triage clients MUST NOT expose call_with_tools.

    The scoping gate is the ``_dream_role=True`` flag.  A default CCClient
    must raise ``RuntimeError`` mentioning the dream-role constraint so
    accidental misuse is loud.
    """
    _patch_sdk_types(monkeypatch)
    sdk = _FakeSDKClient([])
    client = CCClient(sdk)  # no _dream_role flag
    # customer clients would be created with enable_kb_tool=True etc.;
    # verify the default path refuses call_with_tools.

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(client.call_with_tools(
            system="s", messages=[], tools=[],
        ))
    assert "dream" in str(excinfo.value).lower()


def test_tools_argument_relayed_to_caller_context(monkeypatch):
    """Tool definitions come from the caller and must not be mutated.

    The wrapper serialises them into the prompt preamble as JSON (so the
    CLI-backed model sees them), but the ORIGINAL ``tools`` list the
    caller passed must be unchanged — no in-place append, no type swap.
    """
    _patch_sdk_types(monkeypatch)
    sdk = _FakeSDKClient([
        [
            _FakeAssistantMessage(
                content=[_FakeTextBlock("nothing to propose")],
                stop_reason="end_turn",
                usage={"input_tokens": 5, "output_tokens": 2},
            ),
            _FakeResultMessage(stop_reason="end_turn"),
        ],
    ])
    client = _dream_client(sdk)

    tools_arg = [
        {"name": "emit_proposal", "input_schema": {"type": "object"}},
        {"name": "kb_search", "input_schema": {"type": "object"}},
    ]
    original = [dict(t) for t in tools_arg]

    asyncio.run(client.call_with_tools(
        system="dream soul",
        messages=[{"role": "user", "content": "begin"}],
        tools=tools_arg,
    ))

    # Caller's list is unchanged byte-for-byte.
    assert tools_arg == original
    # And the prompt the SDK saw mentions the tool names so the LLM can
    # emit them (the wrapper embeds tool schemas in the prompt since the
    # CLI SDK doesn't accept Anthropic-shape tool JSON natively).
    joined_prompt = " ".join(sdk.prompts)
    assert "emit_proposal" in joined_prompt
    assert "kb_search" in joined_prompt
