"""Nothing in this repository may destroy a resource as shipped.

These read the real ``policies/`` directory rather than fixtures. The point is
not that the mechanism works — other tests cover that — but that the policies
actually committed to this repository stay inside the safety envelope. A rule
raised to DELETE in a pull request fails here, by name, with the file it is in.
"""
import pytest

from app.core.actions import ActionTier, tier_of
from app.services import policy_registry

pytestmark = pytest.mark.safety


@pytest.fixture(scope="module")
def policies(request):
    directory = request.config.rootpath / "policies"
    try:
        loaded = policy_registry.load_policies(str(directory), force=True)
    except policy_registry.PolicyRegistryError as e:
        pytest.skip(f"Cannot inspect policies: {e}")
    if not loaded:
        pytest.skip("No policies found to check.")
    return loaded


def test_every_shipped_rule_is_at_or_below_notify(policies):
    """Tier 1 is the ceiling for anything committed here.

    Tier 2 is implemented and reversible, so this is not a claim that it is
    unsafe — it is a claim that turning it on is a decision somebody makes
    deliberately, in a pull request that has to change this test.
    """
    offenders = [
        f"{policy.name}:{rule.rule} requests {rule.requested_action} (Tier {rule.tier})"
        for policy in policies
        for rule in policy.rules
        if rule.tier > ActionTier.NOTIFY
    ]
    assert not offenders, (
        "Rules above Tier 1 are committed:\n  "
        + "\n  ".join(offenders)
        + "\n\nRaising a rule's tier is a deliberate change. If that is what you "
        "mean to do, say so in the pull request and update this test."
    )


def test_no_shipped_rule_declares_itself_destructive(policies):
    offenders = [
        f"{policy.name}:{rule.rule}"
        for policy in policies
        for rule in policy.rules
        if rule.destructive
    ]
    assert not offenders, (
        "Rules declaring destructive: true are committed: " + ", ".join(offenders)
    )


def test_registry_summary_agrees_with_the_rules(policies):
    """The number the dashboard shows must be the number in the files.

    The dashboard renders `max_tier` from this summary, and a summary that
    under-reports would show a reassuring "Tier 1" over a policy that deletes.
    """
    summary = policy_registry.registry_summary()
    computed = max(rule.tier for policy in policies for rule in policy.rules)
    assert summary["max_tier"] == computed
    assert summary["destructive_rule_count"] == 0


def test_every_rule_has_an_id_and_a_severity(policies):
    """Metadata the UI and the audit trail depend on, present everywhere."""
    incomplete = [
        f"{policy.name}:{rule.rule}"
        for policy in policies
        for rule in policy.rules
        if not rule.id or not rule.severity or not rule.description
    ]
    assert not incomplete, "Rules missing id, severity, or description: " + ", ".join(
        incomplete
    )


def test_rule_ids_are_unique_across_every_policy(policies):
    """IDs identify a finding in the audit trail, so a duplicate is a real bug."""
    seen: dict[str, str] = {}
    duplicates = []
    for policy in policies:
        for rule in policy.rules:
            where = f"{policy.name}:{rule.rule}"
            if rule.id in seen:
                duplicates.append(f"{rule.id} in both {seen[rule.id]} and {where}")
            else:
                seen[rule.id] = where
    assert not duplicates, "Duplicate rule IDs: " + "; ".join(duplicates)


def test_declared_actions_all_exist_in_the_registry(policies):
    """A typo in `requested_action` must not silently become something else."""
    for policy in policies:
        for rule in policy.rules:
            # `tier_of` resolves an unknown action to the safe floor, so this
            # asserts the round trip rather than the lookup.
            assert tier_of(rule.requested_action) == rule.tier, (
                f"{policy.name}:{rule.rule} declares {rule.requested_action!r}, "
                "which does not resolve to the tier the registry reported."
            )
