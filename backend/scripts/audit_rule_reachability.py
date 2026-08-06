"""Which shipped rules could ever fire against real discovery output.

Empirical rather than analytical: build the richest resource each handler could
possibly return — every declared field, populated — and evaluate the policies
against it. A rule that does not fire for *any* generated variation of a fully
populated resource is not strict, it is unreachable.

Run with `python -m scripts.audit_rule_reachability` from `backend/`.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Dict, List

from app.core.config import settings
from app.providers.databricks.handlers import HANDLER_REGISTRY
from app.providers.opa.client import OpaProvider
from app.services import policy_registry, resource_schema
from app.services.sentinel_service import SentinelService

#: A few plausible values per field, so a rule gated on a specific one still has
#: a chance to fire. Keyed by field name; anything unlisted gets the generic set.
CANDIDATES: Dict[str, List[Any]] = {
    "tags": [{}, {"cost-center": "CC-1", "owner": "a@b.com", "data_classification": "pii",
               "reliability_window": "7d", "data_owner": "team", "purpose": "x"}],
    "owner": ["someone@company.com", ""],
    "state": ["RUNNING", "TERMINATED", "STOPPED", "UNKNOWN"],
    "policy_id": [None, "pol-1"],
    "autotermination_minutes": [None, 0, 30],
    "auto_stop_mins": [0, 30],
    "max_num_clusters": [1, 40],
    "access_mode": ["USER_ISOLATION", "LEGACY_SINGLE_USER_STANDARD"],
    "cluster_type": ["interactive", "job"],
    "shared_with": [[], ["ALL_USERS"]],
    "uses_embedded_credentials": [False, True],
    "storage_type": ["MANAGED", "EXTERNAL", "dbfs", "local_volume"],
    "serverless": [True, False],
    "continuous": [True, False],
    "development": [True, False],
    "paused": [True, False],
    "active": [True, False],
    "retention_window_days": [0, 30],
    "capacity": ["CU_1", "CU_8"],
    "stopped": [True, False],
    "has_description": [True, False],
    "certified": [True, False],
    "quarantined": [True, False],
    "metadata_complete": [True],
    "endpoint_type": ["FOUNDATION_MODEL_API", "EXTERNAL_MODEL"],
    "in_shared": [True, False],
    "table_type": ["MANAGED", "VIEW"],
}

GENERIC = ["value", ""]

ENVIRONMENTS = [
    {"name": "ws-prod", "type": "enterprise", "environment": "prod"},
    {"name": "ws-dev", "type": "domain", "environment": "dev"},
    {"name": "ws-adhoc", "type": "ad-hoc", "environment": "dev"},
]


def variations(resource_type: str, limit: int = 96) -> List[Dict[str, Any]]:
    """Resources spanning the plausible values of every collected field."""
    fields = resource_schema.resource_fields(resource_type)
    names = [f for f in fields if f != "type"]
    options = [CANDIDATES.get(name, GENERIC) for name in names]

    out = []
    # The full product is astronomical, so walk it lazily and stop.
    for combo in itertools.islice(itertools.product(*options), limit):
        resource = dict(zip(names, combo))
        resource["type"] = resource_type
        resource.setdefault("id", f"{resource_type}-probe")
        out.append(resource)
    return out


async def main() -> None:
    opa = OpaProvider(settings.opa_provider_config())
    fired: set[str] = set()

    for resource_type in sorted(HANDLER_REGISTRY):
        for resource in variations(resource_type):
            for workspace in ENVIRONMENTS:
                payload = {
                    "workspace": workspace,
                    "resource": resource,
                    "allowlist_records": [],
                    "request_time": "2026-08-05T00:00:00Z",
                }
                results = await opa.evaluate_namespace(payload)
                for policy_name, result in results.items():
                    for finding in SentinelService._findings_from_result(
                        policy_name, result, resource
                    ):
                        if finding.get("kind") == "violation":
                            rule_id = finding.get("policy_id") or finding.get("rule_id")
                            if rule_id:
                                fired.add(str(rule_id))

    report = []
    for policy in policy_registry.load_policies():
        has_handler = policy.resource_type in HANDLER_REGISTRY
        for rule in policy.rules:
            report.append(
                {
                    "rule_id": rule.id,
                    "policy": policy.name,
                    "resource_type": policy.resource_type,
                    "handler": has_handler,
                    "reachable": rule.id in fired,
                }
            )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
