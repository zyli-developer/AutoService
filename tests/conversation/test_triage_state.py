"""Triage state on Conversation.metadata + TRIAGE participant role.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §3
"""
from __future__ import annotations

import pytest

from autoservice.conversation_engine.types import ParticipantRole


def test_triage_role_exists():
    assert ParticipantRole.TRIAGE.value == "triage"
