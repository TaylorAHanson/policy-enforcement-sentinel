"""A rule that is not working has to say which kind of not working it is.

"41 rules have no fixture" reads as one problem with one owner. It is at least
three, with three different people who could act, and only one of them is a bug
in a rule. Collapsing them is how the fixable ones stayed unfixed.
"""
from __future__ import annotations

import pytest

from app.services import rule_diagnosis


@pytest.fixture(scope="module")
def report():
    return rule_diagnosis.diagnose()


def test_every_rule_gets_a_category(report):
    assert report["rules"]
    for rule in report["rules"]:
        assert rule["category"] in rule_diagnosis.CATEGORIES


def test_the_categories_account_for_every_rule(report):
    """The counts have to add up, or the summary is lying about the total."""
    assert sum(report["by_category"].values()) == report["total"]


def test_working_means_shown_firing_on_data_the_scanner_produces(report):
    for rule in report["rules"]:
        assert (rule["category"] == "working") == bool(rule["reachable"])


def test_every_category_says_what_to_do_about_it():
    """A category with no action is a label, and a label does not help."""
    for name, info in rule_diagnosis.CATEGORIES.items():
        assert info["label"]
        assert info["detail"]
        if name != "working":
            assert info["action"], f"{name} does not say what to do"


# --- The categories that matter ---------------------------------------------


#: The three categories that mean "this rule reads a field it does not get".
#: They differ only in who can do something about it.
BLOCKED_ON_A_FIELD = {"needs_discovery", "needs_permission", "not_exposed"}


def test_a_rule_blocked_on_a_field_names_the_field(report):
    """"Waiting on the scanner" is useless without saying waiting on what."""
    blocked = [r for r in report["rules"] if r["category"] in BLOCKED_ON_A_FIELD]
    assert blocked, "expected some rules to be blocked on a field"
    for rule in blocked:
        assert rule["missing_fields"], f"{rule['rule_id']} names no missing field"


def test_only_rules_blocked_on_a_field_name_missing_fields(report):
    for rule in report["rules"]:
        if rule["category"] not in BLOCKED_ON_A_FIELD:
            assert not rule["missing_fields"]


def test_nothing_is_merely_waiting_on_a_collector(report):
    """Every field that *can* be collected, is.

    What remains is blocked on a grant or absent from the platform. If this
    fails, somebody added a rule reading a field that could be discovered and
    has not been — which is a real gap, and the failure is how you hear about
    it. Add the field to the handler, or record why it cannot be in
    `rule_diagnosis.BLOCKED_FIELDS`.
    """
    waiting = {
        r["rule_id"]: r["missing_fields"]
        for r in report["rules"]
        if r["category"] == "needs_discovery"
    }
    assert not waiting, f"These read collectable fields nothing collects: {waiting}"


def test_a_permission_blocked_rule_says_what_access_it_needs(report):
    """Otherwise it is indistinguishable from work nobody has got to yet."""
    blocked = [r for r in report["rules"] if r["category"] == "needs_permission"]
    assert blocked, "expected the grant-visibility and system-table rules here"
    for rule in blocked:
        assert rule["blockers"], f"{rule['rule_id']} names no blocker"
        for blocker in rule["blockers"]:
            assert blocker["requirement"], (
                f"{rule['rule_id']} is blocked on permission but names none"
            )
            assert blocker["detail"]


def test_unity_catalog_grants_are_a_permissions_problem_not_a_collector_one(report):
    """Guards against 'helpfully' re-adding an information_schema grant read.

    `table_privileges` and `volume_privileges` look like the obvious source and
    are filtered to the caller: a scanner that is not the object's owner or a
    metastore admin sees only its own grants. Collecting that would turn three
    security rules permanently green while looking like progress.
    """
    by_id = {r["rule_id"]: r for r in report["rules"]}
    for rule_id in ("SEC-DST-005", "SEC-DST-006", "SEC-VOL-002"):
        rule = by_id[rule_id]
        assert rule["category"] == "needs_permission", (
            f"{rule_id} is {rule['category']}; Unity Catalog will not disclose "
            "another principal's grants to this scanner"
        )


def test_idle_days_is_collected_where_it_can_be_and_blocked_where_it_cannot(report):
    """The field that motivated all of this, split by what is actually knowable.

    Clusters, jobs and tables have a real activity signal in the workspace API.
    The other six expose edit times and nothing about use, so their rules are
    waiting on a grant rather than on code.
    """
    by_id = {r["rule_id"]: r for r in report["rules"]}

    for rule_id in ("CST-CLU-005", "CST-JOB-003", "CTL-DST-010"):
        assert "idle_days" not in by_id[rule_id]["missing_fields"], (
            f"{rule_id} should have idle_days now"
        )

    for rule_id in (
        "CST-APP-003",
        "CTL-DSH-003",
        "CST-GEN-004",
        "CST-LKB-003",
        "SEC-SPN-001",
        "CST-WHS-005",
    ):
        assert by_id[rule_id]["category"] == "needs_permission"


def test_a_rule_with_no_handler_is_not_blamed_on_a_missing_field(report):
    """Nothing scans workspaces, so naming a field would send the wrong person.

    The fix is a handler that does not exist, not a field to add to one that
    does.
    """
    orphans = [r for r in report["rules"] if r["category"] == "no_handler"]
    assert orphans, "workspaces has rules and no handler; expected some here"
    for rule in orphans:
        assert not rule["missing_fields"]


def test_the_suspect_rules_are_the_ones_reading_real_data_and_never_matching(report):
    """These are the actual bugs, and the reason this classification exists.

    Each reads only fields discovery does collect, so nothing external is
    blocking them — and a fixture exists that expects them not to fire, meaning
    somebody tried to test them and could not make them.

    This set used to hold seven. Six were fixed once the category told us where
    to look: five owner checks that tested for a missing key while every handler
    writes the string "unknown", and one comparing `access_mode` against a
    literal the SDK has never emitted.
    """
    suspects = {r["rule_id"] for r in report["rules"] if r["category"] == "suspect"}

    # SEC-VOL-001 asks whether production data sits in DBFS. The volume handler
    # discovers Unity Catalog volumes, which are MANAGED or EXTERNAL and never
    # DBFS by construction — so this is not a value to correct but a question
    # about a resource class nothing discovers. It needs a product decision,
    # and it stays visible until it gets one.
    assert suspects == {"SEC-VOL-001"}, (
        "The suspect set changed. A new entry is a rule that reads real data "
        "and cannot match — look at it before shipping."
    )


def test_the_owner_checks_now_recognise_an_unknown_owner(report):
    """The bug that hid five rules at once.

    Every handler defaults `owner` to "unknown" when the API named nobody, and
    all five rules tested `not object.get(resource, "owner", false)`, which is
    false for any non-empty string. Five rules whose entire job was finding
    unowned resources reported that every resource had an owner.
    """
    by_id = {r["rule_id"]: r for r in report["rules"]}
    for rule_id in (
        "CTL-DSH-002",
        "CTL-DST-007",
        "CTL-LKB-004",
        "CTL-SPN-003",
        "CTL-VOL-004",
    ):
        assert by_id[rule_id]["category"] == "working", (
            f"{rule_id} regressed to {by_id[rule_id]['category']}"
        )


def test_a_suspect_reads_only_collected_fields(report):
    """Otherwise it belongs in needs_discovery and has a different owner."""
    for rule in report["rules"]:
        if rule["category"] == "suspect":
            assert not rule["missing_fields"]
            assert rule["passes_in"], "a suspect must have a test that tried"


# --- The field that unblocks the most ---------------------------------------


def test_blocked_fields_are_ordered_by_how_much_they_unblock(report):
    """The point is to make a discovery decision, so lead with the payoff."""
    counts = [entry["rule_count"] for entry in report["blocked_on"]]
    assert counts == sorted(counts, reverse=True)


def test_a_not_exposed_rule_names_no_requirement(report):
    """There is no access to ask for, so offering one would send somebody on a
    pointless errand. The detail still has to explain why."""
    for rule in report["rules"]:
        if rule["category"] != "not_exposed":
            continue
        assert rule["blockers"]
        for blocker in rule["blockers"]:
            assert not blocker["requirement"]
            assert blocker["detail"]


def test_every_blocked_field_entry_is_reachable_from_some_rule():
    """A stale entry in the table would quietly mislabel nothing at all."""
    from app.services import rule_diagnosis as module

    report = module.diagnose()
    named = {
        blocker["field"] for rule in report["rules"] for blocker in rule["blockers"]
    }
    declared = {str(entry["field"]) for entry in module.BLOCKED_FIELDS}
    unused = declared - named
    assert not unused, (
        f"These fields are recorded as blocked and no rule reads them: {unused}. "
        "Either a rule was retired or the entry is wrong."
    )


def test_every_blocked_field_lists_the_rules_waiting_on_it(report):
    for entry in report["blocked_on"]:
        assert entry["rules"]
        assert entry["rule_count"] == len(entry["rules"])
        assert entry["resource_types"]


# --- Scoping ----------------------------------------------------------------


def test_a_scoped_report_only_covers_that_resource_type():
    scoped = rule_diagnosis.diagnose(resource_type="cluster")
    assert scoped["total"] < rule_diagnosis.diagnose()["total"]
    for rule in scoped["rules"]:
        assert rule["resource_type"] == "cluster"


def test_a_rule_defined_twice_is_read_in_full():
    """`violations.x` can appear more than once; that is how Rego says "or".

    The autotermination rule is written that way. Reading only the first block
    would miss fields the second one reads and mislabel the rule.
    """
    content = (
        "violations.thing contains msg if {\n"
        "\tinput.resource.first\n"
        "}\n"
        "\n"
        "violations.thing contains msg if {\n"
        "\tinput.resource.second\n"
        "}\n"
    )
    body = rule_diagnosis._rule_body(content, "thing")
    assert "first" in body and "second" in body


def test_an_unlocatable_rule_falls_back_to_the_whole_file():
    """Better to blame discovery than to call a rule broken on no evidence."""
    content = "violations.other contains msg if {\n\tinput.resource.x\n}\n"
    assert rule_diagnosis._rule_body(content, "missing") == content
