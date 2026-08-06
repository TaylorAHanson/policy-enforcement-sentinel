"""Why a rule has never been shown working, and who can fix it.

"41 rules have no fixture" is a true sentence that helps nobody. It reads as one
problem with one owner, and it is at least three problems with three different
owners — a rule waiting on data the scanner does not collect, a rule for a
resource type nothing scans at all, and a rule that reads real data and still
never matches. Only the last is a bug in the rule, and it is the one worth
looking at first; lumping it in with the other two is how it stays unfixed.

So each rule is classified by what would actually make it work:

``untested``
    Reads only collected fields, and nothing is obviously wrong. It needs a
    fixture. This is the only category that is genuinely a gap in the tests.

``suspect``
    Reads only collected fields, has a fixture that expects it *not* to fire,
    and no fixture makes it fire. Somebody tried to test it and could not.
    That is the signature of a rule whose logic cannot match — an empty-string
    check, or a comparison against a value the handler never emits.

``needs_discovery``
    Reads a field no handler collects, and the field *is* collectable. No honest
    test can exist until discovery collects it, so the work is in the handler.

``needs_permission``
    Reads a field the platform exposes only to an identity with rights this
    scanner does not hold. Writing more collector code will not help; somebody
    has to grant something, or accept that the rule cannot run.

``not_exposed``
    Reads a field Databricks does not publish through any API, at any permission
    level. The rule describes a control the platform cannot evidence.

``no_handler``
    Governs a resource type nothing discovers. The rule cannot run at all.

The classification is derived, never stored. A handler that starts collecting a
field moves every rule waiting on it without anybody updating a list.

The last two matter because they change who the message is for. "Waiting on the
scanner" points at an engineer and implies the work is queued. If the truth is
that Unity Catalog will not disclose another principal's grants to a
non-admin, no amount of engineering closes it — that is a conversation with
whoever owns the metastore, or a decision to retire the rule. Presenting the two
identically is how a rule sits in a backlog for a year.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.providers.databricks.handlers import HANDLER_REGISTRY
from app.services import resource_schema

#: What each category means and what to do about it, in the order a person
#: should work through them. Order matters: `suspect` first because it is the
#: only one that is likely an outright bug, and the cheapest to act on.
CATEGORIES = {
    "suspect": {
        "label": "Probably broken",
        "detail": (
            "Reads data the scanner does collect, but no test can make it fire "
            "and a test exists that expects it not to. Usually the rule compares "
            "against a value discovery never produces, or checks for an empty "
            "field that always arrives with something in it."
        ),
        "action": (
            "Open the rule and check what it compares against, against what the "
            "handler actually emits. The Metadata tab lists the real values."
        ),
        "owner": "policy",
    },
    "untested": {
        "label": "Just needs a test",
        "detail": (
            "Reads data the scanner collects, and nothing looks wrong with it. "
            "Nobody has written a fixture that makes it fire, so it has never "
            "been shown to work."
        ),
        "action": (
            "Write a test for it in the policy's Tests tab: one resource that "
            "should trip it, and one that should not."
        ),
        "owner": "tests",
    },
    "needs_discovery": {
        "label": "Waiting on the scanner",
        "detail": (
            "Reads a field no handler collects. Rego treats a missing field as "
            "no match, so the rule passes every resource silently. No honest "
            "test can exist until discovery collects the field."
        ),
        "action": (
            "Add the field to that resource's handler so discovery collects it, "
            "or retire the rule. Leaving it is the bad option: it reports every "
            "resource as fine without ever having checked."
        ),
        "owner": "handler",
    },
    "needs_permission": {
        "label": "The scanner is not allowed to see this",
        "detail": (
            "The data exists, and Databricks will not show it to the identity "
            "the scanner runs as. Collecting it anyway would return a filtered, "
            "convincing, wrong answer — which for a security rule is worse than "
            "collecting nothing."
        ),
        "action": (
            "Grant the scanner the access listed against each rule, or retire "
            "the rule. If neither is acceptable, say so in the policy so the "
            "next person does not re-litigate it."
        ),
        "owner": "admin",
    },
    "not_exposed": {
        "label": "Databricks does not publish this",
        "detail": (
            "No API returns this, at any permission level. The rule describes "
            "something real, and the platform offers no evidence of it."
        ),
        "action": (
            "Retire the rule, or rewrite it against a signal that does exist. "
            "Keeping it means reporting every resource as compliant on a check "
            "that never ran."
        ),
        "owner": "policy",
    },
    "no_handler": {
        "label": "Nothing scans this",
        "detail": (
            "Governs a resource type no handler discovers, so the rule never "
            "runs against anything at all."
        ),
        "action": (
            "Write a handler that discovers this resource type, or retire the "
            "policy. Until one exists these rules are a statement of intent, "
            "not a control."
        ),
        "owner": "handler",
    },
    "working": {
        "label": "Shown working",
        "detail": "A fixture makes it fire on data the scanner can really produce.",
        "action": "",
        "owner": "",
    },
}


#: Fields that are not merely uncollected. Each entry records *why* writing a
#: collector would not help, so the diagnosis can point at the right person.
#:
#: ``resource_types`` narrows an entry to the types it applies to, because the
#: same field name can be answerable for one resource and not another —
#: ``idle_days`` is exact for a cluster and unknowable for a Genie space.
#: ``None`` means it applies wherever the field appears.
BLOCKED_FIELDS: List[Dict[str, object]] = [
    {
        "field": "idle_days",
        "resource_types": {
            "app",
            "dashboard",
            "genie_space",
            "lakebase_instance",
            "service_principal",
            "sql_warehouse",
        },
        "category": "needs_permission",
        "requirement": "SELECT on the system catalog",
        "detail": (
            "These resources expose creation and edit times but nothing about "
            "use. Real usage lives in system.access.audit and "
            "system.query.history, which need SELECT on the system catalog — "
            "grantable only by a metastore admin."
        ),
    },
    {
        "field": "principals",
        "resource_types": None,
        "category": "needs_permission",
        "requirement": "ownership of the object, or metastore admin",
        "detail": (
            "Unity Catalog shows a caller only their own grants unless they own "
            "the object or its parent, or are a metastore admin. A scanner "
            "without that would read back its own access and conclude nothing "
            "is over-shared."
        ),
    },
    {
        "field": "grants",
        "resource_types": None,
        "category": "needs_permission",
        "requirement": "ownership of the object, or metastore admin",
        "detail": (
            "Same limitation as `principals`: information_schema.table_privileges "
            "filters to the caller, so a non-owner sees an almost empty result "
            "rather than an error."
        ),
    },
    {
        "field": "secret_age_days",
        "resource_types": None,
        "category": "needs_permission",
        "requirement": "account admin",
        "detail": (
            "OAuth secrets for a service principal are an account-level "
            "resource. A workspace-scoped client cannot enumerate them."
        ),
    },
    {
        "field": "peak_connection_pct",
        "resource_types": None,
        "category": "not_exposed",
        "requirement": "",
        "detail": (
            "The Lakebase instances API reports provisioned capacity and no "
            "utilisation. There is no connection-metrics endpoint to read."
        ),
    },
    {
        "field": "attributes",
        "resource_types": None,
        "category": "not_exposed",
        "requirement": "",
        "detail": (
            "The remaining use of this is a pipeline's expectation count, which "
            "is declared in pipeline source and only observable in the event log "
            "of a run. It is not part of the pipeline definition the API returns."
        ),
    },
    {
        "field": "failed_rule_count",
        "resource_types": None,
        "category": "not_exposed",
        "requirement": "",
        "detail": (
            "There is no data-quality result surface on a Unity Catalog table "
            "for the scanner to read."
        ),
    },
    {
        "field": "secret_scan_findings",
        "resource_types": None,
        "category": "not_exposed",
        "requirement": "",
        "detail": (
            "Nothing scans notebook source for credentials. Producing this "
            "would mean exporting and pattern-matching the body of every "
            "notebook in the workspace, which is a different product."
        ),
    },
]


def _blocked_reason(field: str, resource_type: str) -> Optional[Dict[str, object]]:
    """The recorded reason a field cannot simply be collected, if there is one."""
    for entry in BLOCKED_FIELDS:
        if entry["field"] != field:
            continue
        types = entry["resource_types"]
        if types is None or resource_type in types:  # type: ignore[operator]
            return entry
    return None


def _rule_body(content: str, rule_key: str) -> str:
    """Every ``violations.<rule_key>`` block in the policy, concatenated.

    A rule can be defined more than once — that is how Rego expresses "or", and
    the autotermination rule uses it. Missing the second definition would mean
    missing the fields only it reads.

    Falls back to the whole file when the rule cannot be located, which errs
    towards blaming discovery rather than towards a false "probably broken".
    """
    pattern = re.compile(
        r"^violations\." + re.escape(rule_key) + r"\b.*?^}", re.MULTILINE | re.DOTALL
    )
    blocks = pattern.findall(content)
    return "\n".join(blocks) if blocks else content


def _read_policy(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def diagnose(
    *,
    resource_type: Optional[str] = None,
    policy_name: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, object]:
    """Every rule, why it is or is not shown working, and what would fix it."""
    from app.services import policy_registry, synthetic_estate

    coverage = synthetic_estate.rule_coverage(
        resource_type=resource_type, policy_name=policy_name, directory=directory
    )

    policies = {p.name: p for p in policy_registry.load_policies()}
    sources: Dict[str, str] = {}

    findings: List[Dict[str, object]] = []
    for rule in coverage["rules"]:
        policy = policies.get(str(rule["policy"]))
        rule_type = str(rule["resource_type"] or "")

        if rule["reachable"]:
            category, missing = "working", []
        elif rule_type and rule_type not in HANDLER_REGISTRY:
            category, missing = "no_handler", []
        else:
            if policy and policy.file not in sources:
                sources[policy.file] = _read_policy(policy.file)
            content = sources.get(policy.file, "") if policy else ""

            rule_key = ""
            if policy:
                for descriptor in policy.rules:
                    if descriptor.id == rule["rule_id"]:
                        rule_key = descriptor.rule
                        break

            body = _rule_body(content, rule_key) if rule_key and content else content
            problems = resource_schema.check_fields(body, rule_type)
            missing = [p["field"] for p in problems]

            if missing:
                # A rule can be blocked on several fields at once. Report the
                # hardest blocker: telling somebody to write a collector is
                # useless if a second field needs a grant they cannot get.
                reasons = [_blocked_reason(f, rule_type) for f in missing]
                blockers = [r for r in reasons if r]
                if any(r["category"] == "not_exposed" for r in blockers):
                    category = "not_exposed"
                elif blockers:
                    category = "needs_permission"
                else:
                    category = "needs_discovery"
            elif rule["passes_in"]:
                # Somebody wrote a fixture for this rule, and could only get it
                # to not fire. That is the fingerprint of a rule that cannot
                # match rather than one nobody has got round to.
                category = "suspect"
            else:
                category = "untested"

        findings.append(
            {
                **rule,
                "category": category,
                "missing_fields": missing,
                # What stands between the rule and working, in the rule's own
                # terms. Empty for a plain uncollected field, where the category
                # already says everything.
                "blockers": [
                    {
                        "field": str(blocker["field"]),
                        "requirement": str(blocker["requirement"]),
                        "detail": str(blocker["detail"]),
                    }
                    for blocker in (
                        _blocked_reason(field, rule_type) for field in missing
                    )
                    if blocker
                ],
            }
        )

    by_category: Dict[str, int] = {name: 0 for name in CATEGORIES}
    for finding in findings:
        by_category[str(finding["category"])] += 1

    # Which field, for how many rules. This is the whole argument for a
    # discovery change in one line: "collect idle_days and ten rules start
    # working" is a decision somebody can actually make.
    blocked_on: Dict[str, Dict[str, object]] = {}
    for finding in findings:
        if finding["category"] != "needs_discovery":
            continue
        for field in finding["missing_fields"]:  # type: ignore[union-attr]
            entry = blocked_on.setdefault(
                field, {"field": field, "rules": [], "resource_types": set()}
            )
            entry["rules"].append(finding["rule_id"])  # type: ignore[union-attr]
            entry["resource_types"].add(finding["resource_type"])  # type: ignore[union-attr]

    return {
        **coverage,
        "rules": findings,
        "by_category": by_category,
        "categories": CATEGORIES,
        "blocked_on": sorted(
            (
                {
                    "field": entry["field"],
                    "rules": sorted(entry["rules"]),  # type: ignore[arg-type]
                    "rule_count": len(entry["rules"]),  # type: ignore[arg-type]
                    "resource_types": sorted(
                        t for t in entry["resource_types"] if t  # type: ignore[union-attr]
                    ),
                }
                for entry in blocked_on.values()
            ),
            key=lambda e: (-e["rule_count"], e["field"]),
        ),
    }
