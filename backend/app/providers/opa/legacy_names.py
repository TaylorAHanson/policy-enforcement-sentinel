"""Translation from the old policy packages to the per-resource ones.

The policy files used to be grouped by theme — ``compute_and_jobs`` held both
cluster and job rules, ``monitoring_and_logging`` held the tagging rules for
five different resource types. Splitting them per resource type made the files
navigable, but it invalidated every stored reference to a policy by name:
allowlist entries, saved dashboard filters, historical findings, and any
bookmark into the policy editor.

Rather than migrate that data — some of it is user-typed and some of it is in
URLs we do not control — old names keep resolving. A lookup for a retired name
returns the packages its rules moved to, so a link that used to open one policy
now opens the two or three that replaced it.

This is a compatibility shim with an expiry date. Once no stored data references
the old names, delete it.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

#: Retired package name -> the packages its rules now live in.
LEGACY_POLICY_PACKAGES: Dict[str, Tuple[str, ...]] = {
    "compute_and_jobs": ("clusters", "jobs"),
    "apps_and_genie": ("apps", "genie_spaces"),
    "dashboards_and_sql": ("dashboards", "sql_warehouses"),
    "data_and_ai_governance": ("datasets", "volumes"),
    "data_certification": ("datasets",),
    "identity_and_access": ("service_principals", "workspaces", "datasets"),
    "monitoring_and_logging": (
        "clusters",
        "jobs",
        "sql_warehouses",
        "apps",
        "genie_spaces",
    ),
    "spark_declarative_pipelines": ("pipelines",),
    "workspaces_and_environments": ("workspaces",),
}

#: Names that survived the restructure unchanged, listed so callers can tell
#: "unknown policy" apart from "known policy, no rename needed".
UNCHANGED_POLICY_PACKAGES: Tuple[str, ...] = (
    "service_principals",
    "model_serving_endpoints",
)


def resolve_policy_name(name: str) -> List[str]:
    """Current package names for a possibly-retired policy name.

    Returns the name itself when it is not a legacy one — callers can treat the
    result as "the packages to look at" without checking first. An unknown name
    comes back as-is rather than raising, because this sits in front of
    user-supplied filter values.
    """
    if not name:
        return []

    key = name.strip()
    if key.startswith("databricks.governance."):
        key = key[len("databricks.governance."):]

    replacement = LEGACY_POLICY_PACKAGES.get(key)
    if replacement:
        return list(replacement)
    return [key]


def is_legacy_name(name: str) -> bool:
    key = (name or "").strip()
    if key.startswith("databricks.governance."):
        key = key[len("databricks.governance."):]
    return key in LEGACY_POLICY_PACKAGES


def describe_migration() -> List[dict]:
    """Serialisable rename table, shown in the policy editor and release notes."""
    return [
        {"legacy_name": legacy, "replaced_by": list(current)}
        for legacy, current in sorted(LEGACY_POLICY_PACKAGES.items())
    ]
