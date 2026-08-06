"""The vocabulary a policy is allowed to use.

The bug this guards against does not look like a bug. A Rego rule that reads a
field discovery never collected does not fail — it never matches, so the rule
never fires, and every resource of that type is reported compliant forever. It
is a false negative that is invisible from the outside and permanent.
"""
import os

import pytest

from app.providers.databricks.handlers import HANDLER_REGISTRY
from app.services import resource_schema


# --- The catalogue ----------------------------------------------------------


def test_every_handler_declares_its_fields():
    """An undeclared handler silently opts out of the check for its whole
    resource type, which is the one place nobody would look for the gap."""
    missing = [
        name
        for name, handler in HANDLER_REGISTRY.items()
        if not getattr(handler, "discovered_fields", None)
    ]

    assert missing == [], f"These handlers declare no fields: {missing}"


def test_every_handler_declares_the_universal_fields():
    """id, type, name, owner and tags are set by every handler, and policies
    assume they exist everywhere."""
    for name in HANDLER_REGISTRY:
        fields = resource_schema.resource_fields(name)
        for required in ("id", "type", "name", "owner", "tags"):
            assert required in fields, f"{name} is missing {required}"


def test_the_common_list_stays_minimal():
    """The temptation is to add anything a policy might want to this list, and
    a field listed but not collected is exactly the trap the module exists to
    catch. `idle_days` lived here and was collected by nothing."""
    assert set(resource_schema.COMMON_RESOURCE_FIELDS) == {
        "id",
        "type",
        "name",
        "owner",
        "tags",
    }


def test_a_handler_description_beats_the_generic_one():
    """"Always empty, this API has no tags" is what stops someone writing a
    tagging rule for a type that cannot have tags."""
    assert "no tags" in resource_schema.resource_fields("app")["tags"].lower()


def test_the_catalogue_covers_every_registered_type():
    catalogue = resource_schema.catalog()
    covered = {t["resource_type"] for t in catalogue["resource_types"]}

    assert covered == set(HANDLER_REGISTRY)


# --- Finding references -----------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "input.resource.idle_hours > 24",
        'input.resource["idle_hours"]',
        'object.get(input.resource, "idle_hours", 0)',
        "  x := input.resource.idle_hours\n",
    ],
)
def test_it_finds_a_field_however_it_is_written(snippet):
    """All three spellings appear in the shipped policies, and object.get with
    a default is the most common — and the most dangerous, because the default
    is what makes the rule quietly never fire."""
    assert "idle_hours" in resource_schema.referenced_fields(snippet)


def test_it_does_not_confuse_workspace_fields_for_resource_fields():
    fields = resource_schema.referenced_fields(
        "input.workspace.environment == 'prod'\ninput.resource.state == 'RUNNING'"
    )

    assert fields == ["state"]


# --- The check ---------------------------------------------------------------


def test_it_flags_a_field_the_handler_never_collects():
    """The exact case: an idleness rule for apps, whose handler collects no
    activity data at all."""
    problems = resource_schema.check_fields(
        "violations.stale contains msg if { input.resource.idle_hours > 24 }", "app"
    )

    assert len(problems) == 1
    assert problems[0]["field"] == "idle_hours"
    # The message has to say what goes wrong, not just that something is wrong.
    # "Unknown field" would read as a typo rather than a dead rule.
    assert "never fire" in problems[0]["message"]


def test_it_says_what_is_available_instead():
    problems = resource_schema.check_fields("input.resource.nonsense", "cluster")

    assert "policy_id" in problems[0]["message"]


def test_a_collected_field_is_not_flagged():
    content = """
    input.resource.policy_id
    input.resource.autotermination_minutes
    object.get(input.resource, "tags", {})
    """

    assert resource_schema.check_fields(content, "cluster") == []


def test_an_unknown_resource_type_flags_nothing():
    """Flagging every field of a type we know nothing about would train people
    to ignore the warning, and an ignored warning is worse than none."""
    assert resource_schema.check_fields("input.resource.whatever", "not_a_type") == []
    assert resource_schema.check_fields("input.resource.whatever", None) == []


def test_the_object_get_default_does_not_excuse_a_missing_field():
    """`object.get(input.resource, "idle_days", 0)` reads as defensive and is
    the worst version: the default silently stands in for data that is never
    there, so the rule evaluates cleanly and never fires."""
    problems = resource_schema.check_fields(
        'idle := object.get(input.resource, "idle_days", 0)', "app"
    )

    assert [p["field"] for p in problems] == ["idle_days"]


# --- The prompt --------------------------------------------------------------


def test_the_prompt_scopes_to_one_type_when_asked():
    one = resource_schema.prompt_summary("cluster")

    assert "input.resource.policy_id" in one
    assert "lakebase_instance" not in one


def test_the_prompt_says_the_list_is_exhaustive():
    """Without this the model treats the list as examples and invents the rest,
    which is the whole failure being prevented."""
    assert "NOT collected" in resource_schema.prompt_summary("cluster")


# --- The shipped policies ----------------------------------------------------


def policies_dir() -> str:
    """backend/policies, four levels up from tests/unit/services/."""
    here = os.path.abspath(__file__)
    backend = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(here)))
    )
    return os.path.join(backend, "policies")


def test_the_shipped_policies_are_measured_not_asserted():
    """A record of where the shipped policies stand, not a gate.

    Thirteen of them reference fields no handler collects — ten different
    policies have a staleness rule keyed on ``idle_days``, which nothing has
    ever produced. Those rules have never fired and never will.

    Turning that into a failing assertion today would leave the suite red with
    no way to make it green short of a discovery rewrite, so this pins the
    shape of the problem instead: the checker must find real problems in real
    policies, and the count is here to be driven down deliberately.
    """
    from app.services import policy_registry

    flagged = {}
    for policy in policy_registry.load_policies():
        path = os.path.join(policies_dir(), policy.name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            problems = resource_schema.check_fields(handle.read(), policy.resource_type)
        if problems:
            flagged[policy.name] = sorted(p["field"] for p in problems)

    # The checker works against real policies rather than only against the
    # examples in this file.
    assert flagged, "The field checker found nothing in any shipped policy."

    # The one that proves the point. Nine policies gated on `idle_days`, a
    # field nothing collected. Three of them now have it: a cluster's idle time
    # comes from `terminated_time`, a job's from its last run, a table's from
    # `last_altered`.
    #
    # The six left are not waiting on a collector. Apps, dashboards, Genie
    # spaces, Lakebase instances, service principals and warehouses publish when
    # they were changed and never when they were used, so the only real answer
    # is the system tables — and reading those needs a grant only a metastore
    # admin can make. This number should drop when that grant happens, and not
    # before.
    idle = [name for name, fields in flagged.items() if "idle_days" in fields]
    assert sorted(idle) == [
        "apps.rego",
        "dashboards.rego",
        "genie_spaces.rego",
        "lakebase_instances.rego",
        "service_principals.rego",
        "sql_warehouses.rego",
    ], idle
