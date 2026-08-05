"""The ceiling on model-authored policy.

The prompt tells the model it may only emit Tier 0-2 actions. These tests assume
it did not listen, which is the only safe assumption to make about a prompt. The
check runs on the generated text and has no knowledge of what was asked for.
"""
import pytest

from app.agents.guardrails import (
    MAX_GENERATED_TIER,
    GuardrailViolation,
    check_generated_policy,
    inspect_generated_policy,
)
from app.core.actions import ACTIONS, ActionTier


def policy_requesting(action: str, destructive: str = "false") -> str:
    return f'''
package databricks.governance.generated

rule_metadata := {{
    "no_owner_tag": {{
        "id": "GEN-001",
        "severity": "MEDIUM",
        "requested_action": "{action}",
        "destructive": {destructive},
    }},
}}
'''


# --- The ceiling ------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    sorted(n for n, s in ACTIONS.items() if s.tier <= MAX_GENERATED_TIER),
)
def test_every_action_at_or_below_the_ceiling_is_allowed(action):
    report = check_generated_policy(policy_requesting(action))
    assert report.ok


@pytest.mark.parametrize(
    "action",
    sorted(n for n, s in ACTIONS.items() if s.tier > MAX_GENERATED_TIER),
)
def test_no_destructive_action_can_be_generated(action):
    with pytest.raises(GuardrailViolation) as exc:
        check_generated_policy(policy_requesting(action))

    assert any(action in v for v in exc.value.violations)


def test_the_ceiling_is_the_reversible_tier():
    """Tier 2 is generatable precisely because every action in it has an undo."""
    assert MAX_GENERATED_TIER == ActionTier.RESTRICT
    restrict = [s for s in ACTIONS.values() if s.tier == ActionTier.RESTRICT]
    assert restrict and all(s.undo_method for s in restrict)


def test_a_legacy_alias_cannot_smuggle_a_destructive_action_past():
    """KILL resolves to TERMINATE, so it has to be refused as one."""
    with pytest.raises(GuardrailViolation):
        check_generated_policy(policy_requesting("KILL"))


def test_declaring_destructive_is_refused_on_its_own():
    """Even paired with a harmless action. The flag is the claim that matters."""
    with pytest.raises(GuardrailViolation) as exc:
        check_generated_policy(policy_requesting("WARN", destructive="true"))

    assert any("destructive" in v for v in exc.value.violations)


def test_an_unknown_action_is_refused_rather_than_assumed_safe():
    with pytest.raises(GuardrailViolation) as exc:
        check_generated_policy(policy_requesting("OBLITERATE"))

    assert any("not a known action" in v for v in exc.value.violations)


def test_one_bad_rule_among_several_fails_the_whole_policy():
    content = policy_requesting("WARN") + policy_requesting("DELETE")
    with pytest.raises(GuardrailViolation):
        check_generated_policy(content)


def test_violations_are_reported_together():
    """One round trip through the UI, not one refusal at a time."""
    content = policy_requesting("DELETE") + policy_requesting("TERMINATE", "true")
    report = inspect_generated_policy(content)
    assert len(report.violations) >= 3


# --- Refusal, not repair ----------------------------------------------------


def test_the_refusal_explains_what_to_do_instead():
    """A generic rejection teaches nobody what the rule is."""
    try:
        check_generated_policy(policy_requesting("DELETE"))
    except GuardrailViolation as e:
        payload = e.to_dict()

    assert payload["error"] == "guardrail_violation"
    assert payload["violations"]
    assert "reviewed pull request" in payload["remedy"]


def test_a_policy_with_no_actions_at_all_passes():
    """A policy that only records findings requests nothing, which is fine."""
    report = check_generated_policy("package databricks.governance.generated\n")
    assert report.ok
    assert report.actions == []


def test_whitespace_in_the_generated_json_does_not_evade_the_scan():
    content = 'rule_metadata := {"r": {"requested_action"  :   "DELETE"}}'
    with pytest.raises(GuardrailViolation):
        check_generated_policy(content)


def test_the_report_names_the_highest_tier_requested():
    report = inspect_generated_policy(
        policy_requesting("WARN") + policy_requesting("REVOKE_ACCESS")
    )
    assert report.max_tier == int(ActionTier.RESTRICT)
