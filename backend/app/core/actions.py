"""The action ladder — the single source of truth for what an action means.

Every action the Sentinel can take is registered here with the tier it belongs
to, whether it can be undone, and the handler verb that performs it. Nothing
outside this module gets to decide that a string like ``"TERMINATE"`` is safe.

The tiers exist so that "degrade one step" is a well-defined operation. When a
gate refuses a destructive action we do not want to guess at something gentler,
and we especially do not want to fall through to "do the thing anyway".

An action this module does not recognise is not a permission to improvise. It
resolves to :data:`SAFE_FALLBACK_ACTION`. There is no code path in which the
absence of information produces destruction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ActionTier(IntEnum):
    """How much damage an action can do, ascending.

    Ordering is meaningful: ``tier <= ActionTier.NOTIFY`` is the check for
    "this cannot change anything", and downgrades walk this scale downwards.
    """

    OBSERVE = 0
    """Records a finding. No side effect of any kind."""

    NOTIFY = 1
    """Reaches a human. Does not change the resource's behaviour or access."""

    RESTRICT = 2
    """Changes the resource, reversibly, and stores what it takes to undo."""

    DESTRUCTIVE = 3
    """Irreversible. Requires every gate in ``core.enforcement`` to agree."""


TIER_LABELS: Dict[ActionTier, str] = {
    ActionTier.OBSERVE: "Observe",
    ActionTier.NOTIFY: "Notify",
    ActionTier.RESTRICT: "Restrict",
    ActionTier.DESTRUCTIVE: "Destructive",
}


@dataclass(frozen=True)
class ActionSpec:
    """What an action is, and what it takes to perform or reverse it."""

    name: str
    tier: ActionTier
    reversible: bool
    description: str
    #: Handler method that performs it. ``None`` for actions with no side effect.
    handler_method: Optional[str] = None
    #: Handler method that reverses it. Required for every Tier 2 action.
    undo_method: Optional[str] = None

    @property
    def is_destructive(self) -> bool:
        return self.tier >= ActionTier.DESTRUCTIVE

    @property
    def has_side_effect(self) -> bool:
        return self.handler_method is not None


# --- The registry -----------------------------------------------------------
#
# Adding an entry here is a deliberate act. Adding one at Tier 3 means writing
# code in providers/databricks/destructive.py, which is the only module allowed
# to make the call, and it means the safety suite will require the policy that
# requests it to carry `destructive: true`.

ACTIONS: Dict[str, ActionSpec] = {
    # Tier 0 — Observe
    "ALLOW": ActionSpec(
        name="ALLOW",
        tier=ActionTier.OBSERVE,
        reversible=True,
        description="Resource complies with policy. Nothing to do.",
    ),
    "SKIPPED_ALLOWLIST": ActionSpec(
        name="SKIPPED_ALLOWLIST",
        tier=ActionTier.OBSERVE,
        reversible=True,
        description="Violation waived by an approved, unexpired allowlist exception.",
    ),
    "PENDING_EXCEPTION": ActionSpec(
        name="PENDING_EXCEPTION",
        tier=ActionTier.OBSERVE,
        reversible=True,
        description="Violation held while an exception request awaits approval.",
    ),
    "FLAG": ActionSpec(
        name="FLAG",
        tier=ActionTier.OBSERVE,
        reversible=True,
        description="Record the finding for review without notifying anyone.",
    ),
    # Tier 1 — Notify
    "WARN": ActionSpec(
        name="WARN",
        tier=ActionTier.NOTIFY,
        reversible=True,
        description="Email the resource owner describing the violation.",
        handler_method="warn",
    ),
    "ANNOTATE": ActionSpec(
        name="ANNOTATE",
        tier=ActionTier.NOTIFY,
        reversible=True,
        description="Tag the resource as non-compliant. Visible, but not limiting.",
        handler_method="annotate",
        undo_method="unannotate",
    ),
    "CERTIFY": ActionSpec(
        name="CERTIFY",
        tier=ActionTier.NOTIFY,
        reversible=True,
        description="Mark a dataset as certified.",
        handler_method="certify",
        undo_method="uncertify",
    ),
    # Tier 2 — Restrict
    "REVOKE_ACCESS": ActionSpec(
        name="REVOKE_ACCESS",
        tier=ActionTier.RESTRICT,
        reversible=True,
        description=(
            "Remove grants or permissions, leaving the resource intact. Usually the "
            "right answer where the instinct was to terminate."
        ),
        handler_method="revoke_access",
        undo_method="restore_access",
    ),
    "QUARANTINE": ActionSpec(
        name="QUARANTINE",
        tier=ActionTier.RESTRICT,
        reversible=True,
        description="Tag and restrict the resource to its owner and admins.",
        handler_method="quarantine",
        undo_method="unquarantine",
    ),
    "DISABLE": ActionSpec(
        name="DISABLE",
        tier=ActionTier.RESTRICT,
        reversible=True,
        description="Pause a schedule or trigger without deleting anything.",
        handler_method="disable",
        undo_method="enable",
    ),
    "THROTTLE": ActionSpec(
        name="THROTTLE",
        tier=ActionTier.RESTRICT,
        reversible=True,
        description="Lower autoscale ceilings or set autotermination to cap spend.",
        handler_method="throttle",
        undo_method="unthrottle",
    ),
    "UNCERTIFY": ActionSpec(
        name="UNCERTIFY",
        tier=ActionTier.RESTRICT,
        reversible=True,
        description="Remove a dataset's certification.",
        handler_method="uncertify",
        undo_method="certify",
    ),
    # Tier 3 — Destructive
    "TERMINATE": ActionSpec(
        name="TERMINATE",
        tier=ActionTier.DESTRUCTIVE,
        reversible=False,
        description="Stop and delete the resource. Running work is lost.",
        handler_method="terminate",
    ),
    "DELETE": ActionSpec(
        name="DELETE",
        tier=ActionTier.DESTRUCTIVE,
        reversible=False,
        description="Permanently remove the resource and its configuration.",
        handler_method="delete",
    ),
}


#: What every unresolvable situation collapses to.
SAFE_FALLBACK_ACTION = "WARN"

#: Representative action for each tier, used when stepping a request down.
#: Chosen to be the least surprising member of the tier rather than the mildest,
#: because a downgrade should still express the policy's intent where it can.
TIER_REPRESENTATIVE: Dict[ActionTier, str] = {
    ActionTier.OBSERVE: "FLAG",
    ActionTier.NOTIFY: "WARN",
    ActionTier.RESTRICT: "REVOKE_ACCESS",
    ActionTier.DESTRUCTIVE: "TERMINATE",
}

#: Actions that existed before the ladder. Kept so historical findings still
#: render, and so a policy that hasn't been migrated fails safe rather than
#: falling into the unknown-action path.
LEGACY_ALIASES: Dict[str, str] = {
    "KILL": "TERMINATE",
    "BLOCK": "REVOKE_ACCESS",
}


def normalize_action(raw: object) -> Optional[str]:
    """Coerce a policy's requested action into a registered action name.

    Returns ``None`` when the value cannot be understood — callers must treat
    that as :data:`SAFE_FALLBACK_ACTION`, never as licence to proceed.
    """
    if not isinstance(raw, str):
        return None

    candidate = raw.strip().upper()
    if not candidate:
        return None

    if candidate in ACTIONS:
        return candidate

    aliased = LEGACY_ALIASES.get(candidate)
    if aliased:
        logger.warning(
            "Policy requested legacy action %r; treating it as %r. Update the "
            "policy — legacy aliases will be removed.",
            candidate,
            aliased,
        )
        return aliased

    return None


def get_spec(action: str) -> Optional[ActionSpec]:
    """Look up a registered action, resolving legacy aliases."""
    normalized = normalize_action(action)
    if normalized is None:
        return None
    return ACTIONS[normalized]


def tier_of(action: str) -> ActionTier:
    """Tier for an action. Unknown actions are treated as the safe fallback's."""
    spec = get_spec(action)
    if spec is None:
        return ACTIONS[SAFE_FALLBACK_ACTION].tier
    return spec.tier


def downgrade(action: str) -> str:
    """Step an action down exactly one tier.

    Tier 0 is the floor. The result is the representative action of the tier
    below, which the caller must still check the handler can actually perform —
    a downgrade to ``REVOKE_ACCESS`` is meaningless for a handler that has no
    concept of access.
    """
    spec = get_spec(action)
    if spec is None:
        return SAFE_FALLBACK_ACTION

    if spec.tier <= ActionTier.OBSERVE:
        return spec.name

    lower = ActionTier(spec.tier - 1)
    return TIER_REPRESENTATIVE[lower]


def is_destructive(action: str) -> bool:
    spec = get_spec(action)
    return bool(spec and spec.is_destructive)


def requires_undo_support(action: str) -> bool:
    """Whether performing this action must also record how to reverse it."""
    spec = get_spec(action)
    return bool(spec and spec.tier == ActionTier.RESTRICT)


def all_actions_at_or_below(tier: ActionTier) -> Dict[str, ActionSpec]:
    return {name: spec for name, spec in ACTIONS.items() if spec.tier <= tier}


def describe_ladder() -> list[dict]:
    """Serialisable view of the ladder, for the settings UI and the agent prompt."""
    return [
        {
            "action": spec.name,
            "tier": int(spec.tier),
            "tier_label": TIER_LABELS[spec.tier],
            "reversible": spec.reversible,
            "destructive": spec.is_destructive,
            "description": spec.description,
            "handler_method": spec.handler_method,
            "undo_method": spec.undo_method,
        }
        for spec in sorted(ACTIONS.values(), key=lambda s: (s.tier, s.name))
    ]
