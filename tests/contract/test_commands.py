"""§6.1 handle_command permission matrix + command → side-effect wiring."""

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    ConversationState,
    ParticipantRole,
    PermissionDenied,
)


async def _actor(engine, conv, make_participant, role: ParticipantRole, id: str):
    p = make_participant(id=id, role=role)
    await engine.join(conv.id, p)
    return p


# §6.1 table — ❌ rows (must raise PermissionDenied)
DENIED_CASES = [
    (ParticipantRole.CUSTOMER, "/hijack"),
    (ParticipantRole.CUSTOMER, "/release"),
    (ParticipantRole.CUSTOMER, "/resolve"),
    (ParticipantRole.AGENT, "/hijack"),
    (ParticipantRole.AGENT, "/resolve"),
]

ALLOWED_OPERATOR_CMDS = ["/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status"]


@pytest.mark.parametrize("role,command", DENIED_CASES)
async def test_permission_denied_for_disallowed_roles(
    engine, conversation, make_participant, role, command
):
    actor = await _actor(engine, conversation, make_participant, role, f"{role.value}_x")
    # Ensure there's at least one operator so mode state is valid for /release etc.
    await _actor(engine, conversation, make_participant, ParticipantRole.OPERATOR, "op_bg")
    with pytest.raises(PermissionDenied):
        await engine.handle_command(
            conversation.id, actor_id=actor.id, command=command
        )


async def test_hijack_switches_to_takeover(engine, conversation, make_participant):
    op = await _actor(engine, conversation, make_participant, ParticipantRole.OPERATOR, "op_1")
    await engine.handle_command(conversation.id, actor_id=op.id, command="/hijack")
    c = await engine.get_conversation(conversation.id)
    assert c.mode == ConversationMode.TAKEOVER


async def test_release_returns_to_auto(engine, conversation, make_participant):
    op = await _actor(engine, conversation, make_participant, ParticipantRole.OPERATOR, "op_1")
    await engine.handle_command(conversation.id, actor_id=op.id, command="/hijack")
    await engine.handle_command(conversation.id, actor_id=op.id, command="/release")
    c = await engine.get_conversation(conversation.id)
    assert c.mode == ConversationMode.AUTO


async def test_resolve_closes_conversation(engine, conversation, make_participant):
    op = await _actor(engine, conversation, make_participant, ParticipantRole.OPERATOR, "op_1")
    await engine.handle_command(conversation.id, actor_id=op.id, command="/resolve")
    c = await engine.get_conversation(conversation.id)
    assert c.state == ConversationState.CLOSED
    assert c.resolution is not None
    assert c.resolution.outcome.value == "resolved"


async def test_abandon_closes_conversation(engine, conversation, make_participant):
    op = await _actor(engine, conversation, make_participant, ParticipantRole.OPERATOR, "op_1")
    await engine.handle_command(conversation.id, actor_id=op.id, command="/abandon")
    c = await engine.get_conversation(conversation.id)
    assert c.state == ConversationState.CLOSED
    assert c.resolution.outcome.value == "abandoned"
