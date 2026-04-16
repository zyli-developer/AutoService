"""Tests for rules backend with conversational config (T4A.2)."""

from __future__ import annotations

import pytest

from autoservice.rules import (
    VALID_CATEGORIES,
    CATEGORY_PARAMETERS,
    RuleConfigSession,
    RuleConfigState,
    add_rule,
    delete_rule,
    get_rule,
    handle_rules_command,
    list_rules,
    load_rules,
    save_rules,
    update_rule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rules_dir(tmp_path):
    """Provide a temporary rules directory."""
    rd = tmp_path / "rules"
    rd.mkdir()
    return rd


@pytest.fixture()
def seed_rules(rules_dir):
    """Seed two rules across two categories."""
    r1 = add_rule("greeting", "Say hello warmly", rules_dir=rules_dir)
    r2 = add_rule("escalation", "Escalate after 3 failures", rules_dir=rules_dir)
    return r1, r2


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


class TestLoadSave:
    def test_load_empty_dir(self, rules_dir):
        assert load_rules(rules_dir) == []

    def test_save_and_load_roundtrip(self, rules_dir):
        rules = [{"id": "abc", "category": "greeting", "rule": "Hi"}]
        save_rules("greeting.yaml", rules, rules_dir)
        loaded = load_rules(rules_dir)
        assert len(loaded) == 1
        assert loaded[0]["rule"] == "Hi"
        assert loaded[0]["_source"] == "greeting.yaml"

    def test_load_skips_corrupt_yaml(self, rules_dir):
        (rules_dir / "bad.yaml").write_text(": : : not valid yaml list")
        # Should not raise
        load_rules(rules_dir)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_add_rule(self, rules_dir):
        r = add_rule("response", "Keep it short", rules_dir=rules_dir)
        assert r["category"] == "response"
        assert r["rule"] == "Keep it short"
        assert "id" in r

    def test_get_rule(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        found = get_rule(r1["id"], rules_dir=rules_dir)
        assert found is not None
        assert found["rule"] == "Say hello warmly"

    def test_get_rule_not_found(self, rules_dir):
        assert get_rule("nonexistent", rules_dir=rules_dir) is None

    def test_update_rule(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        updated = update_rule(r1["id"], {"rule": "Say hi gently"}, rules_dir=rules_dir)
        assert updated["rule"] == "Say hi gently"
        assert "updated_at" in updated
        # Verify persisted
        reloaded = get_rule(r1["id"], rules_dir=rules_dir)
        assert reloaded["rule"] == "Say hi gently"

    def test_update_rule_not_found(self, rules_dir):
        with pytest.raises(KeyError):
            update_rule("missing", {"rule": "x"}, rules_dir=rules_dir)

    def test_delete_rule(self, rules_dir, seed_rules):
        r1, r2 = seed_rules
        assert delete_rule(r1["id"], rules_dir=rules_dir) is True
        assert get_rule(r1["id"], rules_dir=rules_dir) is None
        # Other rule still present
        assert get_rule(r2["id"], rules_dir=rules_dir) is not None

    def test_delete_rule_not_found(self, rules_dir):
        assert delete_rule("nope", rules_dir=rules_dir) is False

    def test_list_rules_all(self, rules_dir, seed_rules):
        rules = list_rules(rules_dir=rules_dir)
        assert len(rules) == 2

    def test_list_rules_by_category(self, rules_dir, seed_rules):
        rules = list_rules(category="greeting", rules_dir=rules_dir)
        assert len(rules) == 1
        assert rules[0]["category"] == "greeting"

    def test_list_rules_category_no_match(self, rules_dir, seed_rules):
        rules = list_rules(category="compliance", rules_dir=rules_dir)
        assert len(rules) == 0


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestRuleConfigSession:
    def test_initial_state(self):
        s = RuleConfigSession()
        assert s.state == RuleConfigState.IDLE

    def test_reset(self):
        s = RuleConfigSession(state=RuleConfigState.AWAITING_VALUE, category="greeting")
        s.reset()
        assert s.state == RuleConfigState.IDLE
        assert s.category is None

    def test_idle_returns_message(self):
        s = RuleConfigSession()
        msg, done = s.process_input("anything")
        assert "idle" in msg.lower() or "/rules" in msg.lower()
        assert done is False

    # --- Full add flow ---
    def test_add_flow(self, rules_dir):
        s = RuleConfigSession(rules_dir=rules_dir)
        s.mode = "add"
        s.state = RuleConfigState.AWAITING_CATEGORY

        # Step 1: category
        msg, done = s.process_input("greeting")
        assert done is False
        assert s.state == RuleConfigState.AWAITING_PARAMETER
        assert s.category == "greeting"

        # Step 2: rule text
        msg, done = s.process_input("Always greet politely")
        assert done is False
        assert s.state == RuleConfigState.AWAITING_CONFIRMATION

        # Step 3: confirm
        msg, done = s.process_input("yes")
        assert done is True
        assert "added" in msg.lower()

        # Verify persisted
        rules = list_rules(category="greeting", rules_dir=rules_dir)
        assert len(rules) == 1
        assert rules[0]["rule"] == "Always greet politely"

    # --- Full edit flow ---
    def test_edit_flow(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        s = RuleConfigSession(rules_dir=rules_dir)
        s.mode = "edit"
        s.rule_id = r1["id"]
        s.state = RuleConfigState.AWAITING_CATEGORY

        # Step 1: category
        msg, done = s.process_input("greeting")
        assert done is False
        assert s.state == RuleConfigState.AWAITING_PARAMETER

        # Step 2: parameter
        msg, done = s.process_input("tone")
        assert done is False
        assert s.state == RuleConfigState.AWAITING_VALUE

        # Step 3: value
        msg, done = s.process_input("friendly")
        assert done is False
        assert s.state == RuleConfigState.AWAITING_CONFIRMATION

        # Step 4: confirm
        msg, done = s.process_input("y")
        assert done is True
        assert "updated" in msg.lower()

    def test_cancel_on_confirmation(self, rules_dir):
        s = RuleConfigSession(rules_dir=rules_dir)
        s.mode = "add"
        s.state = RuleConfigState.AWAITING_CONFIRMATION
        s.category = "greeting"
        s.value = "test"

        msg, done = s.process_input("no")
        assert done is True
        assert "cancel" in msg.lower()
        assert s.state == RuleConfigState.IDLE

    def test_invalid_category(self):
        s = RuleConfigSession()
        s.state = RuleConfigState.AWAITING_CATEGORY
        msg, done = s.process_input("bogus")
        assert done is False
        assert "invalid" in msg.lower()
        assert s.state == RuleConfigState.AWAITING_CATEGORY

    def test_invalid_parameter_edit(self):
        s = RuleConfigSession()
        s.mode = "edit"
        s.category = "greeting"
        s.state = RuleConfigState.AWAITING_PARAMETER
        msg, done = s.process_input("nonexistent_param")
        assert done is False
        assert "unknown" in msg.lower()
        assert s.state == RuleConfigState.AWAITING_PARAMETER


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


class TestHandleRulesCommand:
    def test_no_args(self):
        assert "Usage" in handle_rules_command([])

    def test_unknown_subcommand(self):
        msg = handle_rules_command(["foo"])
        assert "Unknown" in msg

    def test_show_empty(self, rules_dir):
        msg = handle_rules_command(["show"], rules_dir=rules_dir)
        assert "No rules" in msg

    def test_show_all(self, rules_dir, seed_rules):
        msg = handle_rules_command(["show"], rules_dir=rules_dir)
        assert "greeting" in msg
        assert "escalation" in msg

    def test_show_category_filter(self, rules_dir, seed_rules):
        msg = handle_rules_command(["show", "greeting"], rules_dir=rules_dir)
        assert "greeting" in msg
        assert "escalation" not in msg

    def test_show_invalid_category(self, rules_dir):
        msg = handle_rules_command(["show", "bogus"], rules_dir=rules_dir)
        assert "Unknown category" in msg

    def test_edit_missing_id(self, rules_dir):
        msg = handle_rules_command(["edit"], rules_dir=rules_dir)
        assert "Usage" in msg

    def test_edit_not_found(self, rules_dir):
        s = RuleConfigSession(rules_dir=rules_dir)
        msg = handle_rules_command(["edit", "nope"], session=s, rules_dir=rules_dir)
        assert "not found" in msg

    def test_edit_starts_session(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        s = RuleConfigSession(rules_dir=rules_dir)
        msg = handle_rules_command(["edit", r1["id"]], session=s, rules_dir=rules_dir)
        assert "Editing" in msg
        assert s.state == RuleConfigState.AWAITING_PARAMETER
        assert s.rule_id == r1["id"]

    def test_edit_no_session(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        msg = handle_rules_command(["edit", r1["id"]], rules_dir=rules_dir)
        assert "No active session" in msg

    def test_add_starts_session(self, rules_dir):
        s = RuleConfigSession(rules_dir=rules_dir)
        msg = handle_rules_command(["add"], session=s, rules_dir=rules_dir)
        assert "Adding" in msg
        assert s.state == RuleConfigState.AWAITING_CATEGORY

    def test_add_no_session(self, rules_dir):
        msg = handle_rules_command(["add"], rules_dir=rules_dir)
        assert "No active session" in msg

    def test_delete_success(self, rules_dir, seed_rules):
        r1, _ = seed_rules
        msg = handle_rules_command(["delete", r1["id"]], rules_dir=rules_dir)
        assert "deleted" in msg

    def test_delete_not_found(self, rules_dir):
        msg = handle_rules_command(["delete", "nope"], rules_dir=rules_dir)
        assert "not found" in msg

    def test_delete_missing_id(self, rules_dir):
        msg = handle_rules_command(["delete"], rules_dir=rules_dir)
        assert "Usage" in msg


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_rules_dir_not_exists(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        assert load_rules(nonexistent) == []

    def test_add_multiple_same_category(self, rules_dir):
        add_rule("compliance", "Rule A", rules_dir=rules_dir)
        add_rule("compliance", "Rule B", rules_dir=rules_dir)
        rules = list_rules(category="compliance", rules_dir=rules_dir)
        assert len(rules) == 2

    def test_delete_nonexistent_from_empty(self, rules_dir):
        assert delete_rule("xyz", rules_dir=rules_dir) is False

    def test_update_nonexistent_from_empty(self, rules_dir):
        with pytest.raises(KeyError):
            update_rule("xyz", {"rule": "x"}, rules_dir=rules_dir)

    def test_state_machine_edit_nonexistent_rule(self, rules_dir):
        """Confirm gracefully when the rule_id doesn't exist at apply time."""
        s = RuleConfigSession(rules_dir=rules_dir)
        s.mode = "edit"
        s.rule_id = "ghost"
        s.category = "greeting"
        s.parameter = "tone"
        s.value = "warm"
        s.state = RuleConfigState.AWAITING_CONFIRMATION
        msg, done = s.process_input("yes")
        assert done is True
        assert "not found" in msg.lower()
