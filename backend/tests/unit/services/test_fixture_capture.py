"""Turning a real scan into fixtures.

Capture exists because hand-written fixtures drift from what the Databricks API
actually returns, and a fixture that has drifted proves a rule works against a
shape that does not occur. Every test here is about the fixture matching the
recorded reality rather than the author's memory of it.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.db.sentinel_finding import SentinelFindingModel
from app.db.sentinel_run import SentinelRunModel
from app.services import synthetic_estate

CLUSTER = {
    "id": "0101-abc",
    "type": "cluster",
    "name": "nightly ETL",
    "owner": "someone@company.com",
    "policy_id": None,
    "tags": {"cost-center": "CC-1", "owner": "someone@company.com"},
}


def add_run(db, run_id="run-1", started=None):
    db.add(
        SentinelRunModel(
            id=run_id,
            workspace="prod-ws",
            environment="prod",
            mode="audit",
            status="completed",
            started_at=started or datetime.now(timezone.utc),
        )
    )
    db.commit()
    return run_id


def add_finding(db, run_id, *, rule, kind="violation", resource=None, workspace="prod-ws"):
    resource = resource or CLUSTER
    db.add(
        SentinelFindingModel(
            run_id=run_id,
            kind=kind,
            workspace=workspace,
            environment="prod",
            resource_id=resource["id"],
            resource_type=resource["type"],
            resource_name=resource.get("name"),
            policy_id=rule,
            rule_id=rule,
            data={"resource": resource, "rule": rule, "action": None},
        )
    )
    db.commit()


def read(directory, name):
    with open(os.path.join(directory, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


# --- What gets written ------------------------------------------------------


def test_it_captures_the_resource_exactly_as_the_scan_recorded_it(db_session, tmp_path):
    """The whole point. If capture reshapes the snapshot, the fixture stops
    being evidence of what the API returns and the drift it was meant to prevent
    comes back through the capture path."""
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CTL-CLU-002")

    written = synthetic_estate.capture_from_run(
        db_session, directory=str(tmp_path), anonymise=False
    )

    assert len(written) == 1
    resource = read(tmp_path, written[0]["name"])["resource"]
    assert resource == CLUSTER
    # Specifically: a null stays null. This is the field whose null-vs-absent
    # distinction had a rule silently never firing.
    assert resource["policy_id"] is None
    assert "policy_id" in resource


def test_it_records_which_rules_fired_and_which_did_not(db_session, tmp_path):
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CTL-CLU-002", kind="violation")
    add_finding(db_session, run_id, rule="SEC-CLU-001", kind="check")

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))
    expect = read(tmp_path, written[0]["name"])["expect"]

    assert expect["fires"] == ["CTL-CLU-002"]
    assert expect["passes"] == ["SEC-CLU-001"]


def test_all_rules_for_one_resource_land_in_one_fixture(db_session, tmp_path):
    """A fixture is a resource and every rule evaluated against it. One fixture
    per finding would give each an expectation listing a single rule, and an
    incomplete `fires` list asserts the omitted rules should *not* fire."""
    run_id = add_run(db_session)
    for rule in ("CTL-CLU-002", "CST-CLU-003", "CST-CLU-005"):
        add_finding(db_session, run_id, rule=rule)

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))

    assert len(written) == 1
    assert read(tmp_path, written[0]["name"])["expect"]["fires"] == [
        "CST-CLU-003",
        "CST-CLU-005",
        "CTL-CLU-002",
    ]


def test_a_rule_that_fired_is_never_also_listed_as_passing(db_session, tmp_path):
    """A rule can appear as both across a multi-workspace run. Expecting it to
    fire and pass at once makes the fixture unsatisfiable."""
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CST-CLU-003", kind="violation")
    add_finding(db_session, run_id, rule="CST-CLU-003", kind="check")

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))

    assert written[0]["fires"] == ["CST-CLU-003"]
    assert written[0]["passes"] == []


def test_separate_resources_become_separate_fixtures(db_session, tmp_path):
    run_id = add_run(db_session)
    other = {**CLUSTER, "id": "0202-xyz", "name": "streaming job"}
    add_finding(db_session, run_id, rule="CTL-CLU-002")
    add_finding(db_session, run_id, rule="CTL-CLU-002", resource=other)

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))

    assert len(written) == 2


# --- Privacy ----------------------------------------------------------------


def test_it_removes_owner_emails_by_default(db_session, tmp_path):
    """A fixture is a file in a repository, and the owner email is the only
    thing in a snapshot that identifies a person. Opt out, never opt in."""
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CTL-CLU-002")

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))
    resource = read(tmp_path, written[0]["name"])["resource"]

    assert "someone@company.com" not in json.dumps(resource)
    assert resource["owner"] == "owner@example.com"
    assert resource["tags"]["owner"] == "owner@example.com"


def test_anonymising_does_not_drop_the_owner_field(db_session, tmp_path):
    """Several rules turn on whether an owner is set at all, so removing the
    key rather than replacing it would change which rules fire."""
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CTL-CLU-002")

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))
    resource = read(tmp_path, written[0]["name"])["resource"]

    assert resource["owner"]
    assert resource["tags"]["owner"]
    assert set(resource) == set(CLUSTER)


# --- Selection --------------------------------------------------------------


def test_it_defaults_to_the_most_recent_run(db_session, tmp_path):
    now = datetime.now(timezone.utc)
    old = add_run(db_session, "run-old", started=now - timedelta(days=2))
    new = add_run(db_session, "run-new", started=now)
    add_finding(db_session, old, rule="OLD-001")
    add_finding(db_session, new, rule="NEW-001", resource={**CLUSTER, "id": "new-1"})

    written = synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))

    assert [w["fires"] for w in written] == [["NEW-001"]]


def test_it_can_capture_named_resources_only(db_session, tmp_path):
    run_id = add_run(db_session)
    other = {**CLUSTER, "id": "0202-xyz", "name": "streaming"}
    add_finding(db_session, run_id, rule="CTL-CLU-002")
    add_finding(db_session, run_id, rule="CTL-CLU-002", resource=other)

    written = synthetic_estate.capture_from_run(
        db_session, resource_ids=["0202-xyz"], directory=str(tmp_path)
    )

    assert len(written) == 1


def test_it_honours_the_limit(db_session, tmp_path):
    """A production scan can hold thousands of resources and capture writes a
    file each."""
    run_id = add_run(db_session)
    for i in range(10):
        add_finding(
            db_session, run_id, rule="CTL-CLU-002", resource={**CLUSTER, "id": f"c-{i}"}
        )

    written = synthetic_estate.capture_from_run(
        db_session, limit=3, directory=str(tmp_path)
    )

    assert len(written) == 3


def test_no_runs_at_all_is_an_empty_result_not_a_crash(db_session, tmp_path):
    assert synthetic_estate.capture_from_run(db_session, directory=str(tmp_path)) == []


def test_findings_without_a_resource_snapshot_are_skipped(db_session, tmp_path):
    """Error rows carry ``data={"error": ...}`` and older rows may predate
    snapshotting. Neither can produce a usable fixture."""
    run_id = add_run(db_session)
    db_session.add(
        SentinelFindingModel(
            run_id=run_id,
            kind="violation",
            workspace="prod-ws",
            environment="prod",
            resource_id="broken",
            policy_id="X-001",
            data={"error": "discovery failed"},
        )
    )
    db_session.commit()

    assert synthetic_estate.capture_from_run(db_session, directory=str(tmp_path)) == []


# --- Round trip -------------------------------------------------------------


def test_a_captured_fixture_can_be_loaded_back(db_session, tmp_path):
    """Capture and the fixture loader have to agree on the file format, and
    nothing else checks that they do."""
    run_id = add_run(db_session)
    add_finding(db_session, run_id, rule="CTL-CLU-002")

    synthetic_estate.capture_from_run(db_session, directory=str(tmp_path))
    loaded = synthetic_estate.load_fixtures(str(tmp_path))

    assert len(loaded) == 1
    assert loaded[0].resource_type == "cluster"
    assert loaded[0].fires == ["CTL-CLU-002"]
    assert loaded[0].source == "captured"
