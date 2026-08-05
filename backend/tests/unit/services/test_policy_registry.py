"""The registry, against the real policy directory and against broken input.

Two halves. The first reads the committed policies, because a registry that
parses a fixture correctly and the real files incorrectly is useless. The second
feeds it malformed metadata, because the editor is where somebody goes to fix a
broken policy and it has to render one.
"""
import pytest

from app.core.actions import SAFE_FALLBACK_ACTION
from app.services import policy_registry


@pytest.fixture(autouse=True)
def clean_cache():
    policy_registry.invalidate_cache()
    yield
    policy_registry.invalidate_cache()


@pytest.fixture
def policies(policies_dir, opa_binary):
    loaded = policy_registry.load_policies(str(policies_dir), force=True)
    if not loaded:
        pytest.skip("No policies to inspect.")
    return loaded


def test_reads_package_annotations(policies):
    """Owner, domain, and resource type come from the METADATA block."""
    clusters = next((p for p in policies if p.package == "clusters"), None)
    assert clusters is not None, "clusters.rego did not appear in the registry"
    assert clusters.title
    assert clusters.owner
    assert clusters.resource_type == "cluster"
    assert clusters.rules


def test_library_packages_are_not_listed_as_policies(policies):
    """`common` is a library. Listing it would offer an empty policy in the UI."""
    assert all(p.package != "common" for p in policies)


def test_lookup_accepts_a_file_name_or_a_package_name(policies):
    assert policy_registry.get_policy("clusters") is not None
    assert policy_registry.get_policy("clusters.rego") is not None
    assert policy_registry.get_policy("no-such-policy") is None


def test_every_retired_policy_name_still_resolves(policies):
    """Allowlist entries and saved filters still name the old thematic files."""
    from app.providers.opa.legacy_names import LEGACY_POLICY_PACKAGES

    orphaned = [
        legacy
        for legacy in LEGACY_POLICY_PACKAGES
        if policy_registry.get_policy(legacy) is None
    ]
    assert not orphaned, (
        "These retired names no longer resolve, so stored references to them are "
        "orphaned: " + ", ".join(orphaned)
    )


def test_a_fully_qualified_package_name_resolves(policies):
    """Findings store the full package path; the editor looks up the short one."""
    assert policy_registry.get_policy("databricks.governance.clusters") is not None


def test_the_cache_is_dropped_when_invalidated(policies_dir, opa_binary):
    first = policy_registry.load_policies(str(policies_dir))
    second = policy_registry.load_policies(str(policies_dir))
    assert first is second, "the cache did not return the same object"

    policy_registry.invalidate_cache()
    third = policy_registry.load_policies(str(policies_dir))
    assert third is not first


def test_a_missing_directory_yields_nothing_rather_than_raising(tmp_path):
    assert policy_registry.load_policies(str(tmp_path / "nope")) == []


# --- Malformed metadata -----------------------------------------------------


@pytest.mark.parametrize(
    "meta",
    [
        None,
        "a string",
        42,
        {},
        {"requested_action": "OBLITERATE"},
        {"requested_action": None},
        {"severity": 7, "escalate_after_days": "soon"},
    ],
)
def test_a_broken_rule_still_produces_a_descriptor(meta):
    """The editor has to render a broken policy — that is where it gets fixed."""
    descriptor = policy_registry._rule_descriptor("some_rule", meta)
    assert descriptor.rule == "some_rule"
    assert descriptor.severity
    assert descriptor.category


def test_an_unknown_action_falls_back_to_warn():
    descriptor = policy_registry._rule_descriptor(
        "r", {"requested_action": "OBLITERATE"}
    )
    assert descriptor.requested_action == SAFE_FALLBACK_ACTION


def test_a_non_integer_escalation_window_does_not_raise():
    descriptor = policy_registry._rule_descriptor("r", {"escalate_after_days": "later"})
    assert descriptor.escalate_after_days == 0
