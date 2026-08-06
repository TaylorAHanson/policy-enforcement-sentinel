"""Renaming a policy must not orphan what references it.

Allowlist exceptions, saved filters and stored findings name a policy by its
package. A rename that only moves the file leaves all of them pointing at
nothing — and silently, because an exception matching nothing simply stops
suppressing, which reads as the rule getting stricter rather than as a break.
"""
from __future__ import annotations

import os

import pytest

from app.services import policy_registry, policy_rename


def policies_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", "..", "policies")


@pytest.fixture(scope="module")
def apps_policy() -> str:
    with open(os.path.join(policies_dir(), "apps.rego"), encoding="utf-8") as fh:
        return fh.read()


# --- Names ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["clusters", "sql_warehouses", "a", "x1", "genie_spaces", "clusters.rego"]
)
def test_usable_names_are_accepted(name):
    assert policy_rename.validate_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "Clusters",  # a Rego package is lowercase
        "my-policy",  # a hyphen is subtraction in Rego
        "9lives",  # cannot start with a digit
        "with space",
        "../escape",
        "trailing.dot",
        "a" * 65,
    ],
)
def test_unusable_names_are_refused(name):
    with pytest.raises(policy_rename.RenameError):
        policy_rename.validate_name(name)


def test_the_error_explains_what_a_name_is_for():
    """A name is a filename and a Rego package at once, which is not obvious."""
    with pytest.raises(policy_rename.RenameError) as excinfo:
        policy_rename.validate_name("My Policy")
    message = str(excinfo.value)
    assert "package" in message and "lowercase" in message


# --- Rewriting --------------------------------------------------------------


def test_the_package_declaration_moves_with_the_file(apps_policy):
    """OPA resolves rules by package, not by filename.

    Renaming the file alone would leave the policy loaded under its old package,
    so the new name would exist on disk and nowhere else.
    """
    result = policy_rename.rename(apps_policy, "apps.rego", "databricks_apps")

    assert result.new_name == "databricks_apps.rego"
    assert result.new_package == "databricks.governance.databricks_apps"
    assert "package databricks.governance.databricks_apps" in result.content
    assert "package databricks.governance.apps\n" not in result.content


def test_the_package_prefix_is_preserved(apps_policy):
    result = policy_rename.rename(apps_policy, "apps.rego", "renamed")
    assert result.new_package.startswith("databricks.governance.")


def test_the_old_name_is_recorded(apps_policy):
    result = policy_rename.rename(apps_policy, "apps.rego", "databricks_apps")
    assert "replaces: [apps]" in result.content


def test_a_second_rename_keeps_the_first_redirect(apps_policy):
    """A policy renamed twice has to redirect from both of its old names.

    Dropping the first would break every exception written before the first
    rename, at the moment the second one merged.
    """
    once = policy_rename.rename(apps_policy, "apps.rego", "step_one")
    twice = policy_rename.rename(once.content, "step_one", "step_two")

    assert "replaces: [apps, step_one]" in twice.content


def test_renaming_to_the_same_name_is_refused(apps_policy):
    with pytest.raises(policy_rename.RenameError):
        policy_rename.rename(apps_policy, "apps.rego", "apps")


def test_a_file_with_no_package_is_refused():
    with pytest.raises(policy_rename.RenameError):
        policy_rename.rename("# just a comment\n", "x.rego", "y")


def test_a_policy_with_no_custom_block_is_refused():
    """Without somewhere to record the old name, the rename is unsafe.

    Refusing is the point: silently skipping the alias would produce exactly the
    broken references this module exists to prevent.
    """
    content = "# METADATA\n# title: Bare\npackage databricks.governance.bare\n"
    with pytest.raises(policy_rename.RenameError) as excinfo:
        policy_rename.rename(content, "bare.rego", "renamed")
    assert "custom" in str(excinfo.value)


def test_the_rules_are_untouched(apps_policy):
    """Rule IDs are referenced independently and must survive a rename."""
    result = policy_rename.rename(apps_policy, "apps.rego", "renamed")
    for rule_id in ("CST-APP-003", "CST-APP-004", "SEC-APP-001", "SEC-APP-002"):
        assert rule_id in result.content


# --- Against the real registry ----------------------------------------------


def test_a_renamed_policy_still_parses_and_redirects(tmp_path, apps_policy):
    """End to end: OPA loads it, and the old name still resolves to it."""
    import shutil

    target = str(tmp_path / "policies")
    shutil.copytree(policies_dir(), target)

    result = policy_rename.rename(apps_policy, "apps.rego", "databricks_apps")
    os.remove(os.path.join(target, "apps.rego"))
    with open(os.path.join(target, result.new_name), "w", encoding="utf-8") as fh:
        fh.write(result.content)

    policy_registry.invalidate_cache()
    try:
        renamed = policy_registry.get_policy("databricks_apps", target)
        assert renamed is not None
        assert renamed.replaces == ["apps"]
        assert len(renamed.rules) == 4

        # The whole point: the retired spelling still finds the policy.
        by_old_name = policy_registry.get_policy("apps", target)
        assert by_old_name is not None
        assert by_old_name.package == "databricks_apps"
    finally:
        policy_registry.invalidate_cache()


def test_a_live_policy_is_not_shadowed_by_an_alias(tmp_path, apps_policy):
    """If a new policy takes a retired name, the real one wins.

    Otherwise creating `apps.rego` after renaming the old one away would open
    the renamed policy instead of the new file.
    """
    import shutil

    target = str(tmp_path / "policies")
    shutil.copytree(policies_dir(), target)

    result = policy_rename.rename(apps_policy, "apps.rego", "databricks_apps")
    with open(os.path.join(target, result.new_name), "w", encoding="utf-8") as fh:
        fh.write(result.content)
    # apps.rego is deliberately left in place, so `apps` is both a live policy
    # and something databricks_apps claims to replace.

    policy_registry.invalidate_cache()
    try:
        found = policy_registry.get_policy("apps", target)
        assert found is not None
        assert found.package == "apps"
    finally:
        policy_registry.invalidate_cache()
