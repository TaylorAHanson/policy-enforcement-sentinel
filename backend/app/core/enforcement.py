"""The enforcement chokepoint.

Every path that acts on a Databricks resource — scheduled scans, manual actions
from the UI, MCP tools, the agent — resolves its intent here first. Nothing
downstream is permitted to decide for itself that an action is safe.

A policy expresses a *request*. This module decides what actually happens, by
walking a fixed set of gates and stepping the request down one tier for each
gate that refuses. The result carries the reason, so a downgrade is visible in
the UI rather than silently swallowed.

The design goal is that destruction requires five independent parties to agree —
the policy author, the platform admin who enabled enforcement, the admin who
named the workspace, the operator who confirmed the run, and the blast-radius
guard. Any one of them declining is enough to stop it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, FrozenSet, List, Optional

from app.core.actions import (
    ACTIONS,
    SAFE_FALLBACK_ACTION,
    ActionTier,
    downgrade,
    get_spec,
    normalize_action,
)

logger = logging.getLogger(__name__)


class ScanMode(str, Enum):
    """How much a run is allowed to do.

    The default is the least capable. Moving up the scale is an explicit,
    per-run decision, not a configuration that drifts.
    """

    AUDIT = "audit"
    """Evaluate and record. Touches nothing, notifies nobody."""

    REMEDIATE = "remediate"
    """Reversible remediation permitted (Tier 2 and below)."""

    ENFORCE = "enforce"
    """Destructive actions eligible, subject to every gate below."""


#: The ceiling each mode imposes, before any other gate is considered.
MODE_CEILING: Dict[ScanMode, ActionTier] = {
    ScanMode.AUDIT: ActionTier.OBSERVE,
    ScanMode.REMEDIATE: ActionTier.RESTRICT,
    ScanMode.ENFORCE: ActionTier.DESTRUCTIVE,
}


# --- Gates ------------------------------------------------------------------

class Gate(str, Enum):
    """The five things that must all agree before anything irreversible runs."""

    POLICY_DECLARES_DESTRUCTIVE = "policy_declares_destructive"
    ENFORCEMENT_ENABLED = "enforcement_enabled"
    WORKSPACE_ALLOWED = "workspace_allowed"
    HUMAN_APPROVAL = "human_approval"
    BLAST_RADIUS = "blast_radius"


GATE_DESCRIPTIONS: Dict[Gate, str] = {
    Gate.POLICY_DECLARES_DESTRUCTIVE: (
        "The rule's METADATA must carry destructive: true. A policy cannot "
        "escalate to Tier 3 by naming the action alone."
    ),
    Gate.ENFORCEMENT_ENABLED: (
        "ENFORCEMENT_ENABLED must be on. It ships off, including on fresh installs."
    ),
    Gate.WORKSPACE_ALLOWED: (
        "The workspace must be named in DESTRUCTIVE_ACTION_WORKSPACES. Nothing is "
        "destructible in a workspace nobody deliberately listed."
    ),
    Gate.HUMAN_APPROVAL: (
        "An operator must have confirmed this specific run. The confirmation is "
        "scoped to one run and expires."
    ),
    Gate.BLAST_RADIUS: (
        "The run must affect fewer than DESTRUCTIVE_ACTION_MAX_RESOURCES resources. "
        "A policy edit that suddenly matches hundreds of resources is refused "
        "wholesale rather than executed."
    ),
}


@dataclass(frozen=True)
class EnforcementApproval:
    """An operator's confirmation that one specific run may act destructively."""

    run_id: str
    approved_by: str
    workspace: str
    expires_at: datetime
    approval_id: Optional[str] = None

    def is_valid_for(self, run_id: str, workspace: str, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return False
        if self.run_id != run_id:
            return False
        # An approval for one workspace must not authorise another.
        return self.workspace in ("*", workspace)


# Only ``resolve_effective_action`` holds this. It is what
# ``providers/databricks/destructive.py`` checks to prove it was reached through
# the chokepoint rather than by someone hand-building an EffectiveAction.
_AUTHORIZATION_TOKEN = object()


@dataclass(frozen=True)
class EffectiveAction:
    """What will actually happen, and why it differs from what was asked."""

    requested_action: str
    action: str
    tier: ActionTier
    requested_tier: ActionTier
    mode: ScanMode
    downgrade_reason: Optional[str] = None
    failed_gates: List[Gate] = field(default_factory=list)
    _token: object = None

    @property
    def downgraded(self) -> bool:
        return self.action != self.requested_action

    @property
    def has_side_effect(self) -> bool:
        spec = get_spec(self.action)
        return bool(spec and spec.has_side_effect)

    @property
    def handler_method(self) -> Optional[str]:
        spec = get_spec(self.action)
        return spec.handler_method if spec else None

    @property
    def undo_method(self) -> Optional[str]:
        spec = get_spec(self.action)
        return spec.undo_method if spec else None

    @property
    def is_destructive(self) -> bool:
        return self.tier >= ActionTier.DESTRUCTIVE

    def is_authorized(self) -> bool:
        """True only for instances produced by :func:`resolve_effective_action`."""
        return self._token is _AUTHORIZATION_TOKEN

    def to_dict(self) -> dict:
        return {
            "requested_action": self.requested_action,
            "effective_action": self.action,
            "tier": int(self.tier),
            "requested_tier": int(self.requested_tier),
            "mode": self.mode.value,
            "downgraded": self.downgraded,
            "downgrade_reason": self.downgrade_reason,
            "failed_gates": [g.value for g in self.failed_gates],
        }


@dataclass
class ActionRequest:
    """Everything the chokepoint needs to decide. Deliberately explicit.

    Nothing here is looked up implicitly. If a caller cannot say which run and
    workspace it is acting in, it cannot act.
    """

    requested_action: object
    resource_type: str
    resource_id: str
    workspace: str
    mode: ScanMode = ScanMode.AUDIT
    run_id: Optional[str] = None
    #: From the rule's ``# METADATA`` block.
    policy_declares_destructive: bool = False
    #: Handler verbs actually implemented for this resource type. ``None`` skips
    #: the capability check, which is only appropriate for a dry run with no
    #: handler in hand.
    supported_methods: Optional[FrozenSet[str]] = None
    approval: Optional[EnforcementApproval] = None
    #: How many Tier 3 actions this run wants in total. Compared against the
    #: blast-radius cap, so one bad policy edit cannot escalate an entire scan.
    destructive_candidate_count: int = 0


def _settings():
    # Imported at call time: DB-backed overrides are applied after import, so a
    # module-level binding would freeze the pre-override values.
    from app.core.config import settings

    return settings


def _enforcement_enabled() -> bool:
    return bool(getattr(_settings(), "ENFORCEMENT_ENABLED", False))


def _allowed_workspaces() -> FrozenSet[str]:
    raw = getattr(_settings(), "DESTRUCTIVE_ACTION_WORKSPACES", "") or ""
    if isinstance(raw, (list, tuple, set)):
        entries = [str(item).strip() for item in raw]
    else:
        entries = [part.strip() for part in str(raw).split(",")]
    return frozenset(entry for entry in entries if entry)


def _blast_radius_cap() -> int:
    try:
        return int(getattr(_settings(), "DESTRUCTIVE_ACTION_MAX_RESOURCES", 5))
    except (TypeError, ValueError):
        # An unparseable cap is not permission to skip the check.
        return 0


def _evaluate_gates(request: ActionRequest) -> List[Gate]:
    """Return the gates that refused. Empty means all five agreed."""
    failed: List[Gate] = []

    if not request.policy_declares_destructive:
        failed.append(Gate.POLICY_DECLARES_DESTRUCTIVE)

    if not _enforcement_enabled():
        failed.append(Gate.ENFORCEMENT_ENABLED)

    allowed = _allowed_workspaces()
    if not request.workspace or request.workspace not in allowed:
        failed.append(Gate.WORKSPACE_ALLOWED)

    approval = request.approval
    if not request.run_id or approval is None or not approval.is_valid_for(
        request.run_id, request.workspace
    ):
        failed.append(Gate.HUMAN_APPROVAL)

    cap = _blast_radius_cap()
    if request.destructive_candidate_count > cap:
        failed.append(Gate.BLAST_RADIUS)

    return failed


def _describe(failed: List[Gate]) -> str:
    if len(failed) == 1:
        return GATE_DESCRIPTIONS[failed[0]]
    joined = ", ".join(gate.value for gate in failed)
    return f"Destructive action refused by {len(failed)} gates: {joined}"


def _supported(request: ActionRequest, action: str) -> bool:
    """Whether the handler can actually perform this action."""
    if request.supported_methods is None:
        return True
    spec = get_spec(action)
    if spec is None:
        return False
    if spec.handler_method is None:
        return True  # No side effect, nothing to support.
    return spec.handler_method in request.supported_methods


def resolve_effective_action(request: ActionRequest) -> EffectiveAction:
    """Decide what may actually be done. The only sanctioned way to act.

    The function never raises on bad input. An unparseable request produces a
    ``WARN``, because a caller handling an exception here would be a caller
    deciding for itself what to do next.
    """
    normalized = normalize_action(request.requested_action)

    if normalized is None:
        logger.error(
            "Unrecognised action %r requested for %s/%s in %s; falling back to %s. "
            "This usually means a policy failed to evaluate or returned an "
            "unexpected shape.",
            request.requested_action,
            request.resource_type,
            request.resource_id,
            request.workspace,
            SAFE_FALLBACK_ACTION,
        )
        fallback_tier = ACTIONS[SAFE_FALLBACK_ACTION].tier
        return _finalize(
            request,
            requested_action=str(request.requested_action),
            requested_tier=fallback_tier,
            action=SAFE_FALLBACK_ACTION,
            reason=(
                f"Action {request.requested_action!r} is not recognised. Falling back "
                f"to {SAFE_FALLBACK_ACTION} — an unknown action is never treated as "
                "permission to act."
            ),
            failed_gates=[],
        )

    spec = ACTIONS[normalized]
    requested_tier = spec.tier
    action = normalized
    reasons: List[str] = []
    failed_gates: List[Gate] = []

    # Gate set one: destructive requests must satisfy all five.
    if spec.is_destructive:
        failed_gates = _evaluate_gates(request)
        if failed_gates:
            action = downgrade(action)
            reasons.append(_describe(failed_gates))

    # Gate set two: the run's mode is a hard ceiling regardless of the rest.
    ceiling = MODE_CEILING[request.mode]
    while ACTIONS[action].tier > ceiling:
        stepped = downgrade(action)
        if stepped == action:  # already at the floor
            break
        action = stepped
        reasons.append(
            f"Run mode is {request.mode.value}, which permits at most "
            f"{ceiling.name.lower()} actions."
        )

    # Gate set three: the handler has to be able to do it. A downgrade to
    # REVOKE_ACCESS means nothing for a resource type with no concept of access.
    guard = 0
    while not _supported(request, action) and guard < len(ACTIONS):
        guard += 1
        stepped = downgrade(action)
        reasons.append(
            f"Handler for {request.resource_type} does not implement "
            f"{ACTIONS[action].handler_method!r}."
        )
        if stepped == action:
            action = SAFE_FALLBACK_ACTION
            break
        action = stepped

    if not _supported(request, action):
        # Even the fallback is unavailable; record only.
        action = "FLAG"
        reasons.append(
            f"Handler for {request.resource_type} cannot notify either; recording only."
        )

    return _finalize(
        request,
        requested_action=normalized,
        requested_tier=requested_tier,
        action=action,
        reason=" ".join(dict.fromkeys(reasons)) if reasons else None,
        failed_gates=failed_gates,
    )


def _finalize(
    request: ActionRequest,
    *,
    requested_action: str,
    requested_tier: ActionTier,
    action: str,
    reason: Optional[str],
    failed_gates: List[Gate],
) -> EffectiveAction:
    effective = EffectiveAction(
        requested_action=requested_action,
        action=action,
        tier=ACTIONS[action].tier,
        requested_tier=requested_tier,
        mode=request.mode,
        downgrade_reason=reason if action != requested_action else None,
        failed_gates=failed_gates,
        _token=_AUTHORIZATION_TOKEN,
    )

    if effective.downgraded:
        logger.info(
            "Downgraded %s -> %s for %s/%s in %s: %s",
            requested_action,
            action,
            request.resource_type,
            request.resource_id,
            request.workspace,
            reason,
        )

    return effective


def count_destructive_candidates(requested_actions: List[object]) -> int:
    """How many of these requests are destructive, for the blast-radius gate."""
    total = 0
    for raw in requested_actions:
        normalized = normalize_action(raw)
        if normalized and ACTIONS[normalized].is_destructive:
            total += 1
    return total


def describe_gates() -> List[dict]:
    """Serialisable gate documentation, rendered in the Settings danger group."""
    return [
        {"gate": gate.value, "description": GATE_DESCRIPTIONS[gate]}
        for gate in Gate
    ]
