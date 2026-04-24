"""Customer-role side-channel preamble stripper.

Some agent replies leak a "meta monologue" block at the very start —
the model narrating its own decision process before the actual answer
("根据我的系统提示，作为 CINNOX 客服代理，我可以直接基于知识库给出回复。
让我回应客户：" / "As the assistant, I should … Let me respond:"). The
customer soul (`agents/customer/soul.md`) does not explicitly forbid
this and prompt-level reinforcement is unreliable, so we strip it here.

Return contract mirrors :mod:`autoservice.lead_summary`:
``(preamble_or_None, cleaned_text)``. ``preamble`` is ``None`` when no
preamble is detected and ``cleaned_text`` is the original string
unchanged — fail-closed, we'd rather leak a fragment once than swallow
a legitimate reply.

The caller routes ``preamble`` to a SIDE message so it stays auditable
(operators and logs keep it) without reaching the customer.
"""
from __future__ import annotations

import re
from typing import Optional

# Window we'll consider as "candidate preamble". A longer window risks
# eating into a real reply that happens to contain a self-reference
# keyword further down. 300 chars comfortably covers observed leaks
# (the production screenshot was ~60 chars).
_MAX_PREAMBLE_CHARS = 300

# The remaining body must be at least this long after stripping. Below
# this, we bail out rather than send a stump — fail-closed.
_MIN_BODY_CHARS = 15

# Meta-monologue markers. ANY ONE match inside the candidate head is
# enough. Patterns are deliberately tight — they require BOTH a
# self-reference AND a role/prompt/process reference — to avoid
# stripping innocuous leading text that happens to contain one keyword.
_META_MARKERS: tuple[re.Pattern[str], ...] = (
    # "作为 X 代理 / 助手 / 客服 / AI"
    re.compile(r"作为[^\n，。,!?！？]{0,25}(代理|助手|客服|AI|客户服务)"),
    # "根据(我的)系统提示 / 指示 / 提示词 / prompt"
    re.compile(
        r"根据[^\n]{0,25}(系统提示|系统指示|提示词|指示|prompt)",
        re.IGNORECASE,
    ),
    # "让我(来)回应 / 回复 / 回答 / 答复 客户 / 用户 / 您 / 你"
    re.compile(
        r"让我[^\n]{0,15}(回应|回复|回答|答复)[^\n]{0,8}(客户|用户|您|你)"
    ),
    # "我(可以/将/会/需要/应该) 直接/基于/根据 知识库/KB/提示/回答/回复"
    re.compile(
        r"我(?:可以|将|会|需要|应该)[^\n]{0,25}"
        r"(?:直接|基于|根据)[^\n]{0,20}"
        r"(?:知识库|KB|提示|回答|回复|给出)",
        re.IGNORECASE,
    ),
    # English: "As the/an X assistant/agent/AI/bot/support"
    re.compile(
        r"\bAs\s+(?:the|an?)\s+[A-Za-z ]{0,30}"
        r"(?:assistant|agent|AI|bot|support|customer\s+service)\b",
        re.IGNORECASE,
    ),
    # English: "Let me respond/reply/answer to the customer/user"
    re.compile(
        r"\bLet me\s+(?:respond|reply|answer)\s+to\s+the\s+(?:customer|user)\b",
        re.IGNORECASE,
    ),
)

# Where the preamble ends. Earliest wins.
#   - "…让我回应客户：\n您好…"         → split on colon+newline
#   - "…我来回答。\n\n您好…"           → split on paragraph break
_SPLIT_COLON = re.compile(r"[：:][ \t]*\n+")
_SPLIT_PARA = re.compile(r"\n{2,}")


def parse_customer_preamble(
    agent_output: str,
) -> tuple[Optional[str], str]:
    """Strip a leading meta-monologue preamble from an agent reply.

    Args:
        agent_output: Raw reply text from the model.

    Returns:
        ``(preamble, cleaned)`` when a preamble is detected:
        - ``preamble`` is the stripped block (whitespace trimmed) — the
          caller should emit it as a SIDE message for audit.
        - ``cleaned`` is the customer-visible reply with the preamble
          removed and surrounding whitespace trimmed.

        ``(None, agent_output)`` when no preamble is detected, or when
        stripping would leave the body too short to be useful. The
        caller should send ``agent_output`` unchanged in that case.
    """
    if not agent_output:
        return None, agent_output

    stripped = agent_output.lstrip()
    if not stripped:
        return None, agent_output

    window = stripped[:_MAX_PREAMBLE_CHARS]

    colon = _SPLIT_COLON.search(window)
    para = _SPLIT_PARA.search(window)
    candidates = [m for m in (colon, para) if m is not None]
    if not candidates:
        return None, agent_output

    split = min(candidates, key=lambda m: m.start())
    head = stripped[: split.start() + 1]  # include the splitting char
    body = stripped[split.end():]

    if not any(pat.search(head) for pat in _META_MARKERS):
        return None, agent_output

    if len(body.strip()) < _MIN_BODY_CHARS:
        return None, agent_output

    return head.strip(), body.strip()
