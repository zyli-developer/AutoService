"""Rules backend with conversational config.

T4A.2 产出 | 2026-04-16
"""

from __future__ import annotations

import uuid
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

RULES_DIR = Path(".autoservice/rules")

VALID_CATEGORIES = ("greeting", "escalation", "response", "compliance")

# Parameter templates per category — maps category to its editable parameters.
CATEGORY_PARAMETERS: dict[str, list[str]] = {
    "greeting": ["template", "tone", "language"],
    "escalation": ["threshold", "trigger", "notify_channel"],
    "response": ["max_length", "formality", "language"],
    "compliance": ["constraint", "severity", "audit_log"],
}

# ---------------------------------------------------------------------------
# Core load / save (preserved from original)
# ---------------------------------------------------------------------------


def load_rules(rules_dir: Path | None = None) -> list[dict]:
    """Load all rules from all YAML files in the rules directory."""
    rd = rules_dir or RULES_DIR
    rules: list[dict] = []
    if not rd.exists():
        return rules
    for f in sorted(rd.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or []
            if isinstance(data, list):
                for r in data:
                    r["_source"] = f.name
                rules.extend(data)
        except Exception:
            pass
    return rules


def save_rules(filename: str, rules: list[dict], rules_dir: Path | None = None) -> Path:
    """Save rules to a YAML file."""
    rd = rules_dir or RULES_DIR
    rd.mkdir(parents=True, exist_ok=True)
    path = rd / filename
    # Strip transient _source before persisting
    clean = [{k: v for k, v in r.items() if k != "_source"} for r in rules]
    path.write_text(yaml.dump(clean, allow_unicode=True, default_flow_style=False))
    return path


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def _generate_id() -> str:
    return uuid.uuid4().hex[:8]


def get_rule(rule_id: str, rules_dir: Path | None = None) -> dict | None:
    """Get a single rule by its id."""
    for r in load_rules(rules_dir):
        if str(r.get("id")) == str(rule_id):
            return r
    return None


def update_rule(rule_id: str, updates: dict, rules_dir: Path | None = None) -> dict:
    """Update a rule in-place and persist.  Returns updated rule.

    Raises ``KeyError`` if rule_id not found.
    """
    rd = rules_dir or RULES_DIR
    for f in sorted(rd.glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or []
        if not isinstance(data, list):
            continue
        for r in data:
            if str(r.get("id")) == str(rule_id):
                r.update(updates)
                r["updated_at"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
                save_rules(f.name, data, rd)
                r["_source"] = f.name
                return r
    raise KeyError(f"Rule {rule_id!r} not found")


def delete_rule(rule_id: str, rules_dir: Path | None = None) -> bool:
    """Delete a rule by id.  Returns True if deleted."""
    rd = rules_dir or RULES_DIR
    for f in sorted(rd.glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or []
        if not isinstance(data, list):
            continue
        before = len(data)
        data = [r for r in data if str(r.get("id")) != str(rule_id)]
        if len(data) < before:
            save_rules(f.name, data, rd)
            return True
    return False


def list_rules(category: str | None = None, rules_dir: Path | None = None) -> list[dict]:
    """List rules, optionally filtered by category."""
    rules = load_rules(rules_dir)
    if category:
        rules = [r for r in rules if r.get("category") == category]
    return rules


def add_rule(
    category: str,
    rule: str,
    created_by: str = "",
    filename: str | None = None,
    rules_dir: Path | None = None,
    **extra: Any,
) -> dict:
    """Add a rule.  Auto-generates id.  Returns the new rule dict."""
    rd = rules_dir or RULES_DIR
    fname = filename or f"{category}.yaml"
    path = rd / fname
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []

    new_rule: dict[str, Any] = {
        "id": _generate_id(),
        "category": category,
        "rule": rule,
        "created_by": created_by,
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
    }
    new_rule.update(extra)
    existing.append(new_rule)
    save_rules(fname, existing, rd)
    return new_rule


# ---------------------------------------------------------------------------
# Prompt formatting (preserved)
# ---------------------------------------------------------------------------


def format_rules_for_prompt(rules_dir: Path | None = None) -> str:
    """Format all universal rules as a text block for channel instructions."""
    rules = load_rules(rules_dir)
    if not rules:
        return "(暂无通用行为规则)"
    lines = []
    for r in rules:
        ctx = f"[{r.get('category', r.get('context', 'general'))}] " if r.get("category") or r.get("context") else ""
        lines.append(f"- {ctx}{r['rule']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversational config state machine
# ---------------------------------------------------------------------------


class RuleConfigState(str, Enum):
    IDLE = "idle"
    AWAITING_CATEGORY = "awaiting_category"
    AWAITING_PARAMETER = "awaiting_parameter"
    AWAITING_VALUE = "awaiting_value"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


@dataclass
class RuleConfigSession:
    """Interactive 4-step dialog for collecting rule parameters."""

    state: RuleConfigState = RuleConfigState.IDLE
    rule_id: str | None = None
    category: str | None = None
    parameter: str | None = None
    value: Any = None
    mode: str = "edit"  # "edit" | "add"
    rules_dir: Path | None = None

    def reset(self) -> None:
        """Reset session to IDLE."""
        self.state = RuleConfigState.IDLE
        self.rule_id = None
        self.category = None
        self.parameter = None
        self.value = None
        self.mode = "edit"

    def process_input(self, user_input: str) -> tuple[str, bool]:
        """Drive the state machine forward.

        Returns ``(response_message, is_complete)``.
        """
        text = user_input.strip()

        # --- AWAITING_CATEGORY ---
        if self.state == RuleConfigState.AWAITING_CATEGORY:
            if text.lower() in VALID_CATEGORIES:
                self.category = text.lower()
                if self.mode == "add":
                    self.state = RuleConfigState.AWAITING_PARAMETER
                    return (
                        f"Category set to '{self.category}'. "
                        f"Enter the rule text:",
                        False,
                    )
                # edit mode — list params
                params = CATEGORY_PARAMETERS.get(self.category, [])
                self.state = RuleConfigState.AWAITING_PARAMETER
                return (
                    f"Category: {self.category}\n"
                    f"Available parameters: {', '.join(params)}\n"
                    f"Which parameter do you want to edit?",
                    False,
                )
            return (
                f"Invalid category. Choose one of: {', '.join(VALID_CATEGORIES)}",
                False,
            )

        # --- AWAITING_PARAMETER ---
        if self.state == RuleConfigState.AWAITING_PARAMETER:
            if self.mode == "add":
                # In add mode, this step collects the rule text
                self.parameter = "rule"
                self.value = text
                self.state = RuleConfigState.AWAITING_CONFIRMATION
                return (
                    f"New rule summary:\n"
                    f"  Category: {self.category}\n"
                    f"  Rule: {self.value}\n"
                    f"Confirm? (yes/no)",
                    False,
                )
            # edit mode — validate parameter name
            params = CATEGORY_PARAMETERS.get(self.category, [])
            if text.lower() in params:
                self.parameter = text.lower()
                self.state = RuleConfigState.AWAITING_VALUE
                return (f"Enter new value for '{self.parameter}':", False)
            return (
                f"Unknown parameter. Choose one of: {', '.join(params)}",
                False,
            )

        # --- AWAITING_VALUE ---
        if self.state == RuleConfigState.AWAITING_VALUE:
            self.value = text
            self.state = RuleConfigState.AWAITING_CONFIRMATION
            return (
                f"Will set '{self.parameter}' = '{self.value}' on rule {self.rule_id}. Confirm? (yes/no)",
                False,
            )

        # --- AWAITING_CONFIRMATION ---
        if self.state == RuleConfigState.AWAITING_CONFIRMATION:
            if text.lower() in ("yes", "y"):
                result = self._apply()
                self.reset()
                return (result, True)
            self.reset()
            return ("Cancelled.", True)

        return ("Session is idle. Use /rules command to start.", False)

    def _apply(self) -> str:
        """Persist the collected change."""
        if self.mode == "add":
            new = add_rule(
                category=self.category or "general",
                rule=self.value or "",
                rules_dir=self.rules_dir,
            )
            return f"Rule added (id={new['id']})."

        # edit mode
        try:
            updated = update_rule(
                self.rule_id or "",
                {self.parameter or "": self.value},
                rules_dir=self.rules_dir,
            )
            return f"Rule {updated['id']} updated."
        except KeyError:
            return f"Rule {self.rule_id!r} not found."


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


def handle_rules_command(
    args: list[str],
    session: RuleConfigSession | None = None,
    rules_dir: Path | None = None,
) -> str:
    """/rules command dispatcher.

    Subcommands:
        show [category]      — list rules
        edit <rule_id>       — start interactive edit
        add                  — start interactive add
        delete <rule_id>     — delete rule
    """
    if not args:
        return "Usage: /rules show|edit|add|delete"

    sub = args[0].lower()

    if sub == "show":
        cat = args[1] if len(args) > 1 else None
        if cat and cat not in VALID_CATEGORIES:
            return f"Unknown category '{cat}'. Valid: {', '.join(VALID_CATEGORIES)}"
        rules = list_rules(category=cat, rules_dir=rules_dir)
        if not rules:
            return "No rules found." if not cat else f"No rules in category '{cat}'."
        lines = []
        for r in rules:
            cat_label = r.get("category", r.get("context", "?"))
            lines.append(f"[{r['id']}] [{cat_label}] {r.get('rule', '')}")
        return "\n".join(lines)

    if sub == "edit":
        if len(args) < 2:
            return "Usage: /rules edit <rule_id>"
        rule_id = args[1]
        rule = get_rule(rule_id, rules_dir=rules_dir)
        if not rule:
            return f"Rule '{rule_id}' not found."
        if session is None:
            return "No active session — cannot start interactive edit."
        session.reset()
        session.mode = "edit"
        session.rule_id = rule_id
        session.rules_dir = rules_dir
        cat = rule.get("category")
        if cat and cat in VALID_CATEGORIES:
            session.category = cat
            params = CATEGORY_PARAMETERS.get(cat, [])
            session.state = RuleConfigState.AWAITING_PARAMETER
            return (
                f"Editing rule {rule_id} (category: {cat}).\n"
                f"Available parameters: {', '.join(params)}\n"
                f"Which parameter?"
            )
        session.state = RuleConfigState.AWAITING_CATEGORY
        return (
            f"Editing rule {rule_id}.\n"
            f"Select category: {', '.join(VALID_CATEGORIES)}"
        )

    if sub == "add":
        if session is None:
            return "No active session — cannot start interactive add."
        session.reset()
        session.mode = "add"
        session.rules_dir = rules_dir
        session.state = RuleConfigState.AWAITING_CATEGORY
        return f"Adding new rule.\nSelect category: {', '.join(VALID_CATEGORIES)}"

    if sub == "delete":
        if len(args) < 2:
            return "Usage: /rules delete <rule_id>"
        rule_id = args[1]
        ok = delete_rule(rule_id, rules_dir=rules_dir)
        return f"Rule '{rule_id}' deleted." if ok else f"Rule '{rule_id}' not found."

    return f"Unknown subcommand '{sub}'. Usage: /rules show|edit|add|delete"
