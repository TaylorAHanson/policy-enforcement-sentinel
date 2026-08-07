"""Giving a finding an identity, and closing it only on evidence.

Most of these tests are about refusing to close things. A finding that vanishes
from a scan looks the same whether somebody fixed it, the resource was deleted,
a policy was narrowed, or discovery could not enumerate the type at all — and
only the first is good news. Collapsing them would mean a broken handler reports
as a wave of remediation, which is the product's main output lying in the most
comforting possible direction.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db.finding_state import (
    RESOLUTION_FIXED,
    RESOLUTION_NOT_EVALUATED,
    RESOLUTION_RESOURCE_GONE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    SentinelFindingStateModel,
)
from app.db.sentinel_finding import SentinelFindingModel
from app.db.sentinel_run import SentinelRunModel
from app.services import finding_lifecycle as fl

WS = "prod-ws"
START = datetime(2026, 8, 1, 12, 0, 0)


def add_run(db, run_id, *, offset_days=0, workspaces=None, errors=None):
    """A run whose summary says which types it managed to enumerate."""
    summary = {
        "workspace": WS,
        "status": "completed",
        "errors": errors or {},
        "field_observations": {
            "resource_types": {t: {"resource_count": 1, "fields": {}} for t in (workspaces or ["cluster"])}
        },
    }
    db.add(
        SentinelRunModel(
            id=run_id,
            workspace=WS,
            environment="prod",
            mode="audit",
            status="completed",
            started_at=START + timedelta(days=offset_days),
            results={"workspaces": [summary]},
        )
    )
    db.commit()
    return db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).one()


def add_finding(
    db,
    run_id,
    *,
    rule="SEC-CLU-001",
    kind="violation",
    resource_id="c-1",
    resource_type="cluster",
    name=None,
):
    db.add(
        SentinelFindingModel(
            run_id=run_id,
            kind=kind,
            workspace=WS,
            environment="prod",
            resource_id=resource_id,
            resource_type=resource_type,
            resource_name=name or resource_id,
            policy="clusters",
            rule_id=rule,
            policy_id=rule,
            severity="HIGH",
            message="something",
        )
    )
    db.commit()


def state_of(db, **over):
    states = db.query(SentinelFindingStateModel).all()
    assert len(states) == 1, f"expected one tracked finding, got {len(states)}"
    return states[0]


# --- Identity ---------------------------------------------------------------


def test_the_same_problem_seen_twice_is_one_finding():
    a = fl.fingerprint(workspace=WS, resource_type="cluster", resource_id="c-1", policy_id="SEC-1")
    b = fl.fingerprint(workspace=WS, resource_type="cluster", resource_id="c-1", policy_id="SEC-1")
    assert a == b


def test_the_resource_type_is_part_of_the_identity():
    """Ids are unique within a type, not across one. A real workspace had
    `regression-validation-dev` as both an app and a Lakebase instance, and
    keying on the id alone had already merged two resources into one record once
    in the fixture capture."""
    app = fl.fingerprint(workspace=WS, resource_type="app", resource_id="shared", policy_id="SEC-1")
    lakebase = fl.fingerprint(
        workspace=WS, resource_type="lakebase_instance", resource_id="shared", policy_id="SEC-1"
    )
    assert app != lakebase


def test_the_workspace_is_part_of_the_identity():
    """The same rule breaking on the same resource id in two workspaces is two
    problems, for two different teams."""
    assert fl.fingerprint(
        workspace="a", resource_type="cluster", resource_id="c-1", policy_id="S"
    ) != fl.fingerprint(
        workspace="b", resource_type="cluster", resource_id="c-1", policy_id="S"
    )


def test_two_rules_about_one_resource_are_two_findings():
    assert fl.fingerprint(
        workspace=WS, resource_type="cluster", resource_id="c-1", policy_id="SEC-1"
    ) != fl.fingerprint(
        workspace=WS, resource_type="cluster", resource_id="c-1", policy_id="SEC-2"
    )


def test_something_that_cannot_be_identified_gets_no_fingerprint():
    """Rather than a fingerprint that silently merges every unidentifiable
    finding into one row."""
    assert fl.fingerprint(workspace=WS, resource_type="cluster", resource_id=None, policy_id="S") is None
    assert fl.fingerprint(workspace=WS, resource_type="cluster", resource_id="c", policy_id=None) is None


def test_the_package_and_rule_stand_in_for_a_missing_policy_id():
    """Older findings carry no stable id, and dropping them from tracking would
    lose the history this exists to provide."""
    assert fl.fingerprint(
        workspace=WS, resource_type="cluster", resource_id="c-1", policy="clusters", rule_id="no_auto"
    )


# --- Opening ----------------------------------------------------------------


def test_a_first_sighting_records_when_it_appeared(db_session):
    run = add_run(db_session, "r1")
    add_finding(db_session, "r1")

    counts = fl.reconcile_run(db_session, run)

    assert counts["new"] == 1
    state = state_of(db_session)
    assert state.status == STATUS_OPEN
    assert state.first_seen_at == START
    assert state.occurrences == 1


def test_seeing_it_again_ages_it_rather_than_duplicating_it(db_session):
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=7)
    add_finding(db_session, "r2")
    counts = fl.reconcile_run(db_session, run2)

    assert counts["new"] == 0
    assert counts["still_open"] == 1
    state = state_of(db_session)
    assert state.first_seen_at == START, "the age of the problem, not of the sighting"
    assert state.last_seen_at == START + timedelta(days=7)
    assert state.occurrences == 2


# --- Closing, which is the dangerous half -----------------------------------


def test_a_rule_that_ran_and_passed_closes_it_as_fixed(db_session):
    """The only evidence that means somebody fixed something."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=1)
    add_finding(db_session, "r2", kind="check")
    counts = fl.reconcile_run(db_session, run2)

    assert counts["fixed"] == 1
    state = state_of(db_session)
    assert state.status == STATUS_RESOLVED
    assert state.resolution == RESOLUTION_FIXED


def test_a_finding_whose_type_failed_to_enumerate_stays_open(db_session):
    """The one that matters most. If a permissions change breaks the volume
    handler, four hundred findings must not quietly close and report as
    progress — the estate is exactly as it was and nobody has been told."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run1)

    # A scan that could not list clusters at all.
    run2 = add_run(db_session, "r2", offset_days=1, workspaces=[], errors={"cluster": "403"})
    counts = fl.reconcile_run(db_session, run2)

    assert counts["unjudgeable"] == 1
    assert counts["fixed"] == 0
    state = state_of(db_session)
    assert state.status == STATUS_OPEN


def test_an_unjudged_finding_keeps_its_old_evaluation_stamp(db_session):
    """What makes a stale finding distinguishable from a confirmed one. Without
    it, "open" means both "still true" and "we have not looked since March"."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=30, workspaces=[], errors={"cluster": "403"})
    fl.reconcile_run(db_session, run2)

    assert state_of(db_session).last_evaluated_at == START


def test_a_partial_enumeration_is_not_a_basis_for_closing_anything(db_session):
    """The type errored *and* returned some resources. A partial listing cannot
    show that anything is absent."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1", resource_id="c-1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=1, workspaces=["cluster"], errors={"cluster": "timeout"})
    add_finding(db_session, "r2", resource_id="c-2")
    counts = fl.reconcile_run(db_session, run2)

    assert counts["unjudgeable"] == 1
    assert counts["resource_gone"] == 0


def test_a_deleted_resource_closes_but_not_as_fixed(db_session):
    """Nothing improved. The finding is moot because the thing it was about is
    gone, and a dashboard that counts this as remediation is measuring
    deletions."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1", resource_id="c-1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=1)
    add_finding(db_session, "r2", resource_id="c-2")
    counts = fl.reconcile_run(db_session, run2)

    gone = db_session.query(SentinelFindingStateModel).filter(
        SentinelFindingStateModel.resource_id == "c-1"
    ).one()
    assert counts["resource_gone"] == 1
    assert gone.resolution == RESOLUTION_RESOURCE_GONE


def test_a_rule_that_stopped_applying_closes_but_not_as_fixed(db_session):
    """Somebody narrowed a policy. The resource is still there and still however
    it was; we merely stopped asking. Reporting this as fixed would turn an edit
    to a policy file into a wave of good news."""
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1", rule="SEC-CLU-001")
    fl.reconcile_run(db_session, run1)

    # Same resource, still enumerated, judged by a different rule only.
    run2 = add_run(db_session, "r2", offset_days=1)
    add_finding(db_session, "r2", rule="CST-CLU-004")
    fl.reconcile_run(db_session, run2)

    stale = db_session.query(SentinelFindingStateModel).filter(
        SentinelFindingStateModel.policy_id == "SEC-CLU-001"
    ).one()
    assert stale.status == STATUS_RESOLVED
    assert stale.resolution == RESOLUTION_NOT_EVALUATED


def test_the_three_ways_of_closing_are_never_merged():
    """Only one of them is somebody having done something."""
    assert len({RESOLUTION_FIXED, RESOLUTION_RESOURCE_GONE, RESOLUTION_NOT_EVALUATED}) == 3


# --- Coming back ------------------------------------------------------------


def test_a_finding_that_comes_back_is_the_same_finding(db_session):
    run1 = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run1)

    run2 = add_run(db_session, "r2", offset_days=1)
    add_finding(db_session, "r2", kind="check")
    fl.reconcile_run(db_session, run2)

    run3 = add_run(db_session, "r3", offset_days=2)
    add_finding(db_session, "r3")
    counts = fl.reconcile_run(db_session, run3)

    state = state_of(db_session)
    assert counts["reopened"] == 1
    assert counts["new"] == 0, "a returning problem is not a new one"
    assert state.status == STATUS_OPEN
    assert state.reopened == 1
    assert state.resolution is None
    assert state.first_seen_at == START, "it dates from the first time, not the relapse"


def test_repeated_relapses_are_counted(db_session):
    """A resource fixed and re-broken every week is a process problem, and it
    looks identical to a stable violation if you only count occurrences."""
    for day in range(6):
        run = add_run(db_session, f"r{day}", offset_days=day)
        add_finding(db_session, f"r{day}", kind="violation" if day % 2 == 0 else "check")
        fl.reconcile_run(db_session, run)

    assert state_of(db_session).reopened == 2


# --- Replaying history ------------------------------------------------------


def test_backfill_dates_findings_from_when_they_first_appeared(db_session):
    """Starting from empty would mean nobody sees a trend for two more scans,
    when the history to answer "how long has this been open" is already there."""
    for day in range(3):
        add_run(db_session, f"r{day}", offset_days=day)
        add_finding(db_session, f"r{day}")

    result = fl.backfill(db_session)

    assert result["runs_replayed"] == 3
    assert result["findings_tracked"] == 1
    state = state_of(db_session)
    assert state.first_seen_at == START
    assert state.occurrences == 3


def test_backfill_is_safe_to_run_twice(db_session):
    """It is a repair tool, and a repair tool that corrupts on a second run is
    one somebody will eventually run twice."""
    add_run(db_session, "r1")
    add_finding(db_session, "r1")

    fl.backfill(db_session)
    first = state_of(db_session).occurrences
    fl.backfill(db_session)

    assert db_session.query(SentinelFindingStateModel).count() == 1
    assert state_of(db_session).occurrences == first + 1, "replay counts a sighting again"


# --- Coverage ---------------------------------------------------------------


def test_a_verdict_proves_its_type_was_enumerated(db_session):
    """Runs predating field observations carry no record of what was scanned,
    and a verdict about a resource is itself the proof."""
    run = add_run(db_session, "r1", workspaces=[])
    add_finding(db_session, "r1", resource_type="cluster")
    findings = db_session.query(SentinelFindingModel).all()

    coverage = fl.ScanCoverage.from_run(run, findings)

    assert coverage.covers(WS, "cluster")
    assert not coverage.covers(WS, "dataset")


def test_an_errored_type_is_not_covered_however_much_it_returned(db_session):
    run = add_run(db_session, "r1", workspaces=["cluster"], errors={"cluster": "boom"})
    add_finding(db_session, "r1")
    findings = db_session.query(SentinelFindingModel).all()

    assert not fl.ScanCoverage.from_run(run, findings).covers(WS, "cluster")


def test_a_failed_workspace_covers_nothing(db_session):
    run = add_run(db_session, "r1")
    run.results = {"workspaces": [{"workspace": WS, "status": "failed", "errors": {}}]}
    db_session.commit()

    assert len(fl.ScanCoverage.from_run(run, [])) == 0


# --- Which scan the summary describes ---------------------------------------
#
# The panel was pinned to the newest scan while the stat cards beside it
# described whichever run was selected. Both sets of numbers were correct and
# they contradicted each other on one screen, with nothing saying why — the
# panel reading "3,789 open" above a Violations card reading "3,041".


def three_scans(db):
    """Three runs: a finding appears at r1, is fixed at r2, comes back at r3."""
    runs = []
    for day, kind in enumerate(["violation", "check", "violation"]):
        run = add_run(db, f"r{day}", offset_days=day)
        add_finding(db, f"r{day}", kind=kind)
        fl.reconcile_run(db, run)
        runs.append(run)
    return runs


def test_the_summary_describes_the_newest_scan_by_default(db_session):
    three_scans(db_session)
    result = fl.summary(db_session)

    assert result["is_latest"] is True
    assert result["returned"]["count"] == 1, "the relapse happened at the newest scan"


def test_a_named_scan_reports_its_own_facts(db_session):
    runs = three_scans(db_session)

    # runs[0] is the first scan, which reports no changes by design.
    fixed_at = fl.summary(db_session, run_id=runs[1].id)
    returned_at = fl.summary(db_session, run_id=runs[2].id)

    assert returned_at["returned"]["count"] == 1
    assert returned_at["fixed"]["count"] == 0
    # And not the relapse, which belongs to the scan that saw it.
    assert fixed_at["returned"]["count"] == 0


def test_a_past_scans_fix_is_forgotten_once_the_finding_relapses(db_session):
    """A known limit, pinned so it is a decision rather than a surprise.

    The state table holds each finding's current position, not an event log, so
    reopening clears the record of which scan closed it. Scan 8 fixed it and
    scan 9 saw it again: scan 8's "fixed" count drops to zero.

    This under-reports how much a past scan moved and can never over-report it,
    and the newest scan — where the dashboard opens — is unaffected. Making it
    exact means storing one row per finding per scan.
    """
    runs = three_scans(db_session)

    assert fl.summary(db_session, run_id=runs[1].id)["fixed"]["count"] == 0
    assert state_of(db_session).reopened == 1, "it did relapse; that is why"


def test_an_older_scan_says_it_is_not_the_latest(db_session):
    """So the panel can label itself rather than quietly describing a different
    run from the cards beside it."""
    runs = three_scans(db_session)
    assert fl.summary(db_session, run_id=runs[0].id)["is_latest"] is False


def test_a_scan_compares_against_the_one_before_it_not_the_newest(db_session):
    runs = three_scans(db_session)
    assert fl.summary(db_session, run_id=runs[1].id)["compared_to"] == runs[0].id


def test_what_a_past_scan_changed_does_not_change(db_session):
    """A fact about a finished scan. If it moved as new scans arrived, the
    history would be unreadable and nobody could cite it."""
    runs = three_scans(db_session)
    before = fl.summary(db_session, run_id=runs[2].id)["returned"]
    assert before["count"] == 1, "guard: the test needs something to preserve"

    later = add_run(db_session, "r9", offset_days=9)
    add_finding(db_session, "r9", resource_id="c-2")
    fl.reconcile_run(db_session, later)

    after = fl.summary(db_session, run_id=runs[2].id)["returned"]

    # Which findings, not every field on them: last_evaluated_at rightly moves
    # each time a later scan looks at the same resource again.
    assert after["count"] == before["count"]
    assert [i["fingerprint"] for i in after["items"]] == [
        i["fingerprint"] for i in before["items"]
    ]


def test_staleness_is_only_asked_of_the_newest_scan(db_session):
    """"Nothing has confirmed this lately" is a claim about now. Asked of a scan
    from March it would report every finding as unconfirmed, which is true and
    useless."""
    runs = three_scans(db_session)
    assert fl.summary(db_session, run_id=runs[0].id)["unconfirmed"]["count"] == 0


def test_an_unknown_scan_is_unavailable_rather_than_the_latest(db_session):
    """Falling back to the newest run would put the wrong scan's numbers under a
    heading naming the one that was asked for."""
    three_scans(db_session)
    result = fl.summary(db_session, run_id="does-not-exist")

    assert result["available"] is False
    assert "history" in result["reason"]


def test_the_first_scan_reports_no_changes(db_session):
    """Everything is new at the first scan, and calling 3,789 findings "new"
    would make the one number that matters meaningless on the day it matters
    most."""
    run = add_run(db_session, "r1")
    add_finding(db_session, "r1")
    fl.reconcile_run(db_session, run)

    result = fl.summary(db_session)
    assert result["is_first_scan"] is True
    assert result["appeared"]["count"] == 0
    assert result["open_now"] == 1
