from datetime import datetime, timezone
from autoservice.conversation_engine.types import (
    Conversation, ConversationMode, ConversationState,
)


def test_conversation_has_takeover_operator_id_field_defaulting_to_none():
    now = datetime.now(timezone.utc)
    conv = Conversation(
        id="web_x",
        state=ConversationState.CREATED,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
    )
    assert conv.takeover_operator_id is None


def test_conversation_takeover_operator_id_can_be_set():
    now = datetime.now(timezone.utc)
    conv = Conversation(
        id="web_x",
        state=ConversationState.CREATED,
        mode=ConversationMode.TAKEOVER,
        participants=(),
        created_at=now,
        updated_at=now,
        takeover_operator_id="op-42",
    )
    assert conv.takeover_operator_id == "op-42"
