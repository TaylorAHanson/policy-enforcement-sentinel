"""The only module permitted to make irreversible Databricks SDK calls.

Every function here demands an authorised :class:`~app.core.enforcement.
EffectiveAction` and raises if it doesn't get one. An ``EffectiveAction`` can
only be produced by ``resolve_effective_action``, so reaching this module means
the five gates were walked — there is no way to call
``clusters.permanent_delete_cluster`` in this codebase without that having
happened.

The confinement is enforced by ``tests/safety/test_destructive_confinement.py``,
which walks the source tree and fails if any of these SDK methods appear
elsewhere. If you find yourself wanting to add a destructive call to a handler,
add it here instead and call it from the handler.

Nothing in this module is reversible. That is the whole reason it is separate.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class UnauthorizedDestructiveCall(RuntimeError):
    """Raised when a destructive call was attempted without going through the gates.

    This is a programming error, not a runtime condition. It means someone added
    a code path that bypasses ``resolve_effective_action``.
    """


def _require_authorization(authorization: Any, operation: str) -> None:
    # Imported lazily to keep this module importable from the safety test
    # without dragging in settings.
    from app.core.enforcement import EffectiveAction

    if not isinstance(authorization, EffectiveAction):
        raise UnauthorizedDestructiveCall(
            f"{operation} requires an EffectiveAction produced by "
            f"resolve_effective_action(); got {type(authorization).__name__}."
        )

    if not authorization.is_authorized():
        raise UnauthorizedDestructiveCall(
            f"{operation} was handed an EffectiveAction that did not come from "
            "resolve_effective_action(). Destructive actions cannot be self-authorised."
        )

    if not authorization.is_destructive:
        raise UnauthorizedDestructiveCall(
            f"{operation} was called with a {authorization.action} authorization "
            f"(tier {int(authorization.tier)}). The resolved action must itself be "
            "destructive — a downgraded action must not reach this module."
        )

    logger.warning(
        "DESTRUCTIVE: %s authorised as %s (requested %s) in mode %s",
        operation,
        authorization.action,
        authorization.requested_action,
        authorization.mode.value,
    )


# --- Compute ----------------------------------------------------------------

def terminate_cluster(workspace_client, cluster_id: str, *, authorization) -> bool:
    """Stop a cluster. Anything running on it dies."""
    _require_authorization(authorization, f"terminate_cluster({cluster_id})")
    workspace_client.clusters.delete(cluster_id=cluster_id)
    return True


def delete_cluster_permanently(workspace_client, cluster_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_cluster_permanently({cluster_id})")
    workspace_client.clusters.permanent_delete_cluster(cluster_id=cluster_id)
    return True


def delete_warehouse(workspace_client, warehouse_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_warehouse({warehouse_id})")
    workspace_client.warehouses.delete(id=warehouse_id)
    return True


# --- Jobs and pipelines -----------------------------------------------------

def delete_job(workspace_client, job_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_job({job_id})")
    workspace_client.jobs.delete(job_id=int(job_id))
    return True


def delete_pipeline(workspace_client, pipeline_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_pipeline({pipeline_id})")
    workspace_client.pipelines.delete(pipeline_id=pipeline_id)
    return True


# --- Apps, dashboards, Genie ------------------------------------------------

def delete_app(workspace_client, app_name: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_app({app_name})")
    workspace_client.apps.delete(name=app_name)
    return True


def trash_dashboard(workspace_client, dashboard_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"trash_dashboard({dashboard_id})")
    workspace_client.lakeview.trash(dashboard_id=dashboard_id)
    return True


def trash_genie_space(workspace_client, space_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"trash_genie_space({space_id})")
    workspace_client.genie.trash_space(space_id=space_id)
    return True


# --- Identity ---------------------------------------------------------------

def delete_service_principal(workspace_client, sp_id: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_service_principal({sp_id})")
    workspace_client.service_principals.delete(id=sp_id)
    return True


# --- Data and serving -------------------------------------------------------

def delete_volume(workspace_client, volume_name: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_volume({volume_name})")
    workspace_client.volumes.delete(name=volume_name)
    return True


def delete_serving_endpoint(workspace_client, endpoint_name: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_serving_endpoint({endpoint_name})")
    workspace_client.serving_endpoints.delete(name=endpoint_name)
    return True


def delete_notebook(workspace_client, path: str, *, authorization) -> bool:
    _require_authorization(authorization, f"delete_notebook({path})")
    workspace_client.workspace.delete(path=path, recursive=False)
    return True


#: The SDK call sites this module owns. The confinement test reads this to know
#: what to search the rest of the tree for, so adding a destructive call here
#: automatically extends the guard rather than quietly escaping it.
CONFINED_SDK_CALLS = (
    "clusters.delete",
    "clusters.permanent_delete_cluster",
    "warehouses.delete",
    "jobs.delete",
    "pipelines.delete",
    "apps.delete",
    "lakeview.trash",
    "genie.trash_space",
    "service_principals.delete",
    "volumes.delete",
    "serving_endpoints.delete",
    "workspace.delete",
)
