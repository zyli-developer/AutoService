"""§3 Messages + get_messages (Q9, DevB #1) + ValidationError cases."""

import pytest

from autoservice.conversation_engine import (
    MessageVisibility,
    ParticipantRole,
    ValidationError,
)


async def _customer(engine, conv, make_participant):
    p = make_participant(id="cust_1", role=ParticipantRole.CUSTOMER)
    await engine.join(conv.id, p)
    return p


async def _operator(engine, conv, make_participant):
    p = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conv.id, p)
    return p


async def test_send_message_returns_message(engine, conversation, make_participant):
    cust = await _customer(engine, conversation, make_participant)
    m = await engine.send_message(
        conversation.id, source=cust.id, content="hello"
    )
    assert m.content == "hello"
    assert m.visibility == MessageVisibility.PUBLIC
    assert m.sequence_number >= 1


async def test_send_message_sequence_monotonic_per_conv(
    engine, conversation, make_participant
):
    """Q3 / §7.1 #4: sequence_number is per-conversation monotonic."""
    cust = await _customer(engine, conversation, make_participant)
    m1 = await engine.send_message(conversation.id, source=cust.id, content="a")
    m2 = await engine.send_message(conversation.id, source=cust.id, content="b")
    m3 = await engine.send_message(conversation.id, source=cust.id, content="c")
    assert m1.sequence_number < m2.sequence_number < m3.sequence_number


@pytest.mark.parametrize("content", ["", "   "])
async def test_send_empty_content_raises(
    engine, conversation, make_participant, content
):
    cust = await _customer(engine, conversation, make_participant)
    with pytest.raises(ValidationError):
        await engine.send_message(conversation.id, source=cust.id, content=content)


async def test_edit_message_creates_edit_link(engine, conversation, make_participant):
    """US-2.2 placeholder→backfill."""
    cust = await _customer(engine, conversation, make_participant)
    original = await engine.send_message(
        conversation.id, source=cust.id, content="loading…"
    )
    edited = await engine.edit_message(
        conversation.id,
        original.id,
        new_content="final answer",
        edited_by=cust.id,
    )
    assert edited.content == "final answer"
    assert edited.edit_of == original.id


async def test_get_messages_returns_chronological(
    engine, conversation, make_participant
):
    cust = await _customer(engine, conversation, make_participant)
    for i in range(3):
        await engine.send_message(conversation.id, source=cust.id, content=f"m{i}")
    msgs = await engine.get_messages(conversation.id)
    seqs = [m.sequence_number for m in msgs]
    assert seqs == sorted(seqs)


async def test_get_messages_since_sequence_excludes_prior(
    engine, conversation, make_participant
):
    cust = await _customer(engine, conversation, make_participant)
    m1 = await engine.send_message(conversation.id, source=cust.id, content="a")
    m2 = await engine.send_message(conversation.id, source=cust.id, content="b")
    later = await engine.get_messages(conversation.id, since_sequence=m1.sequence_number)
    ids = {m.id for m in later}
    assert m2.id in ids
    assert m1.id not in ids


async def test_get_messages_before_sequence_devb_1(
    engine, conversation, make_participant
):
    """DevB #1: before_sequence for scroll-up."""
    cust = await _customer(engine, conversation, make_participant)
    msgs = []
    for i in range(5):
        msgs.append(
            await engine.send_message(conversation.id, source=cust.id, content=f"m{i}")
        )
    older = await engine.get_messages(
        conversation.id, before_sequence=msgs[3].sequence_number
    )
    ids = {m.id for m in older}
    assert msgs[0].id in ids
    assert msgs[3].id not in ids
    assert msgs[4].id not in ids


async def test_get_messages_since_and_before_are_exclusive(
    engine, conversation, make_participant
):
    """DevB #1: since_sequence and before_sequence mutually exclusive."""
    await _customer(engine, conversation, make_participant)
    with pytest.raises(ValidationError):
        await engine.get_messages(
            conversation.id, since_sequence=1, before_sequence=10
        )


async def test_get_messages_viewer_role_filters_side_q9(
    engine, conversation, make_participant
):
    """Q9: Engine filters SIDE when viewer_role=CUSTOMER."""
    cust = await _customer(engine, conversation, make_participant)
    op = await _operator(engine, conversation, make_participant)
    await engine.send_message(conversation.id, source=cust.id, content="public")
    await engine.send_message(
        conversation.id,
        source=op.id,
        content="side note",
        requested_visibility=MessageVisibility.SIDE,
    )

    as_customer = await engine.get_messages(
        conversation.id, viewer_role=ParticipantRole.CUSTOMER
    )
    assert all(m.visibility == MessageVisibility.PUBLIC for m in as_customer)

    as_operator = await engine.get_messages(
        conversation.id, viewer_role=ParticipantRole.OPERATOR
    )
    vis = {m.visibility for m in as_operator}
    assert MessageVisibility.PUBLIC in vis
    assert MessageVisibility.SIDE in vis
