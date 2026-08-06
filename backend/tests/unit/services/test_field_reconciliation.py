"""Checking the field catalogue against the estate it claims to describe.

`discovered_fields` is the root of every other honesty check here, and it is a
hand-written docstring. These tests are about the three ways it can be wrong
while everything downstream still reports success.
"""
from __future__ import annotations

from app.services import field_reconciliation as fr


def cluster(**over):
    base = {
        "id": "0101-a",
        "type": "cluster",
        "name": "analytics",
        "owner": "someone@company.com",
        "state": "RUNNING",
        "cluster_type": "interactive",
        "access_mode": "USER_ISOLATION",
        "autotermination_minutes": 30,
        "policy_id": "E01",
        "num_workers": 2,
        "autoscale_max_workers": None,
        "idle_days": 0,
        "tags": {"cost-center": "CC-1"},
    }
    base.update(over)
    return base


# --- Observation ------------------------------------------------------------


def test_observation_counts_presence_and_population_separately():
    """A field that is always set and always empty is the subtle failure. It
    has to be distinguishable from one that is genuinely absent."""
    seen = fr.observe([cluster(tags={}), cluster(tags={})])
    stats = seen["resource_types"]["cluster"]["fields"]["tags"]
    assert stats["present"] == 2
    assert stats["populated"] == 0


def test_zero_is_a_value_not_an_absence():
    """`autotermination_minutes: 0` is a real, dangerous setting and the rule
    that catches it depends on this. Treating falsey as empty would hide it."""
    seen = fr.observe([cluster(autotermination_minutes=0)])
    stats = seen["resource_types"]["cluster"]["fields"]["autotermination_minutes"]
    assert stats["populated"] == 1


def test_no_resource_survives_into_the_aggregate():
    """The output is persisted on every run and shipped to a browser. It has to
    be counts, not an estate inventory."""
    seen = fr.observe([cluster(name="secret-project", owner="ceo@company.com")])
    blob = repr(seen)
    assert "secret-project" not in blob
    assert "ceo@company.com" not in blob


def test_identifying_fields_never_have_their_values_recorded():
    """The cardinality cap alone is not enough protection: in a workspace with
    three clusters, `owner` is low-cardinality and would be captured."""
    seen = fr.observe([cluster()])
    fields = seen["resource_types"]["cluster"]["fields"]
    for identifying in ("id", "name", "owner"):
        assert fields[identifying]["values"] == []


def test_an_enum_like_field_keeps_its_values():
    """This is what makes the impossible-comparison check possible."""
    seen = fr.observe([cluster(), cluster(access_mode="SINGLE_USER")])
    values = seen["resource_types"]["cluster"]["fields"]["access_mode"]["values"]
    assert values == ["SINGLE_USER", "USER_ISOLATION"]


def test_a_high_cardinality_field_stops_being_recorded():
    """Past a point the field is free text, and a literal being absent from the
    set stops being evidence of anything."""
    resources = [cluster(state=f"STATE_{i}") for i in range(fr._MAX_DISTINCT_VALUES + 5)]
    stats = fr.observe(resources)["resource_types"]["cluster"]["fields"]["state"]
    assert stats["too_many_values"]
    assert stats["values"] == []


# --- Reconciliation ---------------------------------------------------------


def test_a_declared_field_that_is_never_emitted_is_reported():
    """The disguised version of the original bug. The catalogue says the field
    is collected, so `rule_diagnosis` calls every rule reading it *working* —
    this is the only check that can see otherwise."""
    resources = [cluster() for _ in range(5)]
    for resource in resources:
        del resource["policy_id"]

    report = fr.reconcile(fr.observe(resources))
    kinds = {(f["kind"], f["field"]) for f in report["findings"]}
    assert ("never_emitted", "policy_id") in kinds


def test_a_field_that_is_always_empty_is_inert_rather_than_drift():
    """It is worth saying that no rule reading `tags` can fire here. It is not
    worth calling it a bug: the catalogue and the estate agree, and a workspace
    where nobody tags anything looks identical to an API that has no tags."""
    report = fr.reconcile(fr.observe([cluster(tags={}) for _ in range(5)]))
    assert ("tags") in {f["field"] for f in report["inert"]}
    assert "tags" not in {f["field"] for f in report["findings"]}


def test_a_nullable_field_on_an_unused_feature_is_not_drift():
    """Every cluster has a fixed worker count, so `autoscale_max_workers` is
    null on all of them. The handler is behaving correctly and reporting it as
    drift would train people to ignore the report."""
    report = fr.reconcile(fr.observe([cluster() for _ in range(5)]))
    assert "autoscale_max_workers" in {f["field"] for f in report["inert"]}
    assert "autoscale_max_workers" not in {f["field"] for f in report["findings"]}


def test_an_undeclared_field_is_reported():
    report = fr.reconcile(fr.observe([cluster(surprise="hello") for _ in range(5)]))
    kinds = {(f["kind"], f["field"]) for f in report["findings"]}
    assert ("undeclared", "surprise") in kinds


def test_a_clean_estate_produces_no_drift():
    """The catalogue is right about clusters, so there is nothing to correct."""
    report = fr.reconcile(fr.observe([cluster() for _ in range(5)]))
    cluster_findings = [f for f in report["findings"] if f["resource_type"] == "cluster"]
    assert cluster_findings == []


def test_a_resource_type_with_nothing_discovered_is_inconclusive_not_broken():
    """A workspace with no Genie spaces must not report every Genie field as a
    broken declaration. That would bury the real findings on the first run."""
    report = fr.reconcile(fr.observe([cluster()]))
    genie = next(t for t in report["resource_types"] if t["resource_type"] == "genie_space")
    assert genie["scanned"] is False
    assert genie["never_emitted"] == []


def test_a_single_resource_is_marked_inconclusive():
    """One cluster that happens not to set a field is not evidence the handler
    never sets it."""
    report = fr.reconcile(fr.observe([cluster()]), min_resources=5)
    entry = next(t for t in report["resource_types"] if t["resource_type"] == "cluster")
    assert entry["conclusive"] is False


# --- Comparisons against literals -------------------------------------------


def test_the_shapes_a_comparison_is_written_in_are_all_found():
    content = """
    violations.a contains msg if { input.resource.access_mode == "shared" }
    violations.b contains msg if { object.get(input.resource, "state", "") == "GONE" }
    violations.c contains msg if { object.get(input.resource, "storage_type", "") in {"dbfs", "local_volume"} }
    violations.d contains msg if { input.resource.cluster_type in {"batch"} }
    """
    found = fr.compared_literals(content)
    assert found["access_mode"] == {"shared"}
    assert found["state"] == {"GONE"}
    assert found["storage_type"] == {"dbfs", "local_volume"}
    assert found["cluster_type"] == {"batch"}


def test_a_comparison_no_resource_can_satisfy_is_reported():
    """This is SEC-CLU-001 exactly: the policy wants "shared", the SDK has never
    emitted it, and the rule looked like a clean pass for its whole life."""
    sources = {
        "cluster": {
            "clusters.rego": 'violations.x contains msg if { input.resource.access_mode == "shared" }'
        }
    }
    report = fr.reconcile(
        fr.observe([cluster() for _ in range(5)]), policy_sources=sources
    )
    impossible = [f for f in report["findings"] if f["kind"] == "impossible_comparison"]
    assert len(impossible) == 1
    assert impossible[0]["field"] == "access_mode"
    assert impossible[0]["compared_against"] == ["shared"]
    assert "USER_ISOLATION" in impossible[0]["observed_values"]


def test_a_comparison_that_matches_something_is_left_alone():
    sources = {
        "cluster": {
            "clusters.rego": 'violations.x contains msg if { input.resource.access_mode == "USER_ISOLATION" }'
        }
    }
    report = fr.reconcile(
        fr.observe([cluster() for _ in range(5)]), policy_sources=sources
    )
    assert not [f for f in report["findings"] if f["kind"] == "impossible_comparison"]


def test_a_set_with_one_reachable_member_is_not_impossible():
    """A rule listing four states and matching one of them is working as
    intended. Only a comparison with no reachable branch is a bug."""
    sources = {
        "cluster": {
            "c.rego": 'violations.x contains msg if { input.resource.access_mode in {"NONE", "USER_ISOLATION"} }'
        }
    }
    report = fr.reconcile(
        fr.observe([cluster() for _ in range(5)]), policy_sources=sources
    )
    assert not [f for f in report["findings"] if f["kind"] == "impossible_comparison"]


def test_an_unbounded_field_yields_no_verdict():
    """We stopped recording values, so absence from the set proves nothing and
    claiming otherwise would be a false accusation."""
    resources = [cluster(state=f"S{i}") for i in range(fr._MAX_DISTINCT_VALUES + 5)]
    sources = {
        "cluster": {"c.rego": 'violations.x contains msg if { input.resource.state == "NOPE" }'}
    }
    report = fr.reconcile(fr.observe(resources), policy_sources=sources)
    assert not [f for f in report["findings"] if f["kind"] == "impossible_comparison"]


def test_an_identifying_field_is_never_judged_on_its_values():
    """`owner` has no recorded values by design, so a comparison against it
    cannot be called impossible however it is written."""
    sources = {
        "cluster": {"c.rego": 'violations.x contains msg if { input.resource.owner == "nobody" }'}
    }
    report = fr.reconcile(
        fr.observe([cluster() for _ in range(5)]), policy_sources=sources
    )
    assert not [f for f in report["findings"] if f["kind"] == "impossible_comparison"]
