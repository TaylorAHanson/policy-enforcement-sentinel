"""Reversible permission changes.

This backs the ``REVOKE_ACCESS`` and ``QUARANTINE`` actions. Everything here is
undoable by construction: each function captures the full prior access control
list before changing anything and returns it as the undo payload, which lands in
``enforcement_audit.undo_payload``.

Deliberately *not* in ``destructive.py`` — nothing here loses data or work, and
the whole point of Tier 2 is that it achieves the governance outcome without
being irreversible. Revoking access to an untagged production cluster stops the
misuse; terminating it also destroys whatever was running.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


#: Resource type (as it appears in the Rego input) -> the SDK's permissions API
#: object type. Types absent from this map have no permissions surface, and the
#: chokepoint will decline to downgrade to REVOKE_ACCESS for them.
REQUEST_OBJECT_TYPES: Dict[str, str] = {
    "cluster": "clusters",
    "job": "jobs",
    "sql_warehouse": "warehouses",
    "app": "apps",
    "pipeline": "pipelines",
    "notebook": "notebooks",
    "model_serving_endpoint": "serving-endpoints",
    "dashboard": "dbsql-dashboards",
    "genie_space": "genie",
}

#: Permission levels that let someone use or change the resource. These are what
#: we strip. Ownership and admin-equivalent levels are preserved so the resource
#: doesn't become unmanageable.
PRESERVED_LEVELS = {"IS_OWNER", "CAN_MANAGE"}


def _acl_entry_to_dict(entry: Any) -> Dict[str, Any]:
    """Flatten an SDK ACL entry into something JSON-serialisable."""
    permissions: List[str] = []
    for permission in getattr(entry, "all_permissions", None) or []:
        level = getattr(permission, "permission_level", None)
        # Inherited permissions can't be set directly; replaying them on restore
        # would fail the API call.
        if getattr(permission, "inherited", False):
            continue
        if level is not None:
            permissions.append(getattr(level, "value", str(level)))

    return {
        "user_name": getattr(entry, "user_name", None),
        "group_name": getattr(entry, "group_name", None),
        "service_principal_name": getattr(entry, "service_principal_name", None),
        "permission_levels": permissions,
    }


def capture_permissions(workspace_client, resource_type: str, resource_id: str) -> Dict[str, Any]:
    """Snapshot the current ACL so a later change can be undone."""
    object_type = REQUEST_OBJECT_TYPES.get(resource_type)
    if not object_type:
        raise ValueError(f"No permissions surface known for resource type {resource_type!r}")

    current = workspace_client.permissions.get(
        request_object_type=object_type, request_object_id=resource_id
    )
    entries = [
        _acl_entry_to_dict(entry)
        for entry in (getattr(current, "access_control_list", None) or [])
    ]
    return {
        "resource_type": resource_type,
        "object_type": object_type,
        "resource_id": resource_id,
        "access_control_list": entries,
    }


def _to_access_control_requests(entries: List[Dict[str, Any]]):
    from databricks.sdk.service import iam

    requests = []
    for entry in entries:
        for level in entry.get("permission_levels") or []:
            requests.append(
                iam.AccessControlRequest(
                    user_name=entry.get("user_name"),
                    group_name=entry.get("group_name"),
                    service_principal_name=entry.get("service_principal_name"),
                    permission_level=iam.PermissionLevel(level),
                )
            )
    return requests


def revoke_permissions(
    workspace_client,
    resource_type: str,
    resource_id: str,
    *,
    keep_levels: Optional[set] = None,
) -> Dict[str, Any]:
    """Strip usage permissions, keeping ownership and management.

    Returns the prior ACL as an undo payload. Raises rather than reporting
    success if the capture fails — acting without a way back is exactly what
    this module exists to prevent.
    """
    keep = keep_levels if keep_levels is not None else PRESERVED_LEVELS
    undo_payload = capture_permissions(workspace_client, resource_type, resource_id)

    retained = []
    for entry in undo_payload["access_control_list"]:
        kept_levels = [lvl for lvl in entry["permission_levels"] if lvl in keep]
        if kept_levels:
            retained.append({**entry, "permission_levels": kept_levels})

    workspace_client.permissions.set(
        request_object_type=undo_payload["object_type"],
        request_object_id=resource_id,
        access_control_list=_to_access_control_requests(retained),
    )

    removed = sum(
        len(e["permission_levels"]) for e in undo_payload["access_control_list"]
    ) - sum(len(e["permission_levels"]) for e in retained)
    logger.info(
        "Revoked %d permission grant(s) on %s %s; %d retained (owner/manage).",
        removed,
        resource_type,
        resource_id,
        sum(len(e["permission_levels"]) for e in retained),
    )
    return undo_payload


def restore_permissions(workspace_client, undo_payload: Dict[str, Any]) -> bool:
    """Reapply an ACL captured by :func:`revoke_permissions`."""
    if not undo_payload or "access_control_list" not in undo_payload:
        raise ValueError("undo_payload does not contain a captured access control list")

    workspace_client.permissions.set(
        request_object_type=undo_payload["object_type"],
        request_object_id=undo_payload["resource_id"],
        access_control_list=_to_access_control_requests(
            undo_payload["access_control_list"]
        ),
    )
    logger.info(
        "Restored permissions on %s %s.",
        undo_payload.get("resource_type"),
        undo_payload.get("resource_id"),
    )
    return True


def quarantine_permissions(workspace_client, resource_type: str, resource_id: str) -> Dict[str, Any]:
    """Restrict to owners only — stricter than :func:`revoke_permissions`."""
    return revoke_permissions(
        workspace_client, resource_type, resource_id, keep_levels={"IS_OWNER"}
    )
