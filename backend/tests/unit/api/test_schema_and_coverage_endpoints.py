"""The endpoints behind the field catalogue and the coverage numbers.

Both exist to answer the same question from two directions: is this rule
actually capable of doing anything? A rule that reads data nobody collects
cannot, and a rule no fixture exercises has never been shown to.
"""
from __future__ import annotations


# --- /policies/schema --------------------------------------------------------


def test_the_catalogue_lists_every_resource_type(client):
    response = client.get("/api/v1/policies/schema")

    assert response.status_code == 200
    body = response.json()
    types = {t["resource_type"] for t in body["resource_types"]}
    assert "cluster" in types
    assert "app" in types


def test_every_type_declares_fields(client):
    body = client.get("/api/v1/policies/schema").json()

    undeclared = [t["resource_type"] for t in body["resource_types"] if not t["declared"]]
    assert undeclared == []


def test_one_type_can_be_asked_for_directly(client):
    response = client.get("/api/v1/policies/schema", params={"resource_type": "cluster"})

    assert response.status_code == 200
    fields = {f["name"] for f in response.json()["fields"]}
    assert "policy_id" in fields
    assert "autotermination_minutes" in fields


def test_an_unknown_type_is_a_404_not_an_empty_list(client):
    """An empty field list reads as "this type has no fields", which would send
    someone off to write a policy with nothing to test."""
    response = client.get("/api/v1/policies/schema", params={"resource_type": "nope"})

    assert response.status_code == 404


def test_apps_do_not_claim_to_have_activity_data(client):
    """The case that prompted all of this: an idleness rule for apps cannot be
    written, because nothing collects when an app was last used."""
    fields = {
        f["name"]
        for f in client.get(
            "/api/v1/policies/schema", params={"resource_type": "app"}
        ).json()["fields"]
    }

    assert "idle_days" not in fields
    assert "last_activity" not in fields


# --- /policies/validate ------------------------------------------------------


VALID_BUT_INERT = """\
package databricks.governance.probe

import rego.v1

# METADATA
# custom:
#   resource_type: cluster
applies if input.resource.type == "cluster"

violations.stale contains msg if {
	applies
	input.resource.hours_since_last_use > 24
	msg := "stale"
}
"""


def test_validate_reports_a_field_nothing_collects(client):
    response = client.post(
        "/api/v1/policies/validate",
        json={"policy_name": "probe.rego", "content": VALID_BUT_INERT},
    )

    assert response.status_code == 200
    body = response.json()
    warnings = body.get("warnings") or []
    assert [w["field"] for w in warnings] == ["hours_since_last_use"]


def test_a_field_warning_is_not_an_error(client):
    """It has to stay separate. The policy compiles, and blocking on this would
    stop someone saving a file whose annotation is simply out of date."""
    body = client.post(
        "/api/v1/policies/validate",
        json={"policy_name": "probe.rego", "content": VALID_BUT_INERT},
    ).json()

    assert body["errors"] == [] or body["valid"] is True
    assert "warnings" in body


def test_a_policy_using_only_collected_fields_warns_about_nothing(client):
    content = VALID_BUT_INERT.replace(
        "input.resource.hours_since_last_use > 24",
        'input.resource.access_mode == "SINGLE_USER"',
    )

    body = client.post(
        "/api/v1/policies/validate",
        json={"policy_name": "probe.rego", "content": content},
    ).json()

    assert (body.get("warnings") or []) == []


# --- /testing/coverage -------------------------------------------------------


def test_coverage_reports_rules_with_no_fixture(client):
    response = client.get("/api/v1/testing/coverage")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert body["covered"] + body["uncovered"] == body["total"]


def test_coverage_can_be_scoped_to_one_policy(client):
    body = client.get(
        "/api/v1/testing/coverage", params={"policy": "clusters.rego"}
    ).json()

    assert {r["policy"] for r in body["rules"]} == {"clusters.rego"}


# --- /testing/synthetic, draft mode -----------------------------------------


def test_a_draft_name_without_content_is_refused(client):
    """Treating a missing body as "no draft" would evaluate the committed file
    and report a pass for a change that was never tested."""
    response = client.post(
        "/api/v1/testing/synthetic", json={"draft_policy": "clusters.rego"}
    )

    assert response.status_code == 400
    assert "draft_content" in response.json()["detail"]


def test_draft_content_without_a_name_is_refused(client):
    response = client.post(
        "/api/v1/testing/synthetic", json={"draft_content": "package x"}
    )

    assert response.status_code == 400


def test_a_plain_run_is_not_marked_as_having_tested_a_draft(client):
    body = client.post("/api/v1/testing/synthetic", json={}).json()

    assert body["tested_draft"] is False
