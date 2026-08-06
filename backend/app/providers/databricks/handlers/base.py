"""Resource handler base class and capability mixins.

Capability here is **opt-in and nominal**. A handler can only be asked to
terminate a resource if it explicitly inherits :class:`SupportsTerminate`;
``isinstance`` against these mixins is a real type check, not a probe for a
method name. That is the point — the previous design dispatched on
``hasattr(handler, "kill")``, which meant any handler that happened to grow a
method called ``kill`` became destructible by accident.

The base class deliberately carries only the two capabilities every handler must
have: discovering resources, and telling a human about a problem. Everything
that changes a resource is a mixin the author had to reach for.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, FrozenSet, List, Optional

import logging

logger = logging.getLogger(__name__)


class BaseResourceHandler(ABC):
    """One resource type's view of a workspace.

    Subclasses must implement discovery and warning. They must not implement
    destructive behaviour here — see the mixins below.
    """

    #: Resource type string as it appears in the Rego input document.
    resource_type: str = "unknown"

    #: Field name -> what it holds, for every key ``discover()`` puts on a
    #: resource. This is the vocabulary a policy for this type is allowed to
    #: use, and it is declared rather than inferred so it can be read without
    #: running a scan.
    #:
    #: It exists because of the failure mode that has now bitten this
    #: repository twice: Rego treats a reference to a key that was never
    #: supplied as simply not matching, so a rule about ``idle_hours`` on a
    #: resource type whose handler never collects ``idle_hours`` does not error.
    #: It passes. Every resource looks compliant, the dashboard is green, and
    #: the rule protects nothing. A missing field is not a runtime error here —
    #: it is a silent, permanent false negative, which is why it needs catching
    #: before the policy is written rather than after it ships.
    #:
    #: Keep this honest. A field listed here that discovery does not actually
    #: set is worse than one that is missing, because it invites exactly the
    #: rule that cannot work.
    discovered_fields: Dict[str, str] = {}

    def __init__(self, workspace_client):
        self.workspace_client = workspace_client

    @abstractmethod
    async def discover(self) -> List[Dict[str, Any]]:
        """Return every resource of this type.

        Each entry needs at least ``id`` and ``type``. Errors must **propagate**:
        the scan engine distinguishes an authentication failure from a genuinely
        empty workspace, and swallowing the exception here turns "we could not
        look" into "there is nothing there", which reads as compliant.
        """

    async def warn(
        self, resource_id: str, message: str, owner: Optional[str] = None
    ) -> bool:
        """Notify the resource owner. Must not change the resource.

        Concrete on the base because every handler warns identically, and
        because ``warn`` is the floor the whole safety model falls back to — a
        handler that forgot to implement it would push the fallback down to
        "record silently", which is not what anyone means by a warning.

        ``owner`` is optional: the scan engine already knows it from discovery
        and passes it through, but a caller acting on a single resource may not.
        """
        from app.providers.notifications.email import EmailNotifier

        logger.info(
            "Warning owner of %s %s: %s", self.resource_type, resource_id, message
        )
        return EmailNotifier().send_warning(owner or "unknown", resource_id, message)


# --- Tier 2 capabilities (reversible) ---------------------------------------
#
# Each mixin pairs an action with its undo. A Tier 2 action that cannot be
# reversed is a Tier 3 action wearing a disguise, so the undo is abstract too.


class SupportsRevokeAccess(ABC):
    """Can remove permissions without destroying the resource."""

    @abstractmethod
    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        """Remove grants. Returns the prior state needed by :meth:`restore_access`."""

    @abstractmethod
    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        """Reapply the permissions captured by :meth:`revoke_access`."""


class SupportsQuarantine(ABC):
    """Can restrict a resource to its owner and admins."""

    @abstractmethod
    async def quarantine(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def unquarantine(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        ...


class SupportsDisable(ABC):
    """Can pause a schedule or trigger without deleting anything."""

    @abstractmethod
    async def disable(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def enable(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        ...


class SupportsThrottle(ABC):
    """Can cap spend by lowering autoscale ceilings or setting autotermination."""

    @abstractmethod
    async def throttle(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def unthrottle(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        ...


class SupportsAnnotate(ABC):
    """Can tag a resource as non-compliant. Visible, but not limiting."""

    @abstractmethod
    async def annotate(self, resource_id: str, message: str, *, authorization=None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def unannotate(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        ...


class SupportsCertification(ABC):
    """Can mark a dataset certified or withdraw that certification."""

    @abstractmethod
    async def certify(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def uncertify(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        ...


# --- Tier 3 capabilities (irreversible) -------------------------------------
#
# Implementing one of these is a deliberate act with real consequences. The
# implementation must delegate to app.providers.databricks.destructive, which is
# the only module permitted to make the underlying SDK call.


class SupportsTerminate(ABC):
    """Can stop and remove a running resource. Work in flight is lost."""

    @abstractmethod
    async def terminate(self, resource_id: str, *, authorization) -> bool:
        """``authorization`` must be an authorised ``EffectiveAction``."""


class SupportsDelete(ABC):
    """Can permanently remove a resource and its configuration."""

    @abstractmethod
    async def delete(self, resource_id: str, *, authorization) -> bool:
        """``authorization`` must be an authorised ``EffectiveAction``."""


#: Maps the handler verb named in the action ladder to the mixin that grants it.
CAPABILITY_MIXINS = {
    "warn": BaseResourceHandler,
    "revoke_access": SupportsRevokeAccess,
    "restore_access": SupportsRevokeAccess,
    "quarantine": SupportsQuarantine,
    "unquarantine": SupportsQuarantine,
    "disable": SupportsDisable,
    "enable": SupportsDisable,
    "throttle": SupportsThrottle,
    "unthrottle": SupportsThrottle,
    "annotate": SupportsAnnotate,
    "unannotate": SupportsAnnotate,
    "certify": SupportsCertification,
    "uncertify": SupportsCertification,
    "terminate": SupportsTerminate,
    "delete": SupportsDelete,
}


def supported_methods(handler) -> FrozenSet[str]:
    """Which action verbs this handler actually implements.

    Fed to the chokepoint so a downgrade never lands on something the handler
    has no concept of — ``REVOKE_ACCESS`` means nothing for a resource type
    without permissions, and silently doing nothing would look like success.
    """
    return frozenset(
        verb
        for verb, mixin in CAPABILITY_MIXINS.items()
        if isinstance(handler, mixin)
    )


def supports(handler, verb: str) -> bool:
    mixin = CAPABILITY_MIXINS.get(verb)
    return bool(mixin and isinstance(handler, mixin))
