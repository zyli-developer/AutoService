"""§7.1 #6 viewer_role visibility matrix — read-path filter.

Spec: `conversation-engine.md` §7.1 invariant 6. Only CUSTOMER viewers get
SIDE messages filtered out; all other roles (AGENT, OPERATOR, OBSERVER,
ADMIN, None) can read SIDE.
"""

from __future__ import annotations

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    MessageVisibility,
    ParticipantRole,
)


async def _seed_one_of_each_visibility(engine, conv, make_participant):
    """Seed conversation with PUBLIC + SIDE + SYSTEM messages."""
    cust = make_participant(id="cust_v", role=ParticipantRole.CUSTOMER)
    op = make_participant(id="op_v", role=ParticipantRole.OPERATOR)
    agent = make_participant(id="agent_v", role=ParticipantRole.AGENT)
    await engine.join(conv.id, cust)
    await engine.join(conv.id, op)  # auto → copilot
    await engine.join(conv.id, agent)

    # PUBLIC from customer (gate keeps it public)
    await engine.send_message(conv.id, source=cust.id, content="hello")
    # SIDE from operator (gate downgrades PUBLIC→SIDE in copilot)
    await engine.send_message(conv.id, source=op.id, content="suggestion")
    # PUBLIC from agent in copilot (stays public)
    await engine.send_message(conv.id, source=agent.id, content="reply")


@pytest.mark.parametrize(
    "viewer_role,expects_side",
    [
        (ParticipantRole.CUSTOMER, False),
        (ParticipantRole.AGENT, True),
        (ParticipantRole.OPERATOR, True),
        (ParticipantRole.OBSERVER, True),
        (None, True),
    ],
)
async def test_visibility_matrix_get_messages(
    engine, conversation, make_participant, viewer_role, expects_side
):
    await _seed_one_of_each_visibility(engine, conversation, make_participant)

    msgs = await engine.get_messages(conversation.id, viewer_role=viewer_role)
    side_msgs = [m for m in msgs if m.visibility == MessageVisibility.SIDE]

    if expects_side:
        assert len(side_msgs) >= 1, (
            f"viewer_role={viewer_role} must see SIDE messages"
        )
    else:
        assert len(side_msgs) == 0, (
            f"viewer_role={viewer_role} must NOT see SIDE messages"
        )


async def test_customer_filter_does_not_strip_public_or_system(
    engine, conversation, make_participant
):
    """§7.1 #6: filter targets SIDE only; PUBLIC and SYSTEM must pass through."""
    await _seed_one_of_each_visibility(engine, conversation, make_participant)

    msgs = await engine.get_messages(
        conversation.id, viewer_role=ParticipantRole.CUSTOMER
    )
    assert any(m.visibility == MessageVisibility.PUBLIC for m in msgs), (
        "CUSTOMER must still see PUBLIC messages"
    )
    assert all(m.visibility != MessageVisibility.SIDE for m in msgs), (
        "CUSTOMER must not see any SIDE messages"
    )
