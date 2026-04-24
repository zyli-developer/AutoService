"""Lead-role side-channel summary parser.

The ``lead`` role's soul (`agents/lead/soul.md` §输出格式) instructs the LLM
to emit a structured summary after collecting lead info:

    [线索] 联系方式: xxx | 需求: xxx | 预算: xxx | 时间线: xxx | 意向: hot/warm/cold

The soul calls it a "side channel" line, but there was no side-channel
pipeline — the line flowed straight into the customer-visible message.
This parser is that missing side channel: extract the fields for
structured logging / CRM write, strip the directive from the reply.

Return contract mirrors :mod:`autoservice.handoff` and
:mod:`autoservice.sentiment`: ``(result, cleaned_output)``. ``result`` is
``None`` when no directive is present; ``cleaned_output`` is the original
string in that case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


VALID_INTENTS: frozenset[str] = frozenset({"hot", "warm", "cold"})

MAX_FIELD_CHARS = 500


# Regex notes:
# - MULTILINE + VERBOSE: ``^``/``$`` match line boundaries, whitespace in
#   the pattern is ignored unless escaped.
# - Field order is fixed (contract with soul.md); reordered input rejected.
# - Colon may be ASCII ``:`` or full-width ``：`` (LLMs mix them).
# - Values capture lazily up to the next ``|`` or newline; pipe inside a
#   field would break the format and the LLM is instructed not to use it.
# - Per-field cap (100 chars, raw) sits below :data:`MAX_FIELD_CHARS` to
#   avoid catastrophic backtracking on adversarial input; post-match we
#   clip to MAX_FIELD_CHARS for the authoritative bound.
_LEAD_PATTERN = re.compile(
    r"""
    ^[ \t]*                                     # line start, optional indent
    \[\s*线索\s*\]                              # exact [线索] marker
    \s* 联系方式 \s* [:：] \s* (?P<contact>[^|\n]{0,600}?) \s*
    \| \s* 需求     \s* [:：] \s* (?P<demand>[^|\n]{0,600}?)  \s*
    \| \s* 预算     \s* [:：] \s* (?P<budget>[^|\n]{0,600}?)  \s*
    \| \s* 时间线    \s* [:：] \s* (?P<timeline>[^|\n]{0,600}?) \s*
    \| \s* 意向     \s* [:：] \s* (?P<intent>[^|\n\s][^|\n]{0,99}?)
    [ \t]* $                                    # optional trailing space, end-of-line
    """,
    re.MULTILINE | re.VERBOSE,
)


@dataclass(frozen=True)
class LeadSummaryResult:
    """Parsed lead-summary directive (one conversation turn)."""

    contact: str    # "未获取" sentinel if LLM didn't collect it
    demand: str
    budget: str
    timeline: str
    intent: str     # lowercased; check against VALID_INTENTS before trusting
    raw_line: str   # original matched substring (for audit log)

    def to_log_fields(self) -> dict[str, str]:
        """Flat dict for structured logging — ``logger.info(..., extra=r.to_log_fields())``."""
        return {
            "lead_contact": self.contact,
            "lead_demand": self.demand,
            "lead_budget": self.budget,
            "lead_timeline": self.timeline,
            "lead_intent": self.intent,
        }


def _clip(value: str) -> str:
    value = value.strip()
    if len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS]
    return value


def parse_lead_summary(agent_output: str) -> tuple[Optional[LeadSummaryResult], str]:
    """Extract the first ``[线索] ...`` directive from *agent_output*.

    Returns:
        ``(LeadSummaryResult, cleaned)`` when a well-formed directive is
        found.  ``cleaned`` is *agent_output* with **every** matching
        directive line removed (handles the rare "LLM emitted two
        summaries" case) plus any blank lines that the removal left
        dangling; trailing whitespace is rstripped so the caller can feed
        it directly into ``engine.edit_message(new_content=...)``.

        ``(None, agent_output)`` when no directive is present or the
        format is malformed (missing a field, reordered fields, wrong
        marker).  Fail-closed — we'd rather leak a fragment once than
        suppress a reply the LLM actually intended for the customer.
    """
    match = _LEAD_PATTERN.search(agent_output)
    if match is None:
        return None, agent_output

    contact = _clip(match.group("contact"))
    demand = _clip(match.group("demand"))
    budget = _clip(match.group("budget"))
    timeline = _clip(match.group("timeline"))
    intent = match.group("intent").strip().lower()
    if len(intent) > MAX_FIELD_CHARS:
        intent = intent[:MAX_FIELD_CHARS]

    result = LeadSummaryResult(
        contact=contact,
        demand=demand,
        budget=budget,
        timeline=timeline,
        intent=intent,
        raw_line=match.group(0),
    )

    # Strip *every* matching line (defensive — first is returned but
    # any additional occurrences must not leak either).
    cleaned = _LEAD_PATTERN.sub("", agent_output)
    # Collapse ≥3 consecutive newlines left by removal into one blank line.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.rstrip()

    return result, cleaned
