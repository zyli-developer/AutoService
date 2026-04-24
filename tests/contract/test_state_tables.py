"""Lock spec markdown tables to Python constants, engine-independent.

Anti-drift tests: Gate matrix, legal Mode transitions, invariants list, and
permission matrix all exist as source-of-truth constants and as tables in
docs/contracts/conversation-engine.md. Parse the markdown and assert the two
representations agree. Any spec change that forgets one side trips these.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    MessageVisibility,
    ParticipantRole,
)

ENGINE_DOC = (
    Path(__file__).resolve().parents[2]
    / "docs" / "contracts" / "conversation-engine.md"
)


# ---------- Source-of-truth constants ----------

# T0.1 §4 Gate table — (mode, sender_role, requested=PUBLIC) → final_visibility
# Only rows where requested=PUBLIC appear in §4; requested=SIDE/SYSTEM is
# never downgraded (Q5) and handled separately.
GATE_MATRIX: dict[tuple[ConversationMode, ParticipantRole], MessageVisibility] = {
    (ConversationMode.AUTO, ParticipantRole.AGENT): MessageVisibility.PUBLIC,
    (ConversationMode.AUTO, ParticipantRole.CUSTOMER): MessageVisibility.PUBLIC,
    (ConversationMode.AUTO, ParticipantRole.OPERATOR): MessageVisibility.SIDE,
    (ConversationMode.COPILOT, ParticipantRole.AGENT): MessageVisibility.PUBLIC,
    (ConversationMode.COPILOT, ParticipantRole.OPERATOR): MessageVisibility.SIDE,
    (ConversationMode.TAKEOVER, ParticipantRole.AGENT): MessageVisibility.SIDE,
    (ConversationMode.TAKEOVER, ParticipantRole.OPERATOR): MessageVisibility.PUBLIC,
}


# T0.1 §3 Mode: transitions allowed by switch_mode + auto transitions.
# Target == current handled as mode.noop (Q4), not IllegalModeTransition.
LEGAL_MODE_TRANSITIONS: set[tuple[ConversationMode, ConversationMode]] = {
    (ConversationMode.AUTO, ConversationMode.COPILOT),
    (ConversationMode.AUTO, ConversationMode.TAKEOVER),
    (ConversationMode.COPILOT, ConversationMode.AUTO),
    (ConversationMode.COPILOT, ConversationMode.TAKEOVER),
    (ConversationMode.TAKEOVER, ConversationMode.AUTO),
    (ConversationMode.TAKEOVER, ConversationMode.COPILOT),
}


# T0.1 §6.1 — actors × commands → allowed (True/False).
# ADMIN is an out-of-enum role (T0.2 §1); represented here as string.
PERMISSION_MATRIX: dict[tuple[str, str], bool] = {
    # customer: nothing
    **{("customer", cmd): False for cmd in
       ["/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status", "/dispatch", "/assign"]},
    # agent: nothing
    **{("agent", cmd): False for cmd in
       ["/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status", "/dispatch", "/assign"]},
    # operator: all except /dispatch, /assign
    ("operator", "/hijack"): True,
    ("operator", "/release"): True,
    ("operator", "/copilot"): True,
    ("operator", "/resolve"): True,
    ("operator", "/abandon"): True,
    ("operator", "/status"): True,
    ("operator", "/dispatch"): False,
    ("operator", "/assign"): False,
    # admin: everything
    **{("admin", cmd): True for cmd in
       ["/hijack", "/release", "/copilot", "/resolve", "/abandon", "/status", "/dispatch", "/assign"]},
}


INVARIANTS = [
    "create_conversation 幂等",
    "close_conversation 幂等",
    "mode 切换原子",
    "事件顺序",
    "Gate 降级不可逆",
    "读写路径对称",
    "Plugin Hook 隔离",
    "最后一个 operator leave 回落",
]


# ---------- Fixture: parse engine doc once ----------

@pytest.fixture(scope="module")
def doc_text() -> str:
    return ENGINE_DOC.read_text(encoding="utf-8")


# ---------- Gate matrix ----------

def _visibility_from_cell(cell: str) -> MessageVisibility:
    c = cell.lower()
    if "side" in c:
        return MessageVisibility.SIDE
    if "public" in c:
        return MessageVisibility.PUBLIC
    raise ValueError(cell)


def _parse_gate_matrix(doc: str) -> dict:
    # §4 table: rows with mode | role | public | visibility cells
    out = {}
    for line in doc.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        mode_cell = cells[0].lower()
        role_cell = cells[1].lower()
        if mode_cell not in {m.value for m in ConversationMode}:
            continue
        if role_cell not in {r.value for r in ParticipantRole}:
            continue
        vis = _visibility_from_cell(cells[2])
        out[(ConversationMode(mode_cell), ParticipantRole(role_cell))] = vis
    return out


def test_gate_matrix_matches_spec(doc_text):
    parsed = _parse_gate_matrix(doc_text)
    assert parsed == GATE_MATRIX, (
        f"§4 Gate table drift vs GATE_MATRIX.\n"
        f"Only in spec: {parsed.keys() - GATE_MATRIX.keys()}\n"
        f"Only in const: {GATE_MATRIX.keys() - parsed.keys()}"
    )


@pytest.mark.parametrize("key,vis", sorted(GATE_MATRIX.items(), key=lambda x: (x[0][0].value, x[0][1].value)))
def test_gate_matrix_individual_row(key, vis):
    """Per-row parametrize: drift in any single cell fails its own test."""
    mode, role = key
    assert GATE_MATRIX[(mode, role)] == vis


def test_gate_only_downgrades_public_to_side_q5():
    """Q5 / §7.1 #5: Gate never upgrades. SIDE → PUBLIC must not appear."""
    for (mode, role), final in GATE_MATRIX.items():
        # requested is implicitly PUBLIC for all §4 rows
        if final == MessageVisibility.PUBLIC:
            continue
        assert final == MessageVisibility.SIDE, f"Unexpected visibility {final}"


# ---------- Legal mode transitions ----------

@pytest.mark.parametrize("src,dst", sorted(((a.value, b.value) for a, b in LEGAL_MODE_TRANSITIONS)))
def test_legal_mode_transition_pair(src, dst):
    # Symmetric coverage: both directions for every pair are in the set.
    assert (ConversationMode(src), ConversationMode(dst)) in LEGAL_MODE_TRANSITIONS


def test_self_transitions_not_in_legal_set():
    """Q4: target == current is mode.noop, not switch_mode's legal set."""
    for m in ConversationMode:
        assert (m, m) not in LEGAL_MODE_TRANSITIONS


def test_all_nonself_pairs_are_legal():
    """Current design has every non-self pair allowed (operator can freely
    switch between modes in either direction)."""
    all_modes = list(ConversationMode)
    for a in all_modes:
        for b in all_modes:
            if a == b:
                continue
            assert (a, b) in LEGAL_MODE_TRANSITIONS


# ---------- Permission matrix ----------

def _parse_permission_matrix(doc: str) -> dict:
    """Extract §6.1 table: command | customer | agent | operator | admin | …"""
    out: dict = {}
    in_table = False
    header_seen = False
    for line in doc.splitlines():
        if "§6.1" in line or "handle_command 权限矩阵" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if in_table and not line.startswith("|"):
            if header_seen:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not header_seen:
            if cells and cells[0].lower().startswith("command"):
                header_seen = True
            continue
        if cells and cells[0].startswith("---"):
            continue
        if not cells or not cells[0].startswith("`/"):
            break
        command = cells[0].strip("`").strip()
        # columns: customer, agent, operator, admin, (notes)
        for i, role in enumerate(("customer", "agent", "operator", "admin"), start=1):
            mark = cells[i] if i < len(cells) else ""
            out[(role, command)] = ("✅" in mark)
    return out


def test_permission_matrix_matches_spec(doc_text):
    parsed = _parse_permission_matrix(doc_text)
    # Compare only the keys that appear in both — spec has /status/dispatch/assign
    # plus mode commands; constants cover the same set. Any difference = drift.
    common = set(parsed.keys()) & set(PERMISSION_MATRIX.keys())
    mismatches = [
        k for k in common if parsed[k] != PERMISSION_MATRIX[k]
    ]
    assert not mismatches, f"Permission matrix drift: {mismatches[:5]}"
    # Keys only on one side flag incomplete coverage
    assert not (set(PERMISSION_MATRIX.keys()) - set(parsed.keys())), (
        "PERMISSION_MATRIX has entries absent from §6.1 table"
    )


@pytest.mark.parametrize("command", ["/hijack", "/release", "/copilot", "/resolve", "/abandon"])
def test_operator_can_run_standard_commands(command):
    assert PERMISSION_MATRIX[("operator", command)] is True


@pytest.mark.parametrize("command", ["/hijack", "/resolve"])
def test_customer_and_agent_cannot_run_mode_commands(command):
    assert PERMISSION_MATRIX[("customer", command)] is False
    assert PERMISSION_MATRIX[("agent", command)] is False


@pytest.mark.parametrize("command", ["/dispatch", "/assign"])
def test_only_admin_can_run_privileged_commands(command):
    assert PERMISSION_MATRIX[("admin", command)] is True
    assert PERMISSION_MATRIX[("operator", command)] is False
    assert PERMISSION_MATRIX[("agent", command)] is False
    assert PERMISSION_MATRIX[("customer", command)] is False


# ---------- Invariants (§7.1) ----------

def test_invariants_section_present(doc_text):
    assert "§7.1" in doc_text or "7.1 不变量" in doc_text


@pytest.mark.parametrize("phrase", INVARIANTS)
def test_invariant_mentioned_in_spec(doc_text, phrase):
    assert phrase in doc_text, f"Invariant missing from §7.1: {phrase}"


def test_invariant_count_is_eight(doc_text):
    """§7.1 was frozen at 8 invariants in v1.0."""
    # Count numbered lines "1." … "8." within the §7.1 block
    m = re.search(
        r"### 7\.1 不变量.*?\n(.+?)(?:\n---|\n## )",
        doc_text,
        re.DOTALL,
    )
    assert m, "§7.1 block not found"
    block = m.group(1)
    numbered = re.findall(r"^\s*(\d+)\.\s+\*\*", block, re.MULTILINE)
    assert numbered == [str(i) for i in range(1, 9)], (
        f"§7.1 invariant numbering drift: {numbered}"
    )
