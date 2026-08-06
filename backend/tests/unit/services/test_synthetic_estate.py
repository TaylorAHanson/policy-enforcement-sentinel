"""The fixture runner, and the fixtures that ship with it.

The last test in this file is the one that earns its keep: it runs the committed
fixtures against the committed policies. It fails when someone edits a rule and
changes what it catches without noticing — which is the whole point of having
fixtures, and is not something any other test here can tell you.
"""
from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from app.services import synthetic_estate
from app.services.synthetic_estate import FixtureError, parse_fixture

CLUSTER = {
    "id": "0101-test",
    "type": "cluster",
    "cluster_type": "job",
    "access_mode": "single_user",
    "policy_id": "standard",
    "autotermination_minutes": 30,
    "idle_days": 1,
    "tags": {"cost-center": "CC-1", "owner": "a@b.com"},
}


# --- Reading fixtures -------------------------------------------------------


def test_a_fixture_needs_a_resource_type():
    """Without a type no policy claims it, so it would pass by never being
    evaluated — the most misleading possible green."""
    with pytest.raises(FixtureError):
        parse_fixture("broken", {"resource": {"id": "x"}})


def test_a_fixture_without_a_resource_is_refused():
    with pytest.raises(FixtureError):
        parse_fixture("broken", {"expect": {"fires": ["X-1"]}})


def test_expectations_accept_a_bare_string():
    fixture = parse_fixture("one", {"resource": CLUSTER, "expect": {"fires": "SEC-CLU-001"}})

    assert fixture.fires == ["SEC-CLU-001"]


def test_a_fixture_with_no_expectations_is_valid():
    """Useful while writing one: run it, see what fires, then write it down."""
    fixture = parse_fixture("blank", {"resource": CLUSTER})

    assert fixture.fires == []
    assert fixture.passes == []


def test_defaults_are_filled_in():
    fixture = parse_fixture("defaults", {"resource": CLUSTER})

    assert fixture.workspace == "synthetic-workspace"
    assert fixture.environment == "dev"
    assert fixture.source == "handwritten"


def test_a_malformed_file_is_skipped_not_fatal(tmp_path):
    """One bad file must not stop the rest from running."""
    (tmp_path / "good.json").write_text(json.dumps({"resource": CLUSTER}))
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "notes.txt").write_text("ignored")

    loaded = synthetic_estate.load_fixtures(str(tmp_path))

    assert [f.name for f in loaded] == ["good"]


def test_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert synthetic_estate.load_fixtures(str(tmp_path / "nope")) == []


# --- Running against real OPA ----------------------------------------------


@pytest.fixture
def opa_available():
    if shutil.which("opa") is None:
        pytest.skip("The opa binary is not installed.")


def run(directory=None, only=None):
    return asyncio.run(synthetic_estate.run_all(directory, only=only))


def write(tmp_path, name, payload):
    (tmp_path / f"{name}.json").write_text(json.dumps(payload))


def test_an_empty_directory_reports_nothing_rather_than_passing(tmp_path):
    """Zero fixtures is not a green run.

    "0 passed, 0 failed" reads as success at a glance, which is how a CI safety
    step pointed at an empty directory went unnoticed. ``ok`` has to say no.
    """
    result = run(str(tmp_path))

    assert result["total"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["results"] == []
    assert result["ok"] is False


def test_a_fixture_that_matches_reality_passes(tmp_path, opa_available):
    write(
        tmp_path,
        "clean",
        {
            "resource": CLUSTER,
            "environment": "prod",
            "expect": {"passes": ["SEC-CLU-001", "CST-CLU-005"]},
        },
    )

    result = run(str(tmp_path))

    assert result["passed"] == 1, result["results"]


def test_a_rule_that_was_expected_to_fire_but_did_not_is_reported(tmp_path, opa_available):
    write(
        tmp_path,
        "wrong",
        {"resource": CLUSTER, "expect": {"fires": ["SEC-CLU-001"]}},
    )

    result = run(str(tmp_path))

    assert result["failed"] == 1
    assert result["results"][0]["missing"] == ["SEC-CLU-001"]


def test_a_rule_that_fires_without_being_expected_is_reported(tmp_path, opa_available):
    """A policy widening to catch resources it was never meant to is invisible
    in a dashboard; it looks like the system working."""
    untagged = {**CLUSTER, "tags": {}}
    write(tmp_path, "widened", {"resource": untagged, "expect": {}})

    result = run(str(tmp_path))

    assert result["failed"] == 1
    assert "CST-CLU-003" in result["results"][0]["unexpected"]


def test_a_rule_expected_to_pass_but_firing_is_reported(tmp_path, opa_available):
    untagged = {**CLUSTER, "tags": {}}
    write(tmp_path, "regressed", {"resource": untagged, "expect": {"passes": ["CST-CLU-003"]}})

    result = run(str(tmp_path))

    assert result["results"][0]["wrongly_fired"] == ["CST-CLU-003"]


def test_a_rule_expected_to_pass_that_never_ran_is_reported(tmp_path, opa_available):
    """"Passed" must mean evaluated and compliant, never "not looked at"."""
    write(tmp_path, "unevaluated", {"resource": CLUSTER, "expect": {"passes": ["JOB-999"]}})

    result = run(str(tmp_path))

    assert result["results"][0]["not_evaluated"] == ["JOB-999"]


def test_only_runs_the_named_fixtures(tmp_path, opa_available):
    write(tmp_path, "one", {"resource": CLUSTER})
    write(tmp_path, "two", {"resource": CLUSTER})

    result = run(str(tmp_path), only=["two"])

    assert result["total"] == 1
    assert result["results"][0]["fixture"] == "two"


def test_the_effective_action_comes_from_the_real_chokepoint(tmp_path, opa_available):
    """The gap between what a policy asks for and what would happen.

    Enforcement ships off, so a rule requesting WARN resolves to FLAG — recorded
    and nothing else. A synthetic run reports that rather than echoing the
    request back, because "this policy warns the owner" and "this policy would
    do nothing at your current settings" are the two answers people most often
    confuse.
    """
    untagged = {**CLUSTER, "tags": {}}
    write(tmp_path, "action", {"resource": untagged, "expect": {"fires": ["CST-CLU-003"]}})

    result = run(str(tmp_path))
    rules = {r["rule_id"]: r for r in result["results"][0]["rules"]}

    assert rules["CST-CLU-003"]["requested_action"] == "WARN"
    assert rules["CST-CLU-003"]["effective_action"] == "FLAG"
    assert rules["CST-CLU-003"]["downgraded"] is True
    assert result["enforcement_enabled"] is False


def test_a_passing_rule_is_not_reported_as_downgraded(tmp_path, opa_available):
    """A compliant rule has no requested action, and putting that through the
    chokepoint would show every passing rule as a downgrade."""
    write(tmp_path, "clean", {"resource": CLUSTER, "expect": {"passes": ["CST-CLU-003"]}})

    result = run(str(tmp_path))
    rules = {r["rule_id"]: r for r in result["results"][0]["rules"]}

    assert rules["CST-CLU-003"]["effective_action"] is None
    assert rules["CST-CLU-003"]["downgraded"] is False


def test_a_null_optional_field_is_treated_as_absent(tmp_path, opa_available):
    """The bug this harness found on its first run.

    The SDK returns ``policy_id: null`` for a cluster with no compute policy,
    and ``not input.resource.policy_id`` does not match a JSON null — so the
    rule silently never fired. Pinned here as well as in a fixture because it is
    a trap the next policy author will walk into too.
    """
    no_policy = {**CLUSTER, "policy_id": None}
    write(tmp_path, "nullpolicy", {"resource": no_policy, "expect": {"fires": ["CTL-CLU-002"]}})

    result = run(str(tmp_path))

    assert result["passed"] == 1, result["results"]


def test_a_pattern_exception_in_a_fixture_waives_only_its_rule(tmp_path, opa_available):
    """The same matcher the safety suite covers, reached through a scan-shaped
    input rather than a probe policy."""
    idle = {**CLUSTER, "idle_days": 200, "policy_id": None}
    write(
        tmp_path,
        "waived",
        {
            "resource": idle,
            "allowlist_records": [
                {
                    "id": "e1",
                    "match_type": "pattern",
                    "resource_type": "cluster",
                    "rule_id": "CST-CLU-005",
                    "status": "approved",
                    "justification": "Agreed.",
                    "expires_at": None,
                }
            ],
            "expect": {"fires": ["CST-CLU-005", "CTL-CLU-002"]},
        },
    )

    result = run(str(tmp_path))
    rules = {r["rule_id"]: r for r in result["results"][0]["rules"]}

    assert rules["CST-CLU-005"]["requested_action"] == "SKIPPED_ALLOWLIST"
    assert rules["CTL-CLU-002"]["requested_action"] == "WARN"


# --- The committed fixtures against the committed policies ------------------


def test_the_shipped_fixtures_agree_with_the_shipped_policies(opa_available):
    """The regression test this whole module exists to make possible.

    A failure here is not a broken test. It means a policy now catches
    something different from what it caught when the fixture was written, and
    somebody has to decide which of the two is right.
    """
    result = run()

    if result["total"] == 0:
        pytest.skip("No fixtures are committed.")

    failures = [
        f"{r['fixture']}: missing={r['missing']} unexpected={r['unexpected']} "
        f"not_evaluated={r['not_evaluated']} wrongly_fired={r['wrongly_fired']} "
        f"error={r['error']}"
        for r in result["results"]
        if not r["passed"]
    ]

    assert not failures, "Fixtures disagree with the policies:\n  " + "\n  ".join(failures)
