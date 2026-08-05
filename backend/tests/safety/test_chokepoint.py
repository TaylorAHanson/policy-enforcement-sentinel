"""The five gates, one at a time.

Each gate is opened individually with every other gate already open, so a test
failing here names exactly which gate stopped guarding. A single test that opens
all five and checks the happy path would pass even if four of them had been
deleted.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.actions import ActionTier
from app.core.enforcement import (
    ActionRequest,
    EffectiveAction,
    EnforcementApproval,
    Gate,
    ScanMode,
    count_destructive_candidates,
    resolve_effective_action,
)

pytestmark = pytest.mark.safety

RUN_ID = "run-1"
WORKSPACE = "prod-analytics"


@pytest.fixture
def all_gates_open(monkeypatch):
    """Every gate satisfied. Individual tests close exactly one."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENFORCEMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "DESTRUCTIVE_ACTION_WORKSPACES", WORKSPACE, raising=False
    )
    monkeypatch.setattr(settings, "DESTRUCTIVE_ACTION_MAX_RESOURCES", 5, raising=False)
    return settings


def approval(**overrides) -> EnforcementApproval:
    defaults = dict(
        run_id=RUN_ID,
        approved_by="operator@company.com",
        workspace=WORKSPACE,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    defaults.update(overrides)
    return EnforcementApproval(**defaults)


def destructive_request(**overrides) -> ActionRequest:
    defaults = dict(
        requested_action="DELETE",
        resource_type="dashboard",
        resource_id="dash-1",
        workspace=WORKSPACE,
        mode=ScanMode.ENFORCE,
        run_id=RUN_ID,
        policy_declares_destructive=True,
        approval=approval(),
        destructive_candidate_count=1,
    )
    defaults.update(overrides)
    return ActionRequest(**defaults)


# --- The permitted case -----------------------------------------------------


def test_destructive_action_survives_when_all_five_gates_agree(all_gates_open):
    """The one path to Tier 3. If this fails, the gates are unreachable."""
    result = resolve_effective_action(destructive_request())
    assert result.action == "DELETE"
    assert result.tier == ActionTier.DESTRUCTIVE
    assert not result.downgraded
    assert result.failed_gates == []


# --- Each gate, individually ------------------------------------------------


def test_gate_policy_declares_destructive(all_gates_open):
    result = resolve_effective_action(
        destructive_request(policy_declares_destructive=False)
    )
    assert Gate.POLICY_DECLARES_DESTRUCTIVE in result.failed_gates
    assert result.tier < ActionTier.DESTRUCTIVE
    assert result.downgrade_reason


def test_gate_enforcement_enabled(all_gates_open, monkeypatch):
    monkeypatch.setattr(all_gates_open, "ENFORCEMENT_ENABLED", False, raising=False)
    result = resolve_effective_action(destructive_request())
    assert Gate.ENFORCEMENT_ENABLED in result.failed_gates
    assert result.tier < ActionTier.DESTRUCTIVE


def test_gate_workspace_allowed(all_gates_open):
    result = resolve_effective_action(destructive_request(workspace="some-other-ws"))
    assert Gate.WORKSPACE_ALLOWED in result.failed_gates
    assert result.tier < ActionTier.DESTRUCTIVE


def test_gate_human_approval_missing(all_gates_open):
    result = resolve_effective_action(destructive_request(approval=None))
    assert Gate.HUMAN_APPROVAL in result.failed_gates
    assert result.tier < ActionTier.DESTRUCTIVE


def test_gate_blast_radius(all_gates_open):
    result = resolve_effective_action(destructive_request(destructive_candidate_count=6))
    assert Gate.BLAST_RADIUS in result.failed_gates
    assert result.tier < ActionTier.DESTRUCTIVE


# --- Approval scoping -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, why",
    [
        ({"run_id": "some-other-run"}, "an approval for one run must not authorise another"),
        ({"workspace": "some-other-ws"}, "an approval is scoped to its workspace"),
        (
            {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)},
            "an expired approval is not an approval",
        ),
    ],
)
def test_approval_does_not_transfer(all_gates_open, overrides, why):
    result = resolve_effective_action(
        destructive_request(approval=approval(**overrides))
    )
    assert Gate.HUMAN_APPROVAL in result.failed_gates, why


def test_naive_expiry_is_treated_as_utc(all_gates_open):
    """A naive datetime must not compare as "not yet expired" by accident."""
    naive_future = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(
        tzinfo=None
    )
    result = resolve_effective_action(
        destructive_request(approval=approval(expires_at=naive_future))
    )
    assert Gate.HUMAN_APPROVAL not in result.failed_gates


# --- Mode ceiling -----------------------------------------------------------


@pytest.mark.parametrize(
    "mode, ceiling",
    [
        (ScanMode.AUDIT, ActionTier.OBSERVE),
        (ScanMode.REMEDIATE, ActionTier.RESTRICT),
        (ScanMode.ENFORCE, ActionTier.DESTRUCTIVE),
    ],
)
def test_mode_is_a_hard_ceiling(all_gates_open, mode, ceiling):
    """Mode caps the outcome even when every gate agrees."""
    result = resolve_effective_action(destructive_request(mode=mode))
    assert result.tier <= ceiling


def test_audit_mode_never_has_a_side_effect(all_gates_open):
    for action in ("DELETE", "TERMINATE", "REVOKE_ACCESS", "QUARANTINE", "WARN"):
        result = resolve_effective_action(
            destructive_request(requested_action=action, mode=ScanMode.AUDIT)
        )
        assert not result.has_side_effect, (
            f"{action} produced a side effect in audit mode"
        )


# --- Malformed input --------------------------------------------------------


@pytest.mark.parametrize(
    "garbage",
    [None, "", "OBLITERATE", 42, [], {}, "delete; drop table", object()],
)
def test_unrecognised_actions_resolve_to_warn(all_gates_open, garbage):
    """A policy that fails to evaluate must never be read as permission to act.

    This is the highest-value test in the suite. Malformed policy output is the
    realistic path to an unintended action: a rule returning the wrong shape,
    an OPA upgrade changing a result, a typo in `requested_action`.
    """
    result = resolve_effective_action(
        destructive_request(requested_action=garbage, mode=ScanMode.ENFORCE)
    )
    assert result.action == "WARN"
    assert result.tier == ActionTier.NOTIFY
    assert result.downgrade_reason


def test_resolution_never_raises(all_gates_open):
    """A caller catching an exception here would be deciding for itself."""
    for bad in (None, object(), {"nested": ["nonsense"]}):
        resolve_effective_action(
            ActionRequest(
                requested_action=bad,
                resource_type="",
                resource_id="",
                workspace="",
                mode=ScanMode.ENFORCE,
            )
        )


# --- Handler capability -----------------------------------------------------


def test_unsupported_action_is_downgraded_not_attempted(all_gates_open):
    """A handler that cannot revoke access must not be asked to."""
    result = resolve_effective_action(
        destructive_request(
            requested_action="REVOKE_ACCESS",
            mode=ScanMode.REMEDIATE,
            supported_methods=frozenset({"warn"}),
        )
    )
    assert result.action != "REVOKE_ACCESS"
    assert result.handler_method in (None, "warn")


def test_handler_with_no_capabilities_records_only(all_gates_open):
    result = resolve_effective_action(
        destructive_request(
            requested_action="DELETE",
            supported_methods=frozenset(),
        )
    )
    assert not result.has_side_effect


# --- The authorization token ------------------------------------------------


def test_only_the_chokepoint_produces_an_authorized_action(all_gates_open):
    """A hand-built EffectiveAction must not pass as authorized.

    This is what `providers/databricks/destructive.py` checks. Without it,
    constructing the dataclass directly would be a way around every gate above.
    """
    assert resolve_effective_action(destructive_request()).is_authorized()

    forged = EffectiveAction(
        requested_action="DELETE",
        action="DELETE",
        tier=ActionTier.DESTRUCTIVE,
        requested_tier=ActionTier.DESTRUCTIVE,
        mode=ScanMode.ENFORCE,
    )
    assert not forged.is_authorized()


# --- Blast-radius counting --------------------------------------------------


def test_blast_radius_counts_only_destructive_requests():
    actions = ["WARN", "DELETE", "REVOKE_ACCESS", "TERMINATE", "FLAG", "nonsense"]
    assert count_destructive_candidates(actions) == 2
