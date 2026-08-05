"""The read-only tools the Q&A loop may call.

Read-only here is structural, not a convention. This module imports the policy
registry, the read side of the database, and the OPA evaluator. It does not
import ``app.providers.databricks.handlers``, ``app.providers.databricks.destructive``,
``app.services.action_executor``, or ``app.core.enforcement`` — so there is no
tool through which the assistant can act on a resource, and no route by which
one could be added without that import appearing here in review.

:func:`build_tools` returns a fixed list. Nothing is registered dynamically,
which means the set of things the assistant can do is the set of functions
written in this file.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.services.agent_llm import Tool

logger = logging.getLogger(__name__)

#: Cap on rows returned to the model. Findings tables run to tens of thousands
#: of rows; the model needs a sample and a count, not the table.
_MAX_ROWS = 50


# --- Policies ---------------------------------------------------------------


async def _list_policies(args: Dict[str, Any]) -> Any:
    from app.services import policy_registry

    policies = policy_registry.load_policies()
    return {
        "policies": [
            {
                "name": p.name,
                "package": p.package,
                "title": p.title,
                "owner": p.owner,
                "resource_type": p.resource_type,
                "rules": [
                    {
                        "rule": r.rule,
                        "id": r.id,
                        "category": r.category,
                        "severity": r.severity,
                        "requested_action": r.requested_action,
                        "tier": r.tier,
                        "description": r.description,
                    }
                    for r in p.rules
                ],
            }
            for p in policies
        ],
        "summary": policy_registry.registry_summary(),
    }


async def _read_policy(args: Dict[str, Any]) -> Any:
    from app.core.config import settings

    name = str(args.get("policy_name") or "").strip()
    if not name:
        return "policy_name is required."
    if not name.endswith(".rego"):
        name += ".rego"

    # The model chooses this name, so it is untrusted input on a filesystem
    # path. basename() collapses any traversal attempt to a bare filename.
    name = os.path.basename(name)
    path = os.path.join(settings.get_policies_dir, name)
    if not os.path.exists(path):
        return f"No policy named {name!r}."

    with open(path, "r", encoding="utf-8") as handle:
        return {"name": name, "content": handle.read()}


async def _evaluate_policy(args: Dict[str, Any]) -> Any:
    """Run a resource through the live policies.

    Answers "would this cluster violate anything?" by evaluating rather than by
    reading the Rego and reasoning about it, which is what the model would
    otherwise do, and would sometimes get wrong.
    """
    from app.core.config import settings
    from app.providers.opa.client import OpaProvider

    resource = args.get("resource")
    if not isinstance(resource, dict):
        return "resource must be an object describing one Databricks resource."

    input_data = {
        "resource": resource,
        "workspace": args.get("workspace") or {"environment": "dev"},
        "allowlist": [],
    }

    opa = OpaProvider(settings.opa_provider_config())
    try:
        results = await opa.evaluate_namespace(input_data)
    except Exception as e:
        return f"Evaluation failed: {e}"

    # Packages that did not apply return nothing useful and would crowd out the
    # ones that did.
    return {
        package: result
        for package, result in results.items()
        if isinstance(result, dict) and result.get("rule_results")
    }


# --- Findings ---------------------------------------------------------------


async def _search_findings(args: Dict[str, Any]) -> Any:
    from app.db.session import SessionLocal
    from app.db.sentinel_finding import SentinelFindingModel
    from app.db.sentinel_run import SentinelRunModel

    session = SessionLocal()
    try:
        run_id = args.get("run_id")
        if run_id is None:
            run = session.query(SentinelRunModel).order_by(SentinelRunModel.id.desc()).first()
            if run is None:
                return "No scan has been run yet."
            run_id = run.id

        query = session.query(SentinelFindingModel).filter(
            SentinelFindingModel.run_id == run_id
        )

        for field, column in (
            ("policy", SentinelFindingModel.policy),
            ("severity", SentinelFindingModel.severity),
            ("category", SentinelFindingModel.category),
            ("resource_type", SentinelFindingModel.resource_type),
            ("workspace", SentinelFindingModel.workspace),
            ("owner", SentinelFindingModel.owner),
        ):
            value = args.get(field)
            if value:
                query = query.filter(column == str(value))

        query = query.filter(SentinelFindingModel.kind == str(args.get("kind") or "violation"))

        total = query.count()
        rows = query.order_by(SentinelFindingModel.id.desc()).limit(_MAX_ROWS).all()

        return {
            "run_id": run_id,
            "total_matching": total,
            "returned": len(rows),
            "findings": [
                {
                    "resource": row.resource_name or row.resource_id,
                    "resource_type": row.resource_type,
                    "workspace": row.workspace,
                    "owner": row.owner,
                    "policy": row.policy,
                    "rule": row.rule_id,
                    "policy_id": row.policy_id,
                    "severity": row.severity,
                    "message": row.message,
                    "requested_action": row.requested_action,
                    "effective_action": row.effective_action,
                    "downgrade_reason": row.downgrade_reason,
                }
                for row in rows
            ],
        }
    except Exception as e:
        logger.warning("search_findings failed: %s", e)
        return f"Could not search findings: {e}"
    finally:
        session.close()


async def _get_allowlist(args: Dict[str, Any]) -> Any:
    from app.db.allowlist import AllowlistModel
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        rows = session.query(AllowlistModel).limit(_MAX_ROWS).all()
        return {
            "count": len(rows),
            "entries": [
                {
                    "resource_id": row.resource_id,
                    "resource_type": getattr(row, "resource_type", None),
                    "policy": getattr(row, "policy_name", None),
                    "reason": getattr(row, "reason", None),
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                }
                for row in rows
            ],
        }
    except Exception as e:
        logger.warning("get_allowlist failed: %s", e)
        return f"Could not read the allowlist: {e}"
    finally:
        session.close()


async def _get_enforcement_status(args: Dict[str, Any]) -> Any:
    """What would actually happen right now, gate by gate.

    Without this the model answers enforcement questions from the policy's
    requested action, which is the one answer guaranteed to be misleading —
    enforcement ships off, so nearly everything resolves to WARN.
    """
    from app.core.actions import describe_ladder
    from app.core.config import settings

    workspaces = [
        w.strip()
        for w in (settings.DESTRUCTIVE_ACTION_WORKSPACES or "").split(",")
        if w.strip()
    ]
    return {
        "enforcement_enabled": settings.ENFORCEMENT_ENABLED,
        "destructive_workspaces": workspaces,
        "max_resources_per_run": settings.DESTRUCTIVE_ACTION_MAX_RESOURCES,
        "scheduled_scan_mode": settings.SENTINEL_CRON_MODE,
        "action_ladder": describe_ladder(),
        "note": (
            "With enforcement disabled, every action resolves to WARN regardless "
            "of what a policy requests."
        ),
    }


# --- Registry ---------------------------------------------------------------

_TOOL_SPECS = [
    (
        "list_policies",
        "List every governance policy with its rules, severities, and requested "
        "actions. Start here for any question about what is being checked.",
        {"type": "object", "properties": {}},
        _list_policies,
    ),
    (
        "read_policy",
        "Read the full Rego source of one policy file.",
        {
            "type": "object",
            "properties": {
                "policy_name": {
                    "type": "string",
                    "description": "File name, e.g. clusters.rego",
                }
            },
            "required": ["policy_name"],
        },
        _read_policy,
    ),
    (
        "search_findings",
        "Search the findings from a scan. Defaults to the most recent run. "
        "Returns a count of all matches plus a sample.",
        {
            "type": "object",
            "properties": {
                "run_id": {"type": "integer", "description": "Defaults to the latest run."},
                "policy": {"type": "string", "description": "Package name, e.g. clusters"},
                "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                "category": {"type": "string"},
                "resource_type": {"type": "string"},
                "workspace": {"type": "string"},
                "owner": {"type": "string"},
                "kind": {"type": "string", "enum": ["violation", "check"]},
            },
        },
        _search_findings,
    ),
    (
        "evaluate_policy",
        "Evaluate a hypothetical resource against the live policies and return "
        "which rules fire. Use this instead of reasoning about the Rego yourself.",
        {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "object",
                    "description": "The resource, including a `type` field.",
                },
                "workspace": {
                    "type": "object",
                    "description": "Optional workspace context, e.g. {\"environment\": \"prod\"}.",
                },
            },
            "required": ["resource"],
        },
        _evaluate_policy,
    ),
    (
        "get_allowlist",
        "List the exceptions that exempt specific resources from policies.",
        {"type": "object", "properties": {}},
        _get_allowlist,
    ),
    (
        "get_enforcement_status",
        "Report whether enforcement is enabled and which gates are open. Call "
        "this before answering any question about what a policy would do.",
        {"type": "object", "properties": {}},
        _get_enforcement_status,
    ),
]


def build_tools(names: Optional[List[str]] = None) -> List[Tool]:
    """The tools available to the Q&A loop.

    ``names`` narrows the set; it cannot widen it, because the specs are a fixed
    module-level list.
    """
    tools = [
        Tool(name=name, description=description, parameters=parameters, handler=handler)
        for name, description, parameters, handler in _TOOL_SPECS
    ]
    if names is None:
        return tools
    wanted = set(names)
    return [tool for tool in tools if tool.name in wanted]


def tool_names() -> List[str]:
    return [spec[0] for spec in _TOOL_SPECS]
