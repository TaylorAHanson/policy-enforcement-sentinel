"""Write the starting fixture set for every resource type.

One-shot authoring aid, kept because it documents the intent behind the files it
produced: every resource here is built only from fields the corresponding
handler actually collects, with values that handler can actually emit. That
constraint is the whole point. A fixture is worthless as evidence if it feeds
the policies data production never supplies — the rule passes the test and stays
dead in the estate, which is precisely the failure this repository already had.

Re-running overwrites the files it owns. Hand-edited fixtures should be renamed
so they are not on this list.

Run with `python -m scripts.generate_fixtures` from `backend/`.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from app.services import resource_schema

OUT = os.path.join("fixtures", "synthetic")

COST_TAGS = {"cost-center": "CC-4100", "owner": "data-platform@company.com"}


def app(**over):
    return {"id": "sales-forecast", "name": "sales-forecast", "type": "app",
            "owner": "analytics@company.com", "state": "RUNNING",
            "url": "https://example.databricksapps.com",
            "shared_with": ["analytics-team"], "tags": {}, **over}


def cluster(**over):
    """A cluster as `ClusterResourceHandler.discover` would return one.

    `idle_days` is zero because a running cluster is in use now. It comes from
    `terminated_time` once the cluster stops. `access_mode` carries an SDK
    data-security-mode value rather than the literal "shared" the policy looks
    for, which is why SEC-CLU-001 cannot fire.
    """
    return {"id": "0101-000000-aaaa", "name": "analytics", "type": "cluster",
            "owner": "analytics@company.com", "state": "RUNNING",
            "cluster_type": "interactive", "access_mode": "USER_ISOLATION",
            "autotermination_minutes": 30, "policy_id": "E0123456789",
            "num_workers": 2, "autoscale_max_workers": None, "idle_days": 0,
            "tags": dict(COST_TAGS), **over}


def dashboard(**over):
    return {"id": "dsh-001", "name": "Revenue overview", "type": "dashboard",
            "owner": "analytics@company.com", "uses_embedded_credentials": False,
            "is_published": True, "shared_with": ["data-analysts"], "tags": {},
            **over}


def dataset(**over):
    return {"id": "prod.sales.orders", "name": "orders", "type": "dataset",
            "owner": "data-platform@company.com", "catalog": "prod",
            "schema": "sales", "table_type": "MANAGED", "has_description": True,
            "certified": False, "quarantined": False,
            "last_altered": "2026-07-01T00:00:00Z", "idle_days": 5,
            "all_columns_have_descriptions": True, "tags": {}, **over}


def genie(**over):
    return {"id": "gs-001", "name": "Sales assistant", "type": "genie_space",
            "owner": "analytics@company.com", "description": "Answers sales questions.",
            "shared_with": ["sales-team"], "tags": {}, **over}


def job(**over):
    """`failed_consecutively_days` is absent by default, which is what a job
    whose last run succeeded looks like — the handler omits it rather than
    writing a zero."""
    return {"id": "884422", "name": "nightly-load", "type": "job",
            "owner": "svc-etl@company.com", "schedule": "0 0 2 * * ?",
            "paused": False, "max_concurrent_runs": 1,
            "owner_type": "service_principal", "idle_days": 1,
            "tags": {}, **over}


def lakebase(**over):
    return {"id": "lb-prod", "name": "lb-prod", "type": "lakebase_instance",
            "owner": "data-platform@company.com", "state": "AVAILABLE",
            "capacity": "CU_2", "capacity_units": 2, "stopped": False,
            "retention_window_days": 14, "tags": {}, **over}


def notebook(**over):
    return {"id": "/Shared/etl/bronze", "name": "bronze", "type": "notebook",
            "owner": "data-platform@company.com",
            "path": "/Shared/etl/bronze", "language": "PYTHON",
            "in_shared": True, "in_git_folder": True, "is_scheduled": False,
            "tags": {}, **over}


def pipeline(**over):
    return {"id": "pl-001", "name": "bronze-to-silver", "type": "pipeline",
            "owner": "svc-etl@company.com", "serverless": True,
            "continuous": False, "channel": "CURRENT", "development": False,
            "owner_type": "service_principal", "target_catalog": "prod",
            "metadata_complete": True, "tags": {}, **over}


def endpoint(**over):
    return {"id": "fraud-scorer", "name": "fraud-scorer",
            "type": "model_serving_endpoint", "owner": "ml@company.com",
            "endpoint_type": "EXTERNAL_MODEL", "ready": "READY",
            "scale_to_zero": True, "inference_logging": True,
            "shared_with": ["ml-consumers"],
            "tags": {"cost_center": "CC-4100"}, **over}


def principal(**over):
    return {"id": "sp-99", "name": "svc-etl", "type": "service_principal",
            "owner": "svc-etl", "active": True, "application_id": "abc-123",
            "entitlements": ["allow-cluster-create"], "roles": [],
            "tags": {}, **over}


def warehouse(**over):
    return {"id": "wh-01", "name": "analytics-wh", "type": "sql_warehouse",
            "owner": "data-platform@company.com", "state": "RUNNING",
            "auto_stop_mins": 20, "max_num_clusters": 4, "warehouse_type": "PRO",
            "serverless": True, "tags": dict(COST_TAGS), **over}


def volume(**over):
    return {"id": "prod.raw.landing", "name": "landing", "type": "storage",
            "owner": "data-platform@company.com", "storage_type": "MANAGED",
            "catalog": "prod", "schema": "raw", "tags": {}, **over}


#: name -> (description, workspace, environment, resource, fires, passes)
FIXTURES: Dict[str, Any] = {}


def add(name, description, resource, *, fires=(), passes=(), allowlist=None,
        workspace="synthetic-prod", environment="prod", ws_type="enterprise"):
    FIXTURES[name] = {
        "description": description,
        "workspace": workspace,
        "workspace_type": ws_type,
        "environment": environment,
        "source": "authored",
        "resource": resource,
        "expect": {"fires": sorted(fires), "passes": sorted(passes)},
    }
    if allowlist:
        FIXTURES[name]["allowlist_records"] = allowlist


CLUSTER_RULES = ["SEC-CLU-001", "CTL-CLU-002", "CST-CLU-003", "CST-CLU-004",
                 "CST-CLU-005"]


def others(rules, firing):
    """Everything in `rules` that is not firing, i.e. the expected passes."""
    return [r for r in rules if r not in firing]


# --- Clusters ----------------------------------------------------------------
#
# Rewritten from the originals, which set `idle_days` on every cluster and
# `access_mode: "shared"` on two. Neither value can come out of discovery, so
# those fixtures were evidence about an estate that does not exist -- and one of
# them asserted that an idleness rule fires, which it cannot.

add("cluster_compliant",
    "A cluster that meets every rule it is possible to meet. The one fixture "
    "whose failure means a policy has widened rather than narrowed.",
    cluster(),
    passes=CLUSTER_RULES)

add("cluster_no_compute_policy",
    "A cluster created without a compute policy. CTL-CLU-002 is the rule, and "
    "the policy_id arrives as JSON null rather than being absent -- which is "
    "what `not input.resource.policy_id` failed to detect before common.is_set "
    "existed. This is the regression test for that.",
    cluster(policy_id=None),
    fires=["CTL-CLU-002"], passes=others(CLUSTER_RULES, ["CTL-CLU-002"]))

add("cluster_untagged",
    "No cost tags, so the spend cannot be attributed and there is nobody to "
    "notify.",
    cluster(tags={}),
    fires=["CST-CLU-003"], passes=others(CLUSTER_RULES, ["CST-CLU-003"]))

add("cluster_no_autotermination",
    "An interactive cluster with autotermination disabled, which is the one "
    "that quietly bills all weekend.",
    cluster(autotermination_minutes=None),
    fires=["CST-CLU-004"], passes=others(CLUSTER_RULES, ["CST-CLU-004"]))

add("cluster_autotermination_zero",
    "The other way discovery reports a disabled autotermination. CST-CLU-004 "
    "originally tested only for 0 and let every null-valued cluster through, so "
    "this fixture and the one above have to fire together or the fix regressed.",
    cluster(autotermination_minutes=0),
    fires=["CST-CLU-004"], passes=others(CLUSTER_RULES, ["CST-CLU-004"]))

add("cluster_job_cluster_needs_no_autotermination",
    "A job cluster with no autotermination, which is correct -- it dies with "
    "its run. CST-CLU-004 is scoped to interactive compute, and this is the "
    "pair that proves the scoping is real.",
    cluster(cluster_type="job", autotermination_minutes=None),
    passes=CLUSTER_RULES)

add("cluster_neglected",
    "No compute policy, no tags, no autotermination. Three rules at once, which "
    "is what a genuinely abandoned cluster looks like in the data we actually "
    "have about it.",
    cluster(policy_id=None, tags={}, autotermination_minutes=None),
    fires=["CTL-CLU-002", "CST-CLU-003", "CST-CLU-004"],
    passes=["SEC-CLU-001", "CST-CLU-005"])

add("cluster_terminated_months_ago",
    "A cluster that stopped 120 days ago. CST-CLU-005 fires on `idle_days`, "
    "which the handler now derives from `terminated_time` -- the one resource "
    "type whose idleness the workspace API states outright rather than implying "
    "from an edit timestamp.",
    cluster(state="TERMINATED", idle_days=120),
    fires=["CST-CLU-005"], passes=others(CLUSTER_RULES, ["CST-CLU-005"]))

add("cluster_idle_boundary",
    "Exactly thirty days since termination. CST-CLU-005 fires above thirty, not "
    "at it.",
    cluster(state="TERMINATED", idle_days=30),
    passes=CLUSTER_RULES)

add("cluster_shared_access_mode_in_prod",
    "A production cluster in a mode with no separation between its users. The "
    "rule used to test `access_mode == \"shared\"`, a literal the SDK has never "
    "emitted for any cluster, so it had never once fired.",
    cluster(access_mode="LEGACY_SINGLE_USER_STANDARD"),
    fires=["SEC-CLU-001"], passes=others(CLUSTER_RULES, ["SEC-CLU-001"]))

add("cluster_no_isolation_in_prod",
    "The bluntest form of the same problem: no security mode at all.",
    cluster(access_mode="NONE"),
    fires=["SEC-CLU-001"], passes=others(CLUSTER_RULES, ["SEC-CLU-001"]))

add("cluster_user_isolation_is_not_the_problem",
    "USER_ISOLATION is what the UI calls Standard, and it is the mode this rule "
    "wants people to move *to*. It is also the mode most likely to be read as "
    "\"shared\" by someone skimming, so this fixture exists to stop the next "
    "person widening the rule to include it.",
    cluster(access_mode="USER_ISOLATION"),
    passes=CLUSTER_RULES)

add("cluster_waived_by_pattern",
    "A cluster with no compute policy in a workspace where CTL-CLU-002 has been "
    "waived for the whole class. The rule still evaluates and still fails; the "
    "exception is what turns the action into SKIPPED_ALLOWLIST, and the other "
    "rules are untouched.",
    cluster(policy_id=None, tags={}),
    fires=["CTL-CLU-002", "CST-CLU-003"],
    passes=["SEC-CLU-001", "CST-CLU-004", "CST-CLU-005"],
    allowlist=[{
        "id": "synthetic-pattern-1",
        "match_type": "pattern",
        "resource_type": "cluster",
        "rule_id": "CTL-CLU-002",
        "status": "approved",
        "justification": "Migration in progress, agreed with the platform team.",
        "expires_at": None,
    }])


# --- Apps --------------------------------------------------------------------
add("app_in_enterprise_prod",
    "An app in enterprise production. SEC-APP-001 fires because no risk review "
    "is recorded, and CST-APP-004 fires because the Apps API exposes no tags at "
    "all -- so this pair is what every production app looks like today.",
    app(),
    fires=["SEC-APP-001", "CST-APP-004"], passes=["CST-APP-003", "SEC-APP-002"])

add("app_in_dev",
    "The same app outside production. SEC-APP-001 is scoped to enterprise prod, "
    "so this is the pair proving that condition is real rather than decorative.",
    app(), environment="dev", workspace="synthetic-dev",
    fires=["CST-APP-004"], passes=["SEC-APP-001", "CST-APP-003", "SEC-APP-002"])

add("app_shared_with_everyone",
    "An app shared with the whole workspace. Everyone who can open it inherits "
    "the effective permissions of its service principal, which is what makes "
    "SEC-APP-002 a security rule rather than a tidiness one.",
    app(shared_with=["ALL_USERS"]),
    fires=["SEC-APP-001", "SEC-APP-002", "CST-APP-004"], passes=["CST-APP-003"])

# --- Dashboards --------------------------------------------------------------
add("dashboard_embedded_and_public",
    "A published dashboard that embeds its publisher's credentials and is shared "
    "with everyone. Both halves of SEC-DSH-001 are fields the handler really "
    "collects, which makes this the one dashboard rule that can fire in anger.",
    dashboard(uses_embedded_credentials=True, shared_with=["ALL_USERS"]),
    fires=["SEC-DSH-001"], passes=["CTL-DSH-002", "CTL-DSH-003"])

add("dashboard_embedded_but_not_shared",
    "Embedded credentials alone are not the problem. Removing the broad share "
    "must clear SEC-DSH-001, or the rule is really just 'is it published'.",
    dashboard(uses_embedded_credentials=True),
    passes=["SEC-DSH-001", "CTL-DSH-002", "CTL-DSH-003"])

add("dashboard_shared_without_embedding",
    "The other half. Shared with everyone but querying as the reader, which is "
    "the arrangement SEC-DSH-001 is explicitly not about.",
    dashboard(shared_with=["ALL_USERS"]),
    passes=["SEC-DSH-001", "CTL-DSH-002", "CTL-DSH-003"])

add("dashboard_published_without_owner",
    "A published dashboard whose creator came back empty. This rule needed both "
    "fixes to work: `is_published` had to start being collected, and the owner "
    "check had to stop testing for a missing key.",
    dashboard(owner="", is_published=True),
    fires=["CTL-DSH-002"], passes=["SEC-DSH-001", "CTL-DSH-003"])

add("dashboard_draft_without_owner_is_not_flagged",
    "The same unowned dashboard, never published. CTL-DSH-002 is about things "
    "people are looking at, not about drafts, and this is the pair that keeps "
    "the `is_published` half of it load-bearing.",
    dashboard(owner="", is_published=False),
    passes=["SEC-DSH-001", "CTL-DSH-002", "CTL-DSH-003"])

# --- Datasets ----------------------------------------------------------------
GOV_TAGS = {"owner_group": "data-platform", "approver_group": "governance",
            "domain": "sales", "slo_sla": "99.9",
            "data_classification": "internal", "reliability_window": "7d"}

add("dataset_fully_tagged",
    "Every governance tag present. CTL-DST-001 still fires: it reads `comment`, "
    "which discovery does not collect, so no dataset can ever satisfy it.",
    dataset(tags=dict(GOV_TAGS)),
    fires=["CTL-DST-001"],
    passes=["CTL-DST-003", "SEC-DST-004", "CTL-DST-007", "CTL-DST-009",
            "CTL-DST-002", "CTL-DST-008", "SEC-DST-005", "SEC-DST-006",
            "CTL-DST-010"])

add("dataset_untagged",
    "A table with no governance tags at all -- the common case in a workspace "
    "nobody has swept. Four separate rules fire on the same resource.",
    dataset(),
    fires=["CTL-DST-001", "CTL-DST-003", "SEC-DST-004", "CTL-DST-009"],
    passes=["CTL-DST-002", "CTL-DST-007", "CTL-DST-008", "SEC-DST-005",
            "SEC-DST-006", "CTL-DST-010"])

add("dataset_without_owner",
    "A dataset whose owner came back empty. This used to be the fixture "
    "recording that CTL-DST-007 could not fire -- the rule was "
    "`not input.resource.owner`, and Rego treats an empty string as a value "
    "rather than as absence. `common.no_owner` now recognises all four shapes "
    "absence arrives in.",
    dataset(owner="", tags=dict(GOV_TAGS)),
    fires=["CTL-DST-001", "CTL-DST-007"],
    passes=["CTL-DST-003", "SEC-DST-004", "CTL-DST-009", "CTL-DST-002",
            "CTL-DST-008", "SEC-DST-005", "SEC-DST-006", "CTL-DST-010"])

add("dataset_owner_recorded_as_unknown",
    "The shape absence actually takes in production. The handlers write the "
    "literal \"unknown\" when the API named nobody, so a rule that only checked "
    "for a missing key saw a perfectly good owner on every unowned table in the "
    "estate. This is the fixture that matters most of the five.",
    dataset(owner="unknown", tags=dict(GOV_TAGS)),
    fires=["CTL-DST-001", "CTL-DST-007"],
    passes=["CTL-DST-003", "SEC-DST-004", "CTL-DST-009", "CTL-DST-002",
            "CTL-DST-008", "SEC-DST-005", "SEC-DST-006", "CTL-DST-010"])

add("dataset_undescribed_columns",
    "A table where some column carries no comment. The count comes from "
    "`information_schema.columns`, aggregated in the warehouse rather than "
    "pulled row by row.",
    dataset(tags=dict(GOV_TAGS), all_columns_have_descriptions=False),
    fires=["CTL-DST-001", "CTL-DST-002"],
    passes=["CTL-DST-003", "SEC-DST-004", "CTL-DST-007", "CTL-DST-008",
            "CTL-DST-009", "SEC-DST-005", "SEC-DST-006", "CTL-DST-010"])

add("dataset_not_written_in_months",
    "No writes for 120 days, from `last_altered`. Worth being precise about "
    "what this does and does not say: it is silence from upstream, not "
    "disuse. A reference table read by every query and updated once a year "
    "looks exactly like this, which is why the rule warns rather than acts.",
    dataset(tags=dict(GOV_TAGS), idle_days=120),
    fires=["CTL-DST-001", "CTL-DST-010"],
    passes=["CTL-DST-003", "SEC-DST-004", "CTL-DST-002", "CTL-DST-007",
            "CTL-DST-008", "CTL-DST-009", "SEC-DST-005", "SEC-DST-006"])

# --- Genie spaces ------------------------------------------------------------
add("genie_space_in_enterprise_prod",
    "A Genie space in enterprise production. Both firing rules are unconditional "
    "in practice: neither a risk review nor a curated table set is collected, so "
    "every space in prod looks like this.",
    genie(),
    fires=["SEC-GEN-001", "CTL-GEN-003"], passes=["CST-GEN-004", "SEC-GEN-002"])

add("genie_space_in_dev",
    "Outside enterprise production the risk-review rule is out of scope, which "
    "leaves the curated-tables rule on its own.",
    genie(), environment="dev", workspace="synthetic-dev",
    fires=["CTL-GEN-003"],
    passes=["SEC-GEN-001", "CST-GEN-004", "SEC-GEN-002"])

add("genie_space_shared_with_everyone",
    "A Genie space open to the whole workspace. Genie answers questions against "
    "whatever tables the space is bound to, so a broad share is a broad grant "
    "on the data behind it.",
    genie(shared_with=["ALL_USERS"]),
    fires=["SEC-GEN-001", "SEC-GEN-002", "CTL-GEN-003"], passes=["CST-GEN-004"])

# --- Jobs --------------------------------------------------------------------
add("job_untagged_in_prod",
    "A production job with no cost tags and, as far as discovery can tell, no "
    "failure notifications -- the latter is never collected, so CTL-JOB-005 "
    "fires for every production job today.",
    job(),
    fires=["CST-JOB-004", "CTL-JOB-005"],
    passes=["CTL-JOB-002", "SEC-JOB-001", "CST-JOB-003"])

add("job_tagged_in_prod",
    "The same job with cost tags. CST-JOB-004 clears; CTL-JOB-005 cannot, which "
    "is what makes the difference between the two visible.",
    job(tags=dict(COST_TAGS)),
    fires=["CTL-JOB-005"],
    passes=["CST-JOB-004", "CTL-JOB-002", "SEC-JOB-001", "CST-JOB-003"])

add("job_in_dev",
    "Outside production neither production-scoped rule applies.",
    job(tags=dict(COST_TAGS)), environment="dev", workspace="synthetic-dev",
    passes=["CST-JOB-004", "CTL-JOB-005", "CTL-JOB-002", "SEC-JOB-001",
            "CST-JOB-003"])

add("job_running_as_a_person_in_prod",
    "A production job that runs as its author. `owner_type` comes from the "
    "job's run-as setting rather than its creator, which matters -- a job "
    "somebody built and correctly pointed at a service principal is fine, and "
    "this rule must not flag it.",
    job(owner_type="user", owner="someone@company.com", tags=dict(COST_TAGS)),
    fires=["SEC-JOB-001", "CTL-JOB-005"],
    passes=["CST-JOB-004", "CTL-JOB-002", "CST-JOB-003"])

add("job_created_by_a_person_but_running_as_a_principal",
    "The pair for the fixture above. Same human creator, run-as set properly, "
    "and SEC-JOB-001 stays quiet. If this one ever fires, the handler has gone "
    "back to reading `creator_user_name`.",
    job(owner="someone@company.com", tags=dict(COST_TAGS)),
    fires=["CTL-JOB-005"],
    passes=["SEC-JOB-001", "CST-JOB-004", "CTL-JOB-002", "CST-JOB-003"])

add("job_failing_for_six_weeks",
    "Every run has failed for 42 days. The streak is measured from the oldest "
    "unbroken failure, so a job that failed for a month and was then fixed "
    "reports nothing at all.",
    job(failed_consecutively_days=42, tags=dict(COST_TAGS)),
    fires=["CTL-JOB-002", "CTL-JOB-005"],
    passes=["SEC-JOB-001", "CST-JOB-004", "CST-JOB-003"])

add("job_not_run_in_four_months",
    "A scheduled job that has not run in 120 days -- paused, or scheduled for "
    "a date that never comes round. Absent from this: a job that has never run "
    "at all, which reports no `idle_days` rather than its age.",
    job(idle_days=120, tags=dict(COST_TAGS)),
    fires=["CST-JOB-003", "CTL-JOB-005"],
    passes=["SEC-JOB-001", "CST-JOB-004", "CTL-JOB-002"])

# --- Lakebase ----------------------------------------------------------------
add("lakebase_in_prod",
    "A production Lakebase instance with a fortnight of point-in-time recovery. "
    "CTL-LKB-002 used to fire here and on every other instance, because it read "
    "`retention_days` while the handler collects `retention_window_days` -- so "
    "the value it compared was always the default zero.",
    lakebase(),
    passes=["CTL-LKB-002", "CTL-LKB-004", "CST-LKB-001", "CST-LKB-003"])

add("lakebase_short_retention",
    "Three days of recovery window in production, which is what CTL-LKB-002 is "
    "actually for.",
    lakebase(retention_window_days=3),
    fires=["CTL-LKB-002"],
    passes=["CTL-LKB-004", "CST-LKB-001", "CST-LKB-003"])

add("lakebase_retention_boundary",
    "Exactly seven days. The rule fires below seven, not at it.",
    lakebase(retention_window_days=7),
    passes=["CTL-LKB-002", "CTL-LKB-004", "CST-LKB-001", "CST-LKB-003"])

add("lakebase_without_owner",
    "An instance whose creator came back empty.",
    lakebase(owner=""),
    fires=["CTL-LKB-004"],
    passes=["CTL-LKB-002", "CST-LKB-001", "CST-LKB-003"])

# --- Model serving -----------------------------------------------------------
add("model_endpoint_customer_owned",
    "A well-configured customer endpoint. Every one of these four rules used to "
    "be unanswerable: three read an `attributes` object no handler ever built, "
    "and the chargeback rule read `attributes.custom_tags.cost_center` -- which, "
    "being a path through a missing object, made `not` true and fired on every "
    "endpoint in the estate regardless of its tags.",
    endpoint(),
    passes=["CST-MSE-001", "CST-MSE-002", "SEC-MSE-003", "CTL-MSE-004"])

add("model_endpoint_untagged",
    "The same endpoint with no cost_center tag, which is what CST-MSE-001 was "
    "always meant to catch and never could.",
    endpoint(tags={}),
    fires=["CST-MSE-001"],
    passes=["CST-MSE-002", "SEC-MSE-003", "CTL-MSE-004"])

add("model_endpoint_databricks_provided",
    "A Databricks-provided endpoint, recognised by its name prefix. The "
    "chargeback rule deliberately exempts these, and this is the fixture that "
    "keeps that exemption honest.",
    endpoint(id="databricks-gte-large-en", name="databricks-gte-large-en",
             tags={}),
    passes=["CST-MSE-001", "CST-MSE-002", "SEC-MSE-003", "CTL-MSE-004"])

add("model_endpoint_always_warm_in_dev",
    "A development endpoint holding capacity around the clock. `scale_to_zero` "
    "is true only when every served model scales down, so one always-warm model "
    "among several is enough to trip this.",
    endpoint(scale_to_zero=False), environment="dev", workspace="synthetic-dev",
    fires=["CST-MSE-002"],
    passes=["CST-MSE-001", "SEC-MSE-003", "CTL-MSE-004"])

add("model_endpoint_always_warm_in_prod_is_fine",
    "The same endpoint in production, where staying warm is the point. The pair "
    "proving CST-MSE-002's environment scope survived the rewrite.",
    endpoint(scale_to_zero=False),
    passes=["CST-MSE-001", "CST-MSE-002", "SEC-MSE-003", "CTL-MSE-004"])

add("model_endpoint_without_inference_logging",
    "A production endpoint not capturing inference to Unity Catalog, so there "
    "is no record of what it was asked or what it answered.",
    endpoint(inference_logging=False),
    fires=["CTL-MSE-004"],
    passes=["CST-MSE-001", "CST-MSE-002", "SEC-MSE-003"])

add("model_endpoint_open_to_all_users",
    "An endpoint any user can query. Note the asymmetry the handler documents: "
    "an unreadable ACL also produces an empty `shared_with`, so this rule "
    "under-reports rather than flagging endpoints nobody could inspect.",
    endpoint(shared_with=["ALL_USERS"]),
    fires=["SEC-MSE-003"],
    passes=["CST-MSE-001", "CST-MSE-002", "CTL-MSE-004"])

# --- Notebooks ---------------------------------------------------------------
#
# Two of the three rules work now: `path`, `in_git_folder` and `is_scheduled`
# are collected, the last by reading every job's tasks once per scan. SEC-NBK-001
# still cannot fire -- it wants the results of a credential scan of the notebook
# body, and nothing performs one.

add("notebook_in_shared_workspace",
    "A notebook in a Git folder that no job runs. Nothing fires, which is the "
    "baseline the two rules below are measured against.",
    notebook(),
    passes=["SEC-NBK-001", "CTL-NBK-002", "CTL-NBK-003"])

add("notebook_scheduled_from_a_personal_folder",
    "Production logic scheduled out of somebody's home directory. Both rules "
    "fire: it is invisible to review, and it disappears with the account. "
    "`is_scheduled` is true because a job task points at this exact path.",
    notebook(id="/Users/someone@company.com/prod-load",
             path="/Users/someone@company.com/prod-load", name="prod-load",
             owner="someone@company.com", in_shared=False,
             in_git_folder=False, is_scheduled=True),
    fires=["CTL-NBK-002", "CTL-NBK-003"], passes=["SEC-NBK-001"])

add("notebook_in_personal_folder_but_not_scheduled",
    "The same personal-folder notebook that no job runs. CTL-NBK-002 is about "
    "production logic living somewhere fragile, not about where people keep "
    "their drafts, and this is the pair that holds it to that.",
    notebook(id="/Users/someone@company.com/scratch",
             path="/Users/someone@company.com/scratch", name="scratch",
             owner="someone@company.com", in_shared=False,
             in_git_folder=False),
    passes=["SEC-NBK-001", "CTL-NBK-002", "CTL-NBK-003"])

add("notebook_scheduled_outside_git",
    "A scheduled notebook in /Shared but not under a Git folder, so there is no "
    "history of what changed between runs. CTL-NBK-002 stays quiet because the "
    "path is not personal -- the two rules overlap and are not the same rule.",
    notebook(is_scheduled=True, in_git_folder=False),
    fires=["CTL-NBK-003"], passes=["SEC-NBK-001", "CTL-NBK-002"])

# --- Pipelines ---------------------------------------------------------------
PIPELINE_RULES = ["CST-PIP-001", "CTL-PIP-002", "CTL-PIP-003", "SEC-PIP-004",
                  "CST-PIP-005"]

add("pipeline_serverless_triggered",
    "A well-configured production pipeline.",
    pipeline(),
    passes=PIPELINE_RULES)

add("pipeline_classic_compute",
    "A pipeline still on classic compute. CST-PIP-001 read this through an "
    "`attributes` object the handler never produced, so it matched nothing at "
    "all until the path was corrected; this fixture is what keeps it honest.",
    pipeline(serverless=False),
    fires=["CST-PIP-001"], passes=others(PIPELINE_RULES, ["CST-PIP-001"]))

add("pipeline_continuous_in_dev",
    "A continuous pipeline outside production, which bills around the clock for "
    "a development workload. Same corrected path as above.",
    pipeline(continuous=True, development=True),
    environment="dev", workspace="synthetic-dev",
    fires=["CST-PIP-005"], passes=others(PIPELINE_RULES, ["CST-PIP-005"]))

add("pipeline_continuous_in_prod_is_fine",
    "The same continuous pipeline in production, where running continuously is "
    "the point. The pair proving CST-PIP-005's environment scope is real.",
    pipeline(continuous=True),
    passes=PIPELINE_RULES)

add("pipeline_publishing_to_hive_metastore",
    "A pipeline still writing to the legacy metastore, so its output has no "
    "Unity Catalog lineage or governance. The API has no 'which metastore' "
    "field; the handler infers this from an empty `catalog` alongside a set "
    "`target`.",
    pipeline(target_catalog="hive_metastore"),
    fires=["CTL-PIP-003"], passes=others(PIPELINE_RULES, ["CTL-PIP-003"]))

add("pipeline_running_as_a_person_in_prod",
    "A production pipeline running as its author rather than a service "
    "principal, so it stops working the day they leave.",
    pipeline(owner_type="user", owner="someone@company.com"),
    fires=["SEC-PIP-004"], passes=others(PIPELINE_RULES, ["SEC-PIP-004"]))

# --- Service principals ------------------------------------------------------
add("service_principal_named",
    "A service principal with a display name, which is what the owner field is "
    "derived from.",
    principal(),
    passes=["CTL-SPN-003", "SEC-SPN-001", "SEC-SPN-002", "SEC-SPN-004"])

add("service_principal_without_name",
    "SCIM can return a principal with no display name, leaving nobody to ask "
    "about it. The handler derives `owner` from that same name, so an unnamed "
    "principal is also an unowned one.",
    principal(name="", owner=""),
    fires=["CTL-SPN-003"],
    passes=["SEC-SPN-001", "SEC-SPN-002", "SEC-SPN-004"])

add("service_principal_with_account_admin_role",
    "A service principal holding account admin. SCIM files this under `roles`, "
    "which is only populated when the client is bound to the account -- so "
    "against a workspace-scoped client this rule sees nothing and stays quiet.",
    principal(roles=["account_admin"]),
    fires=["SEC-SPN-002"],
    passes=["CTL-SPN-003", "SEC-SPN-001", "SEC-SPN-004"])

add("service_principal_with_account_admin_entitlement",
    "The same privilege as the fixture above, arriving in `entitlements` "
    "instead. The rule is written twice, once against each field, because "
    "which one is populated depends on how the client was configured rather "
    "than on anything about the principal.",
    principal(entitlements=["account_admin"]),
    fires=["SEC-SPN-002"],
    passes=["CTL-SPN-003", "SEC-SPN-001", "SEC-SPN-004"])

# --- SQL warehouses ----------------------------------------------------------
add("warehouse_compliant_in_prod",
    "A well-configured production warehouse. CTL-WHS-001 fires anyway, because "
    "it tests `policy_id` and the warehouse handler does not collect it -- so "
    "this rule currently flags every production warehouse in the estate.",
    warehouse(),
    fires=["CTL-WHS-001"],
    passes=["CST-WHS-002", "CST-WHS-003", "CST-WHS-004", "CST-WHS-005"])

add("warehouse_no_autostop",
    "Auto-stop disabled, which is a warehouse that bills until somebody notices.",
    warehouse(auto_stop_mins=0),
    fires=["CTL-WHS-001", "CST-WHS-002"],
    passes=["CST-WHS-003", "CST-WHS-004", "CST-WHS-005"])

add("warehouse_scaling_boundary",
    "Exactly ten clusters. CST-WHS-003 fires above ten, not at it, and an "
    "off-by-one here would flag every large warehouse on its tenth cluster.",
    warehouse(max_num_clusters=10),
    fires=["CTL-WHS-001"],
    passes=["CST-WHS-002", "CST-WHS-003", "CST-WHS-004", "CST-WHS-005"])

add("warehouse_scaling_excessive",
    "Eleven clusters, one past the boundary above.",
    warehouse(max_num_clusters=11),
    fires=["CTL-WHS-001", "CST-WHS-003"],
    passes=["CST-WHS-002", "CST-WHS-004", "CST-WHS-005"])

add("warehouse_untagged",
    "No cost tags, so the spend cannot be attributed to anyone.",
    warehouse(tags={}),
    fires=["CTL-WHS-001", "CST-WHS-004"],
    passes=["CST-WHS-002", "CST-WHS-003", "CST-WHS-005"])

add("warehouse_in_dev",
    "Outside production the compute-policy rule is out of scope, which is the "
    "only reason this fixture can show a warehouse with nothing firing.",
    warehouse(), environment="dev", workspace="synthetic-dev",
    passes=["CTL-WHS-001", "CST-WHS-002", "CST-WHS-003", "CST-WHS-004",
            "CST-WHS-005"])

# --- Volumes -----------------------------------------------------------------
add("volume_classified",
    "A managed volume carrying a data classification.",
    volume(tags={"data_classification": "internal"}),
    passes=["CTL-VOL-003", "CTL-VOL-004", "SEC-VOL-001", "SEC-VOL-002"])

add("volume_unclassified",
    "No classification tag, so it is unknown whether this volume holds personal "
    "data.",
    volume(),
    fires=["CTL-VOL-003"],
    passes=["CTL-VOL-004", "SEC-VOL-001", "SEC-VOL-002"])

add("volume_without_owner",
    "An external volume with no Unity Catalog owner recorded.",
    volume(owner="", storage_type="EXTERNAL",
           tags={"data_classification": "internal"}),
    fires=["CTL-VOL-004"],
    passes=["CTL-VOL-003", "SEC-VOL-001", "SEC-VOL-002"])


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    problems = []

    for name, payload in FIXTURES.items():
        resource = payload["resource"]
        known = set(resource_schema.resource_fields(resource["type"]))
        invented = sorted(set(resource) - known)
        if invented:
            problems.append(f"{name}: {invented}")

        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")

    print(f"Wrote {len(FIXTURES)} fixtures to {OUT}")
    if problems:
        raise SystemExit(
            "These fixtures use fields no handler collects, which would make "
            "them evidence about data that does not exist:\n  "
            + "\n  ".join(problems)
        )


if __name__ == "__main__":
    main()
