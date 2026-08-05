"""The endpoints the dashboard is built on.

Pagination is the point of most of these. The previous shape returned every
finding for a run in a single blob, which is fine for a demo estate and fails on
a real one — so the assertions are about totals staying honest while pages stay
bounded, and about filters composing rather than replacing each other.
"""
import pytest

from tests.factories import SentinelFindingFactory, SentinelRunFactory


@pytest.fixture
def run(db_session):
    return SentinelRunFactory.create(db_session)


@pytest.fixture
def populated_run(db_session, run):
    SentinelFindingFactory.create_many(db_session, run.id, 30, severity="HIGH")
    SentinelFindingFactory.create_many(db_session, run.id, 20, severity="LOW")
    SentinelFindingFactory.create_many(
        db_session, run.id, 15, kind="check", severity=None
    )
    SentinelFindingFactory.downgraded(db_session, run.id)
    return run


@pytest.fixture
def mixed_run(db_session, run):
    """Two categories, each with violations and passing checks.

    Its own fixture because the counts here are the subject of the assertions,
    rather than incidental to them as in ``populated_run``.
    """
    SentinelFindingFactory.create_many(
        db_session, run.id, 20, severity="HIGH", category="reliability"
    )
    SentinelFindingFactory.create_many(
        db_session, run.id, 30, kind="check", severity=None, category="reliability"
    )
    SentinelFindingFactory.create_many(
        db_session, run.id, 12, severity="LOW", category="security"
    )
    SentinelFindingFactory.create_many(
        db_session, run.id, 8, kind="check", severity=None, category="security"
    )
    return run


# --- Runs -------------------------------------------------------------------


def test_the_run_list_paginates(client, db_session):
    for i in range(10):
        SentinelRunFactory.create(db_session, workspace=f"ws-{i}")

    body = client.get("/api/v1/sentinel/runs?limit=4").json()

    assert body["total"] == 10
    assert len(body["runs"]) == 4
    assert body["limit"] == 4


def test_the_run_list_omits_the_results_blob_by_default(client, run):
    """It is the largest column and the list view never renders it."""
    body = client.get("/api/v1/sentinel/runs").json()
    assert "results" not in body["runs"][0]

    detailed = client.get(f"/api/v1/sentinel/runs/{run.id}").json()
    assert "results" in detailed


def test_runs_can_be_filtered_by_status(client, db_session):
    SentinelRunFactory.create(db_session, status="completed")
    SentinelRunFactory.create(db_session, status="failed")

    body = client.get("/api/v1/sentinel/runs?status=failed").json()

    assert body["total"] == 1
    assert body["runs"][0]["status"] == "failed"


def test_run_search_is_case_insensitive(client, db_session):
    SentinelRunFactory.create(db_session, workspace="Prod-Analytics")

    body = client.get("/api/v1/sentinel/runs?search=prod-analytics").json()
    assert body["total"] == 1


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/v1/sentinel/runs/nope").status_code == 404


# --- Findings ---------------------------------------------------------------


def test_findings_paginate_without_distorting_the_total(client, populated_run):
    """The header count must reflect the filter, not the page."""
    body = client.get(
        f"/api/v1/sentinel/runs/{populated_run.id}/findings?limit=10"
    ).json()

    assert body["total"] == 66
    assert len(body["findings"]) == 10


def test_paging_covers_every_finding_exactly_once(client, populated_run):
    seen = []
    skip = 0
    while True:
        page = client.get(
            f"/api/v1/sentinel/runs/{populated_run.id}/findings?skip={skip}&limit=25"
        ).json()
        seen.extend(f["id"] for f in page["findings"])
        skip += 25
        if skip >= page["total"]:
            break

    assert len(seen) == len(set(seen)) == 66


def test_filters_compose(client, populated_run):
    body = client.get(
        f"/api/v1/sentinel/runs/{populated_run.id}/findings"
        "?kind=violation&severity=HIGH"
    ).json()

    assert body["total"] == 30
    assert all(f["severity"] == "HIGH" for f in body["findings"])


def test_checks_can_be_separated_from_violations(client, populated_run):
    """"Evaluated and compliant" is the fact the checks view exists to show."""
    checks = client.get(
        f"/api/v1/sentinel/runs/{populated_run.id}/findings?kind=check"
    ).json()

    assert checks["total"] == 15


def test_the_downgraded_filter_finds_refused_actions(client, populated_run):
    """The most important view in the product: what a policy asked for and did
    not get."""
    body = client.get(
        f"/api/v1/sentinel/runs/{populated_run.id}/findings?downgraded_only=true"
    ).json()

    assert body["total"] == 1
    finding = body["findings"][0]
    assert finding["requested_action"] != finding["effective_action"]
    assert finding["downgrade_reason"]


def test_search_matches_across_the_denormalised_text(client, db_session, run):
    SentinelFindingFactory.create(
        db_session, run.id, resource_name="payments-etl", message="Missing owner tag."
    )
    SentinelFindingFactory.create(db_session, run.id, resource_name="analytics")

    body = client.get(
        f"/api/v1/sentinel/runs/{run.id}/findings?search=payments"
    ).json()

    assert body["total"] == 1


def test_an_oversized_page_is_refused(client, populated_run):
    """The cap is what stops a client asking for the whole table."""
    response = client.get(
        f"/api/v1/sentinel/runs/{populated_run.id}/findings?limit=100000"
    )
    assert response.status_code == 422


def test_findings_for_an_unknown_run_are_empty_not_an_error(client):
    body = client.get("/api/v1/sentinel/runs/nope/findings").json()
    assert body["total"] == 0


# --- Facets -----------------------------------------------------------------


def test_facets_count_the_values_actually_present(client, populated_run):
    """Filter options are derived from the data, so no filter yields nothing."""
    facets = client.get(f"/api/v1/sentinel/runs/{populated_run.id}/facets").json()

    severities = {f["value"]: f["count"] for f in facets["severity"]}
    assert severities["HIGH"] == 30
    assert severities["LOW"] == 20
    assert None not in severities


def test_every_facet_value_returns_results(client, populated_run):
    """A filter offered in the UI that matches nothing is a broken filter."""
    facets = client.get(f"/api/v1/sentinel/runs/{populated_run.id}/facets").json()

    for field in ("severity", "category", "resource_type", "effective_action"):
        for facet in facets[field]:
            body = client.get(
                f"/api/v1/sentinel/runs/{populated_run.id}/findings"
                f"?{field}={facet['value']}&limit=1"
            ).json()
            assert body["total"] > 0, f"{field}={facet['value']} matched nothing"


def test_a_facet_count_is_what_choosing_it_would_return(client, mixed_run):
    """The count beside an option has to describe the result of picking it.

    Counting the whole run instead made the menu contradict the table beside
    it: with the checks excluded, the category count still included them.
    """
    run_id = mixed_run.id

    for field in ("severity", "category", "resource_type"):
        facets = client.get(
            f"/api/v1/sentinel/runs/{run_id}/facets?kind=violation"
        ).json()

        for facet in facets[field]:
            body = client.get(
                f"/api/v1/sentinel/runs/{run_id}/findings"
                f"?kind=violation&{field}={facet['value']}&limit=1"
            ).json()
            assert body["total"] == facet["count"], (
                f"{field}={facet['value']} promised {facet['count']} "
                f"but returns {body['total']}"
            )


def test_the_reported_case(client, mixed_run):
    """Violations plus reliability read 757 in the table and 2276 in the menu,
    the difference being reliability checks that had passed."""
    run_id = mixed_run.id

    facets = client.get(
        f"/api/v1/sentinel/runs/{run_id}/facets?kind=violation"
    ).json()
    reliability = next(
        f for f in facets["category"] if f["value"] == "reliability"
    )

    listed = client.get(
        f"/api/v1/sentinel/runs/{run_id}/findings"
        "?kind=violation&category=reliability&limit=1"
    ).json()

    assert reliability["count"] == 20
    assert listed["total"] == 20


def test_a_facet_ignores_only_its_own_dimension(client, mixed_run):
    """Applying the category selection to the category counts would collapse
    the menu to the one option already chosen, leaving no way back."""
    run_id = mixed_run.id
    categories = client.get(f"/api/v1/sentinel/runs/{run_id}/facets").json()["category"]
    assert len(categories) == 2

    narrowed = client.get(
        f"/api/v1/sentinel/runs/{run_id}/facets?category=security"
    ).json()

    # Both options still offered, still counted over everything but themselves.
    assert {f["value"] for f in narrowed["category"]} == {"reliability", "security"}
    assert {f["value"]: f["count"] for f in narrowed["category"]} == {
        f["value"]: f["count"] for f in categories
    }
    # Other dimensions do narrow, because they are not the one being chosen.
    severities = {f["value"]: f["count"] for f in narrowed["severity"]}
    assert severities == {"LOW": 12}


def test_facet_counts_follow_the_kind_filter(client, mixed_run):
    """The concrete bug: checks were counted into a violations-only view."""
    run_id = mixed_run.id

    everything = client.get(f"/api/v1/sentinel/runs/{run_id}/facets").json()
    violations = client.get(
        f"/api/v1/sentinel/runs/{run_id}/facets?kind=violation"
    ).json()

    assert sum(f["count"] for f in everything["category"]) == 70
    assert sum(f["count"] for f in violations["category"]) == 32
