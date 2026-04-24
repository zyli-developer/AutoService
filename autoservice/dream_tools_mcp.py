"""In-process SDK-type MCP server exposing Dream tools to role='dream' CC instances.

Companion to :mod:`autoservice.kb_mcp_server` (which wires ``kb_search`` for
customer / lead roles). This module wires all three Dream tools as REAL MCP
tools so the CLI subprocess can invoke them via the proper tool-use round
trip — not via the prompt-text trick that ``CCClient.call_with_tools`` was
falling back to. Without this, the model sees the tools mentioned in the
prompt but reports "emit_proposal is not available in my current function
set" and never actually records a proposal.

Tenant isolation (CON-04 red-line): ``build_dream_tools_mcp_server`` closes
over the caller-provided ``tenant_id`` and proposals DB path. The model may
NOT override either — any ``tenant_id`` it tries to pass in args is
silently discarded, and the ``status`` column is hard-coded inside
:func:`autoservice.dream_agent.emit_proposal`.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from autoservice import dream_agent as _da

logger = logging.getLogger("autoservice.dream_tools_mcp")


PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Default proposals DB — production path used by api_routes /
#: ``ProposalPipeline``. Tests override via the ``proposals_db_path``
#: argument to :func:`build_dream_tools_mcp_server`.
DEFAULT_PROPOSALS_DB = PROJECT_ROOT / ".autoservice" / "database" / "proposals.db"


def _fmt_kb_rows(rows: list[dict]) -> str:
    """Render KB search rows the same way :mod:`kb_mcp_server` does."""
    if not rows:
        return "No KB matches. Escalate if this is essential."
    lines: list[str] = []
    for i, row in enumerate(rows, 1):
        source = row.get("source_name") or ""
        section = row.get("section") or ""
        header = f"[{i}]"
        if source:
            header += f" {source}"
        if section:
            header += f" · {section}"
        lines.append(header)
        lines.append((row.get("content") or "").strip())
        lines.append("")
    return "\n".join(lines).strip()


def _fmt_souls(rows: list[dict]) -> str:
    if not rows:
        return "No peer souls on disk for this tenant."
    lines: list[str] = []
    for row in rows:
        lines.append(f"## {row.get('role', 'unknown')}_soul")
        excerpt = (row.get("excerpt") or "").strip()
        lines.append(excerpt or "(empty)")
        lines.append("")
    return "\n".join(lines).strip()


def build_dream_tools_mcp_server(
    tenant_id: str,
    proposals_db_path: Path | None = None,
    sandbox_root: Path | None = None,
) -> Any:
    """Build an in-process MCP server scoped to *tenant_id*.

    Args:
        tenant_id: The Dream run's tenant — threaded into every tool
            invocation via closure. The agent may NOT override it.
        proposals_db_path: Sqlite path for the ``proposals`` table.
            Defaults to :data:`DEFAULT_PROPOSALS_DB`.
        sandbox_root: Override for ``.autoservice/sandbox``. Tests point
            this at ``tmp_path``; production leaves it ``None``.

    Returns:
        The ``McpSdkServerConfig`` dict to plug into
        :attr:`ClaudeAgentOptions.mcp_servers`.
    """
    db_path = Path(proposals_db_path) if proposals_db_path else DEFAULT_PROPOSALS_DB

    @tool(
        "emit_proposal",
        (
            "File a draft proposal for the admin to review. Status is "
            "always 'draft' (never overridable — admin approval required). "
            "Call once per finding. category should be a short snake_case "
            "string (e.g. 'platform_level', 'response_quality', 'knowledge_gap'). "
            "risk_level must be low/medium/high. target_role must be one of "
            "customer, operator, lead, translate, triage, dream."
        ),
        {
            "title": str,
            "description": str,
            "suggestion": str,
            "evidence": str,
            "risk_level": str,
            "target_role": str,
            "category": str,
        },
    )
    async def emit_proposal_tool(args: dict[str, Any]) -> dict[str, Any]:
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                proposal_id = _da.emit_proposal(
                    conn,
                    tenant_id=tenant_id,
                    category=str(args.get("category", "")),
                    title=str(args.get("title", "")),
                    description=str(args.get("description", "")),
                    suggestion=str(args.get("suggestion", "")),
                    evidence=str(args.get("evidence", "")),
                    risk_level=str(args.get("risk_level", "")),
                    target_role=str(args.get("target_role", "")),
                )
            finally:
                conn.close()
            logger.info(
                "[dream_tools_mcp] emit_proposal ok tenant=%s id=%s",
                tenant_id, proposal_id,
            )
            return {
                "content": [{
                    "type": "text",
                    "text": f"Proposal filed: id={proposal_id}, status=draft.",
                }],
            }
        except ValueError as exc:
            return {
                "content": [{"type": "text", "text": f"Invalid args: {exc}"}],
                "isError": True,
            }
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.exception(
                "[dream_tools_mcp] emit_proposal internal error tenant=%s: %s",
                tenant_id, exc,
            )
            return {
                "content": [{"type": "text", "text": f"Internal error: {exc}"}],
                "isError": True,
            }

    @tool(
        "kb_search",
        (
            "Search this tenant's knowledge base. Returns up to top_k rows. "
            "Use to gather supporting evidence before calling emit_proposal."
        ),
        {"query": str, "top_k": int},
    )
    async def kb_search_tool(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        try:
            top_k = int(args.get("top_k", 5) or 5)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(top_k, 10))

        if not query:
            return {"content": [{"type": "text", "text": "Empty query."}]}

        try:
            rows = _da.kb_search(
                tenant_id, query, top_k=top_k, sandbox_root=sandbox_root,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.exception(
                "[dream_tools_mcp] kb_search raised tenant=%s query=%r: %s",
                tenant_id, query, exc,
            )
            return {
                "content": [{"type": "text", "text": f"KB error: {exc}"}],
                "isError": True,
            }
        return {"content": [{"type": "text", "text": _fmt_kb_rows(rows)}]}

    @tool(
        "list_souls",
        (
            "List this tenant's peer-agent soul excerpts (customer, lead, "
            "translate, triage) so you can reason about how each agent "
            "currently behaves. The dream soul itself is excluded — dream "
            "never self-modifies."
        ),
        {},
    )
    async def list_souls_tool(args: dict[str, Any]) -> dict[str, Any]:
        try:
            rows = _da.list_souls(tenant_id, sandbox_root=sandbox_root)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.exception(
                "[dream_tools_mcp] list_souls raised tenant=%s: %s",
                tenant_id, exc,
            )
            return {
                "content": [{"type": "text", "text": f"list_souls error: {exc}"}],
                "isError": True,
            }
        return {"content": [{"type": "text", "text": _fmt_souls(rows)}]}

    return create_sdk_mcp_server(
        name="autoservice_dream_tools",
        version="1.0.0",
        tools=[emit_proposal_tool, kb_search_tool, list_souls_tool],
    )
