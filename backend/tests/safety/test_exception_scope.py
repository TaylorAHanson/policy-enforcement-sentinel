"""What an exception is allowed to waive.

These run the real ``opa`` binary against the real ``policies/common.rego``. The
matching logic lives in Rego, so testing a Python reimplementation of it would
prove nothing about what happens during a scan.

The property under test, stated once:

    **An exception with an empty selector matches nothing.**

A pattern exception is the only thing in this system that can suppress findings
on resources that do not exist yet. If a blank ``resource_type`` or ``rule_id``
were read as "any", one half-filled form would silently waive every rule on
every resource in a workspace — and a suppressed finding is indistinguishable
from a resource that passed, so nobody would find out from the dashboard.

The probe policy below has two failing rules on purpose. One rule waived and the
other still failing is the whole point of rule-scoping; a test with a single
rule cannot tell "waived this rule" from "waived everything".
"""
from __future__ import annotations

import asyncio
import shutil

import pytest

from app.providers.opa.client import OpaProvider

pytestmark = pytest.mark.safety

PROBE_NAME = "_exception_probe.rego"
PROBE_QUERY = "data.databricks.governance.exception_probe.rule_results"

PROBE_POLICY = """
package databricks.governance.exception_probe

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"first": {
		"id": "PRB-001",
		"category": "control",
		"description": "Always fails, so an exception has something to waive.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"second": {
		"id": "PRB-002",
		"category": "control",
		"description": "Also always fails, so rule-scoping is observable.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
}

violations.first contains "the first rule failed"

violations.second contains "the second rule failed"

rule_results := common.results(rule_metadata, violations)
"""


@pytest.fixture(scope="module")
def opa(request):
    if shutil.which("opa") is None:
        pytest.skip("The opa binary is not installed.")

    directory = request.config.rootpath / "policies"
    if not directory.exists():
        pytest.skip("No policies directory to evaluate against.")

    return OpaProvider({"policies_dir": str(directory)})


def evaluate(opa: OpaProvider, exceptions: list, *, resource_type: str = "cluster") -> dict:
    """Run the probe and return ``{rule_id: requested_action}``.

    ``SKIPPED_ALLOWLIST`` in that map means the rule was waived; ``WARN`` means
    it still fired.
    """
    payload = {
        "resource": {"id": "cluster-abc", "type": resource_type},
        "workspace": {"name": "prod-analytics"},
        "allowlist_records": exceptions,
        # Well before any expiry used here, so nothing expires mid-test.
        "request_time": 0,
    }

    results = asyncio.run(
        opa.evaluate_content(PROBE_NAME, PROBE_POLICY, PROBE_QUERY, payload)
    )
    return {row["id"]: row["requested_action"] for row in results}


def pattern(**overrides) -> dict:
    row = {
        "id": "exc-1",
        "match_type": "pattern",
        "resource_type": "cluster",
        "rule_id": "PRB-001",
        "status": "approved",
        "justification": "Agreed with the platform team.",
        "expires_at": 99999999999999999999,
    }
    row.update(overrides)
    return row


def resource_exception(**overrides) -> dict:
    row = {
        "id": "exc-1",
        "match_type": "resource",
        "resource_id": "cluster-abc",
        "resource_type": "cluster",
        "status": "approved",
        "justification": "Agreed with the platform team.",
        "expires_at": 99999999999999999999,
    }
    row.update(overrides)
    return row


# --- The baseline -----------------------------------------------------------


def test_with_no_exceptions_both_rules_fire(opa):
    """If this fails, nothing below means anything."""
    assert evaluate(opa, []) == {"PRB-001": "WARN", "PRB-002": "WARN"}


# --- Empty selectors match nothing ------------------------------------------


@pytest.mark.parametrize(
    "description, row",
    [
        ("a blank resource type", pattern(resource_type="")),
        ("a missing resource type", pattern(resource_type=None)),
        ("a blank rule id", pattern(rule_id="")),
        ("a missing rule id", pattern(rule_id=None)),
        ("both blank", pattern(resource_type="", rule_id="")),
        ("a null resource type", pattern(resource_type=None, rule_id="PRB-001")),
    ],
)
def test_a_pattern_with_an_empty_selector_waives_nothing(opa, description, row):
    """Empty is an absence of intent, never a wildcard.

    This is the single most important assertion in this file. Every other
    safety property in the system assumes that a half-specified rule fails
    closed.
    """
    assert evaluate(opa, [row]) == {
        "PRB-001": "WARN",
        "PRB-002": "WARN",
    }, f"A pattern with {description} suppressed a finding."


def test_a_pattern_missing_both_keys_entirely_waives_nothing(opa):
    """Not "set to empty" but "the key is not there at all"."""
    row = {
        "id": "exc-1",
        "match_type": "pattern",
        "status": "approved",
        "justification": "Malformed.",
        "expires_at": 99999999999999999999,
    }

    assert evaluate(opa, [row]) == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_a_resource_row_with_a_blank_resource_id_waives_nothing(opa):
    """The same rule applies to the older shape.

    A resource whose own ID is blank must not be matched by an exception whose
    resource_id is also blank — two absences are not a match.
    """
    row = resource_exception(resource_id="")

    assert evaluate(opa, [row]) == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_a_resource_row_with_a_null_resource_id_waives_nothing(opa):
    """Pattern rows store null here, so this shape reaches Rego routinely."""
    row = resource_exception(resource_id=None)

    assert evaluate(opa, [row]) == {"PRB-001": "WARN", "PRB-002": "WARN"}


# --- A pattern waives exactly one rule --------------------------------------


def test_a_pattern_waives_its_rule_and_only_its_rule(opa):
    result = evaluate(opa, [pattern(rule_id="PRB-001")])

    assert result["PRB-001"] == "SKIPPED_ALLOWLIST"
    assert result["PRB-002"] == "WARN"


def test_the_other_rule_can_be_waived_independently(opa):
    result = evaluate(opa, [pattern(rule_id="PRB-002")])

    assert result["PRB-001"] == "WARN"
    assert result["PRB-002"] == "SKIPPED_ALLOWLIST"


def test_a_pattern_for_a_different_resource_type_does_not_apply(opa):
    result = evaluate(opa, [pattern(resource_type="job")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_a_pattern_for_an_unknown_rule_id_does_not_apply(opa):
    result = evaluate(opa, [pattern(rule_id="PRB-999")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_a_pattern_matches_by_public_id_not_rule_name(opa):
    """The exception form offers CST-CLU-005, not the rule's name in the file."""
    result = evaluate(opa, [pattern(rule_id="first")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_a_resource_with_no_type_cannot_be_pattern_waived(opa):
    """Symmetrical to a blank selector: the other side has to be real too."""
    result = evaluate(opa, [pattern(resource_type="cluster")], resource_type="")

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


# --- The older shape still behaves exactly as it did ------------------------


def test_a_resource_exception_still_waives_every_failing_rule(opa):
    """Unchanged behaviour, and the reason match_type defaults to "resource"."""
    result = evaluate(opa, [resource_exception()])

    assert result == {
        "PRB-001": "SKIPPED_ALLOWLIST",
        "PRB-002": "SKIPPED_ALLOWLIST",
    }


def test_a_row_with_no_match_type_is_treated_as_a_resource_exception(opa):
    """Every row written before patterns existed looks like this.

    Reading a missing match_type as a pattern would be the worse failure — it
    would reinterpret historical single-resource waivers as class-wide ones.
    """
    row = resource_exception()
    del row["match_type"]

    result = evaluate(opa, [row])

    assert result == {
        "PRB-001": "SKIPPED_ALLOWLIST",
        "PRB-002": "SKIPPED_ALLOWLIST",
    }


def test_a_resource_exception_for_another_resource_does_not_apply(opa):
    result = evaluate(opa, [resource_exception(resource_id="cluster-xyz")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_an_unrecognised_match_type_waives_nothing(opa):
    """A value nobody implemented is not a licence to match."""
    result = evaluate(opa, [resource_exception(match_type="everything")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


# --- Status and expiry still gate patterns ----------------------------------


def test_a_pending_pattern_holds_the_finding_rather_than_waiving_it(opa):
    result = evaluate(opa, [pattern(status="pending")])

    assert result["PRB-001"] == "PENDING_EXCEPTION"
    assert result["PRB-002"] == "WARN"


def test_a_rejected_pattern_waives_nothing(opa):
    result = evaluate(opa, [pattern(status="rejected")])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


def test_an_expired_pattern_waives_nothing(opa):
    """`request_time` is 0, so any positive expiry is already in the past."""
    result = evaluate(opa, [pattern(expires_at=-1)])

    assert result == {"PRB-001": "WARN", "PRB-002": "WARN"}


# --- Combinations -----------------------------------------------------------


def test_two_patterns_can_waive_both_rules(opa):
    result = evaluate(
        opa,
        [
            pattern(id="exc-1", rule_id="PRB-001"),
            pattern(id="exc-2", rule_id="PRB-002"),
        ],
    )

    assert result == {
        "PRB-001": "SKIPPED_ALLOWLIST",
        "PRB-002": "SKIPPED_ALLOWLIST",
    }


def test_a_malformed_pattern_alongside_a_valid_one_changes_nothing(opa):
    """One bad row must not widen a good one, nor break evaluation."""
    result = evaluate(
        opa,
        [
            pattern(id="exc-1", rule_id="PRB-001"),
            pattern(id="exc-2", resource_type="", rule_id=""),
        ],
    )

    assert result == {"PRB-001": "SKIPPED_ALLOWLIST", "PRB-002": "WARN"}
