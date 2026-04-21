"""Handoff protocol parser — ``<handoff to="X" reason="..." />`` (M3 T3S.1).

Contract: docs/contracts/m3/e3-triage.md §2.
Mirrors :mod:`autoservice.sentiment` shape exactly — same
``(result, cleaned_output)`` return contract for composition with
the existing output-processing pipeline.

Role whitelist: matches ``AgentRole`` set from :mod:`soul_generator`.
Malformed tags (missing closing, unknown role, nested, injection
attempts) return ``(None, original_output)`` — fail-closed, no raise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# AgentRole enum values — kept in sync with soul_generator.AGENT_ROLES.
# Do NOT add "_master" (platform-scope, not a conversation role).
VALID_HANDOFF_ROLES: frozenset[str] = frozenset({
    "customer",
    "translate",
    "lead",
    "triage",
    "dream",
})


# Regex: `<handoff to="ROLE" reason="FREE TEXT" />`
# - Case-insensitive
# - Self-closing only (no children)
# - Attribute order: to before reason
# - reason is OPTIONAL (per contract §2.1 OQ-E3-2 free-text)
# - Reason max 200 chars (enforced post-regex, not in pattern, so overlong
#   reason → match captured then truncated + flagged)
_HANDOFF_PATTERN = re.compile(
    r"""
    <\s*handoff
    \s+to\s*=\s*["']([A-Za-z_]+)["']          # group 1: role (letters/underscore)
    (?:\s+reason\s*=\s*["']([^"']{0,500})["'])?  # group 2: optional reason (cap 500 raw)
    \s*/\s*>                                    # self-closing
    """,
    re.IGNORECASE | re.VERBOSE,
)


MAX_REASON_CHARS = 200


@dataclass(frozen=True)
class HandoffResult:
    """Parsed handoff directive."""
    target_role: str       # lowercased, validated against VALID_HANDOFF_ROLES
    reason: Optional[str]  # free-text, truncated to MAX_REASON_CHARS
    raw_tag: str           # original matched substring (for audit)


def parse_handoff(agent_output: str) -> tuple[Optional[HandoffResult], str]:
    """Parse first valid ``<handoff />`` tag from *agent_output*.

    Return semantics (mirrors :func:`parse_sentiment`):
    * ``(HandoffResult, cleaned)`` on success — tag removed from output
    * ``(None, agent_output)`` on: no tag / unknown role / malformed tag

    Multiple tags: only the FIRST valid one is honoured (contract
    "Don't Do" rule 1).  Any subsequent tag is stripped from output
    but NOT dispatched — avoids ambiguity in re-triage.

    Adversarial input handling:
    * Non-whitelisted role → reject (None, original)
    * Reason > 200 chars → truncated, still dispatched
    * Nested / non-self-closing → regex won't match
    * HTML/script injection inside reason → stays as free text, caller
      must re-escape before rendering (we don't HTML-escape; that's UI's job)
    """
    match = _HANDOFF_PATTERN.search(agent_output)
    if match is None:
        return None, agent_output

    role = match.group(1).lower()
    if role not in VALID_HANDOFF_ROLES:
        return None, agent_output

    reason_raw = match.group(2)
    reason: Optional[str] = None
    if reason_raw is not None:
        reason = reason_raw.strip()
        if len(reason) > MAX_REASON_CHARS:
            reason = reason[:MAX_REASON_CHARS]

    raw_tag = match.group(0)

    # Remove the tag from output (and any subsequent handoff tags — strip all)
    cleaned = _HANDOFF_PATTERN.sub("", agent_output).strip()

    return (
        HandoffResult(target_role=role, reason=reason, raw_tag=raw_tag),
        cleaned,
    )
