"""Which rules any fixture actually exercises.

A rule with no fixture is not a passing rule, it is an untested one, and on a
green results page the two are indistinguishable. Coverage is read from the
policy registry rather than from the fixtures for exactly that reason: the
interesting set is the rules that appear in no fixture, and those cannot be
counted by looking at fixtures.
"""
import json
import os

import pytest

from app.services import synthetic_estate


def write(directory, name, resource_type, fires=(), passes=()):
    payload = {
        "workspace": "synthetic",
        "environment": "prod",
        "resource": {"id": name, "type": resource_type, "name": name},
        "expect": {"fires": list(fires), "passes": list(passes)},
    }
    with open(os.path.join(directory, f"{name}.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_a_rule_no_fixture_mentions_is_reported_uncovered(tmp_path):
    write(tmp_path, "one", "cluster", fires=["SEC-CLU-001"])

    report = synthetic_estate.rule_coverage(
        resource_type="cluster", directory=str(tmp_path)
    )
    by_id = {r["rule_id"]: r for r in report["rules"]}

    assert by_id["SEC-CLU-001"]["covered"] is True
    assert by_id["CST-CLU-003"]["covered"] is False
    assert report["uncovered"] >= 1


def test_firing_somewhere_is_not_the_same_as_being_tested_both_ways(tmp_path):
    """A rule only ever seen firing has never been shown to leave a compliant
    resource alone, which is how a rule that is too broad survives."""
    write(tmp_path, "one", "cluster", fires=["SEC-CLU-001"])

    report = synthetic_estate.rule_coverage(
        resource_type="cluster", directory=str(tmp_path)
    )
    rule = next(r for r in report["rules"] if r["rule_id"] == "SEC-CLU-001")

    assert rule["covered"] is True
    assert rule["has_negative_case"] is False


def test_a_rule_covered_in_both_directions(tmp_path):
    write(tmp_path, "fires", "cluster", fires=["SEC-CLU-001"])
    write(tmp_path, "passes", "cluster", passes=["SEC-CLU-001"])

    report = synthetic_estate.rule_coverage(
        resource_type="cluster", directory=str(tmp_path)
    )
    rule = next(r for r in report["rules"] if r["rule_id"] == "SEC-CLU-001")

    assert rule["covered"] and rule["has_negative_case"]
    assert rule["fires_in"] == ["fires"]
    assert rule["passes_in"] == ["passes"]


def test_fixtures_for_another_type_do_not_count(tmp_path):
    """Scoping by resource type is what makes the number meaningful in the
    editor: a job fixture says nothing about a cluster rule."""
    write(tmp_path, "job", "job", fires=["SEC-CLU-001"])

    report = synthetic_estate.rule_coverage(
        resource_type="cluster", directory=str(tmp_path)
    )

    assert report["fixture_count"] == 0
    assert report["covered"] == 0


def test_scoping_to_one_policy_reports_only_its_rules(tmp_path):
    report = synthetic_estate.rule_coverage(
        policy_name="clusters.rego", directory=str(tmp_path)
    )

    assert report["total"] > 0
    assert {r["policy"] for r in report["rules"]} == {"clusters.rego"}


def test_an_empty_fixture_directory_leaves_everything_uncovered(tmp_path):
    report = synthetic_estate.rule_coverage(
        resource_type="cluster", directory=str(tmp_path)
    )

    assert report["covered"] == 0
    assert report["uncovered"] == report["total"] > 0


def test_most_rules_are_now_shown_working():
    """A measurement, not a gate.

    This started at 5 of 64 covered, and asserted that the uncovered rules
    outnumbered the covered ones — which was the honest reading at the time.
    It is now the other way round, and the assertion is inverted to keep the
    ratchet pointing the same direction: a change that drops coverage back
    below half shows up in a diff rather than in a quiet green dashboard.

    The rules still uncovered are, with one exception, not coverable: they read
    data the scanner is not permitted to see or that Databricks does not
    publish. See `rule_diagnosis` for which is which.
    """
    report = synthetic_estate.rule_coverage()

    assert report["total"] > 50
    assert report["covered"] > report["uncovered"]
