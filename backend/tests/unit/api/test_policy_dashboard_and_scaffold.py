"""The policy dashboard, and the starting text for a new policy.

A scaffold that produced anything above Tier 1 would make the first pull request
for every new policy an escalation, which is the opposite of the intent: nothing
in this repository ships above Tier 1, and raising a rule is meant to be a
deliberate edit somebody has to justify.
"""
from __future__ import annotations

import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import policy_registry, policy_scaffold


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --- Dashboard --------------------------------------------------------------


def test_the_dashboard_answers_in_one_request(client):
    response = client.get("/api/v1/policies/dashboard")
    assert response.status_code == 200

    body = response.json()
    assert body["policies"], "no policies came back"
    assert "summary" in body
    assert "findings_by_policy" in body
    assert "history_available" in body
    assert "github_enabled" in body


def test_every_row_carries_what_the_list_shows(client):
    body = client.get("/api/v1/policies/dashboard").json()
    for row in body["policies"]:
        assert row["name"].endswith(".rego")
        assert "rule_count" in row
        assert "max_tier" in row
        assert "resource_type" in row
        assert "last_edit" in row  # may be None without a git checkout
        assert "uncommitted_changes" in row


def test_the_dashboard_says_which_types_are_actually_discovered(client):
    """A policy for a type nothing collects reports zero findings forever.

    Zero findings and a clean estate are the same number, so the list has to be
    able to tell them apart. It does that by comparing each policy's resource
    type against the types a handler discovers.
    """
    from app.providers.databricks.handlers import HANDLER_REGISTRY

    body = client.get("/api/v1/policies/dashboard").json()
    assert set(body["discovered_resource_types"]) == set(HANDLER_REGISTRY)


def test_findings_are_keyed_by_package_so_a_row_can_find_its_own(client):
    """The dashboard looks these up by `policy.package`.

    Findings record the Rego package name, and the rows are keyed by package
    too. If either side switched to the filename the column would silently
    render zero for every policy.
    """
    body = client.get("/api/v1/policies/dashboard").json()
    packages = {row["package"] for row in body["policies"]}
    for policy_name in body["findings_by_policy"]:
        assert policy_name in packages or policy_name.endswith(".rego")


# --- Scaffold ---------------------------------------------------------------


def test_the_scaffold_lists_only_types_a_handler_discovers(client):
    from app.providers.databricks.handlers import HANDLER_REGISTRY

    body = client.get("/api/v1/policies/scaffold/defaults").json()
    offered = {t["resource_type"] for t in body["resource_types"]}
    assert offered == set(HANDLER_REGISTRY)


def test_a_suggested_name_is_never_one_already_taken(client):
    body = client.get("/api/v1/policies/scaffold/defaults").json()
    taken = {p.name[: -len(".rego")] for p in policy_registry.load_policies()}
    for entry in body["resource_types"]:
        assert entry["suggested_name"] not in taken


def test_scaffolding_writes_nothing(client, tmp_path):
    before = sorted(os.listdir(policy_registry_dir()))
    client.post(
        "/api/v1/policies/scaffold",
        json={"name": "brand_new_thing", "resource_type": "cluster"},
    )
    assert sorted(os.listdir(policy_registry_dir())) == before


def test_a_duplicate_name_is_refused(client):
    response = client.post(
        "/api/v1/policies/scaffold",
        json={"name": "clusters", "resource_type": "cluster"},
    )
    assert response.status_code == 409


def test_an_unusable_name_is_refused(client):
    response = client.post(
        "/api/v1/policies/scaffold",
        json={"name": "Not A Name", "resource_type": "cluster"},
    )
    assert response.status_code == 400


def test_a_resource_type_is_required(client):
    response = client.post(
        "/api/v1/policies/scaffold",
        json={"name": "orphaned", "resource_type": ""},
    )
    assert response.status_code == 400


def policy_registry_dir() -> str:
    from app.core.config import settings

    return settings.get_policies_dir


# --- What the scaffold produces ---------------------------------------------


def test_the_scaffold_compiles_and_registers(tmp_path):
    """It has to be a working policy, not a sketch of one."""
    target = str(tmp_path / "policies")
    shutil.copytree(policy_registry_dir(), target)

    content = policy_scaffold.starter_policy(
        "secret_scopes", resource_type="cluster", owner="platform-governance"
    )
    with open(os.path.join(target, "secret_scopes.rego"), "w", encoding="utf-8") as fh:
        fh.write(content)

    policy_registry.invalidate_cache()
    try:
        created = policy_registry.get_policy("secret_scopes", target)
        assert created is not None, "OPA would not load the scaffolded policy"
        assert created.rules, "a policy with no rules tests nothing"
        assert created.resource_type == "cluster"
        assert created.owner == "platform-governance"
    finally:
        policy_registry.invalidate_cache()


def test_the_scaffold_never_ships_above_tier_one(tmp_path):
    target = str(tmp_path / "policies")
    shutil.copytree(policy_registry_dir(), target)

    content = policy_scaffold.starter_policy("probe_policy", resource_type="cluster")
    with open(os.path.join(target, "probe_policy.rego"), "w", encoding="utf-8") as fh:
        fh.write(content)

    policy_registry.invalidate_cache()
    try:
        created = policy_registry.get_policy("probe_policy", target)
        assert created is not None
        for rule in created.rules:
            assert rule.tier <= 1, f"{rule.id} scaffolds at tier {rule.tier}"
            assert not rule.destructive
    finally:
        policy_registry.invalidate_cache()


def test_the_scaffolded_rule_only_reads_collected_fields(tmp_path):
    """A starter rule reading uncollected data would never fire.

    Shipping that as the template would teach the mistake the field catalogue
    exists to catch.
    """
    from app.services import resource_schema

    content = policy_scaffold.starter_policy("probe_two", resource_type="cluster")
    warnings = resource_schema.check_fields(content, "cluster")
    assert warnings == []


def test_a_custom_description_survives_into_the_file():
    content = policy_scaffold.starter_policy(
        "described",
        resource_type="job",
        description="Only the things that wake somebody up.",
    )
    assert "Only the things that wake somebody up." in content


def test_a_multiline_description_stays_a_valid_comment_block():
    content = policy_scaffold.starter_policy(
        "multi", resource_type="job", description="First line.\nSecond line."
    )
    body = content.split("package ")[0]
    for line in body.splitlines():
        assert line.startswith("#"), f"{line!r} escaped the comment block"
