"""Telling a person apart from a service principal.

Several rules care whether a production workload runs as a human, because a job
that runs as its author breaks when the author leaves and carries that person's
whole access footprint while they are here. The APIs answer the question in two
different shapes, and the fallback shape is ambiguous, so the logic lives in one
place with its uncertainty made explicit rather than being guessed at twice.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: Service principals are identified by an application ID, which is a UUID.
#: Users are identified by an email address. When all we are handed is a bare
#: string, its shape is the only signal available.
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

USER = "user"
SERVICE_PRINCIPAL = "service_principal"
UNKNOWN = "unknown"


def owner_type(run_as: Any, run_as_name: Optional[str] = None) -> str:
    """``"user"``, ``"service_principal"`` or ``"unknown"``.

    ``run_as`` is the structured object the jobs and pipelines APIs return,
    which names the field it populates and so answers definitively. When it is
    absent we fall back to the shape of ``run_as_name``.

    Returns ``"unknown"`` rather than assuming, because both possible
    assumptions are harmful: defaulting to service principal hides every
    human-owned production workload, and defaulting to user flags every
    correctly configured one. A rule matching on ``"user"`` will do neither.
    """
    if run_as is not None:
        if getattr(run_as, "service_principal_name", None):
            return SERVICE_PRINCIPAL
        if getattr(run_as, "user_name", None):
            return USER

    name = (run_as_name or "").strip()
    if not name:
        return UNKNOWN
    if _UUID.match(name):
        return SERVICE_PRINCIPAL
    if "@" in name:
        return USER
    return UNKNOWN
