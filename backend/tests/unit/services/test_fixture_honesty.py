"""A fixture must not testify about data the scanner cannot produce.

Fixtures build the policy input document directly, so nothing stops one setting
a field no handler collects. The rule then fires, the fixture passes, coverage
goes green -- and the rule is still dead against every real workspace. That is
strictly worse than having no test, because the tick gets read as evidence.

This happened here. Every cluster fixture set `idle_days`, which no handler
collects, and one of them asserted that an idleness rule fires.
"""
from __future__ import annotations

import pytest

from app.services import resource_schema, synthetic_estate


@pytest.fixture(scope="module")
def shipped():
    # Shipped only, as the name says. Including local captures would make these
    # assertions depend on whose machine is running them, and pass or fail based
    # on whether somebody had pressed Capture that morning.
    return synthetic_estate.load_fixtures(include_captures=False)


def test_there_are_fixtures_for_more_than_one_resource_type(shipped):
    types = {f.resource_type for f in shipped}
    assert len(types) > 1, (
        "Every fixture covers the same resource type, so the suite says nothing "
        "about any other handler's policies."
    )


def test_no_shipped_fixture_invents_a_field(shipped):
    offenders = {f.name: f.invented_fields for f in shipped if f.invented_fields}
    assert not offenders, (
        "These fixtures set fields no handler collects, so they prove the rule's "
        "logic while saying nothing about whether it can ever fire:\n"
        + "\n".join(f"  {name}: {fields}" for name, fields in offenders.items())
    )


def test_invented_fields_are_actually_detected():
    """The check above is only worth having if it can fail.

    `idle_hours` is the example the handler base class cites: plausible, close
    to a field that does exist, and collected by nothing. `idle_days` used to
    serve here and no longer can — the cluster handler now derives it from
    `terminated_time`, which is the whole point of this exercise.
    """
    fixture = synthetic_estate.Fixture(
        name="probe",
        resource={"type": "cluster", "id": "c-1", "idle_hours": 2160},
    )
    assert fixture.invented_fields == ["idle_hours"]


def test_a_resource_type_with_no_handler_is_not_judged():
    """`workspace` has policies but no handler, so there is no catalog to check."""
    fixture = synthetic_estate.Fixture(
        name="probe",
        resource={"type": "workspace", "id": "ws-1", "pat_enabled": True},
    )
    assert fixture.invented_fields == []
    assert "workspace" not in resource_schema.HANDLER_REGISTRY


def test_workspace_type_is_explicit_rather_than_sniffed_from_the_name():
    """Several rules are scoped to enterprise production.

    That used to depend on the workspace *name* containing "enterprise", which
    nothing told the fixture author, so a rule they expected to fire silently
    did not.
    """
    enterprise = synthetic_estate.Fixture(
        name="probe",
        resource={"type": "app", "id": "a"},
        workspace="synthetic-prod",
        workspace_type="enterprise",
    )
    assert synthetic_estate._input_for(enterprise)["workspace"]["type"] == "enterprise"

    domain = synthetic_estate.Fixture(
        name="probe",
        resource={"type": "app", "id": "a"},
        workspace="synthetic-prod",
        workspace_type="domain",
    )
    assert synthetic_estate._input_for(domain)["workspace"]["type"] == "domain"


def test_the_old_name_sniff_still_works_for_fixtures_that_relied_on_it():
    legacy = synthetic_estate.Fixture(
        name="probe",
        resource={"type": "app", "id": "a"},
        workspace="my-enterprise-ws",
    )
    assert synthetic_estate._input_for(legacy)["workspace"]["type"] == "enterprise"


def test_coverage_separates_reachable_from_merely_covered():
    report = synthetic_estate.rule_coverage()

    assert report["reachable"] <= report["covered"] <= report["total"]
    assert report["only_synthetic"] == report["covered"] - report["reachable"]
    assert report["only_synthetic"] == 0, (
        "Some rule's only firing fixture invents data, so it is counted as "
        f"working when it is not: {report['fixtures_inventing_fields']}"
    )


def test_every_covered_rule_names_the_fixtures_that_cover_it():
    report = synthetic_estate.rule_coverage()
    for rule in report["rules"]:
        if rule["covered"]:
            assert rule["fires_in"], rule["rule_id"]
