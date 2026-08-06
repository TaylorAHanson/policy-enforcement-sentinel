"""Testing the policy in the editor rather than the one on disk.

The whole point of running a test from the editor is to find out whether the
change in front of you works. Evaluating the committed file instead answers a
question nobody asked, and answers it with a green tick, which is worse than
not answering it at all.
"""
import asyncio
import json
import os
import shutil
import subprocess

import pytest

from app.services import synthetic_estate

CLUSTER = {
    "id": "0101-draft",
    "type": "cluster",
    "name": "draft-test",
    "owner": "someone@company.com",
    "cluster_type": "interactive",
    "access_mode": "USER_ISOLATION",
    "policy_id": "policy-1",
    "autotermination_minutes": 30,
    "idle_days": 1,
    "tags": {"cost-center": "CC-1", "owner": "someone@company.com"},
}


@pytest.fixture
def opa_available():
    if shutil.which("opa") is None:
        pytest.skip("The opa binary is not installed.")


def write(directory, name, payload):
    payload.setdefault("workspace", "synthetic-prod")
    payload.setdefault("environment", "prod")
    with open(os.path.join(directory, f"{name}.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def run(directory, **kwargs):
    return asyncio.run(synthetic_estate.run_all(str(directory), **kwargs))


DRAFT = """\
package databricks.governance.draft_probe

import data.databricks.governance.common
import rego.v1

# METADATA
# custom:
#   resource_type: cluster
applies if input.resource.type == "cluster"

rule_metadata := {"draft_only": {
	"id": "DRAFT-001",
	"category": "cost",
	"description": "Exists only in the draft.",
	"severity": "LOW",
	"requested_action": "WARN",
	"destructive": false,
}}

violations.draft_only contains msg if {
	applies
	msg := "This rule exists only in the draft."
}

rule_results := common.results(rule_metadata, violations) if applies
"""


def test_a_draft_rule_fires_without_being_committed(tmp_path, opa_available):
    """The rule is in no file on disk. If the run sees it, the draft is what
    was evaluated."""
    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {"fires": ["DRAFT-001"]}})

    result = run(
        tmp_path,
        draft=synthetic_estate.Draft("draft_probe.rego", DRAFT),
    )

    assert result["passed"] == 1, result["results"]
    assert result["tested_draft"] is True


def test_without_a_draft_the_same_fixture_fails(tmp_path, opa_available):
    """The other half of the proof: the rule genuinely is not on disk, so this
    is not a fixture that would have passed either way."""
    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {"fires": ["DRAFT-001"]}})

    result = run(tmp_path)

    assert result["failed"] == 1
    # `missing` rather than `not_evaluated`: the fixture expected it to fire and
    # it did not. `not_evaluated` is the equivalent for a rule expected to pass.
    assert result["results"][0]["missing"] == ["DRAFT-001"]
    assert result["tested_draft"] is False


def test_a_draft_is_evaluated_alongside_the_committed_policies(tmp_path, opa_available):
    """A draft replaces one file, not the whole directory. The shared library
    has to still be there or nothing compiles, and the neighbouring policies
    have to still run or a fixture's other expectations break."""
    untagged = {**CLUSTER, "tags": {}}
    write(
        tmp_path,
        "cluster",
        {"resource": untagged, "expect": {"fires": ["DRAFT-001", "CST-CLU-003"]}},
    )

    result = run(
        tmp_path,
        draft=synthetic_estate.Draft("draft_probe.rego", DRAFT),
    )

    assert result["passed"] == 1, result["results"]


def test_a_draft_that_does_not_compile_is_reported_not_ignored(tmp_path, opa_available):
    """Silently falling back to the committed file would show a green run for a
    draft that cannot even parse."""
    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {"passes": ["SEC-CLU-001"]}})

    result = run(
        tmp_path,
        draft=synthetic_estate.Draft("broken.rego", "package x\nthis is not rego {{{"),
    )

    assert result["failed"] == 1
    assert result["results"][0]["error"]


def test_the_draft_does_not_touch_the_policies_directory(tmp_path, opa_available):
    """Evaluation copies the directory rather than writing into it. If it wrote
    in place, testing a draft would change what a live scan evaluates."""
    policies = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        "policies",
    )
    before = sorted(os.listdir(policies))
    clusters = open(os.path.join(policies, "clusters.rego"), encoding="utf-8").read()

    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {}})
    run(
        tmp_path,
        draft=synthetic_estate.Draft("clusters.rego", DRAFT.replace("draft_probe", "clusters")),
    )

    assert sorted(os.listdir(policies)) == before
    assert open(os.path.join(policies, "clusters.rego"), encoding="utf-8").read() == clusters


def test_git_sees_no_change_after_testing_a_draft(tmp_path, opa_available):
    """The same guarantee, asked of git rather than of the filesystem. A draft
    that leaked onto disk would show up here as an uncommitted change to a
    policy nobody edited."""
    repo = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "policies/"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    before = status.stdout

    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {}})
    run(tmp_path, draft=synthetic_estate.Draft("clusters.rego", DRAFT))

    after = subprocess.run(
        ["git", "status", "--porcelain", "policies/"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert after.stdout == before


# --- Filtering ---------------------------------------------------------------


def test_a_resource_type_filter_only_runs_matching_fixtures(tmp_path, opa_available):
    """How the editor scopes a run to the policy that is open."""
    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {}})
    write(
        tmp_path,
        "job",
        {"resource": {"id": "j-1", "type": "job", "name": "nightly"}, "expect": {}},
    )

    both = run(tmp_path)
    clusters_only = run(tmp_path, resource_type="cluster")

    assert both["total"] == 2
    assert clusters_only["total"] == 1
    assert clusters_only["results"][0]["resource_type"] == "cluster"


def test_filtering_to_a_type_with_no_fixtures_is_not_a_pass(tmp_path, opa_available):
    """The editor shows this when a policy's resource type has no fixtures, and
    it has to read as "nothing was checked" rather than "all good"."""
    write(tmp_path, "cluster", {"resource": CLUSTER, "expect": {}})

    result = run(tmp_path, resource_type="lakebase_instance")

    assert result["total"] == 0
    assert result["ok"] is False
