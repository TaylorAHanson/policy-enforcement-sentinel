"""Irreversible SDK calls live in exactly one module.

A source-level check, because this is a property of the codebase rather than of
any runtime path. The value is that it fails in the pull request that introduces
a second call site, at which point moving the call into ``destructive.py`` is a
two-line change — rather than a year later, when it is load-bearing.
"""
import ast
import re
from pathlib import Path

import pytest

from app.providers.databricks.destructive import (
    CONFINED_SDK_CALLS,
    UnauthorizedDestructiveCall,
)

pytestmark = pytest.mark.safety

#: Where the confined calls are permitted. Nothing else may name them.
ALLOWED_FILES = {"destructive.py"}

#: Modules that legitimately mention the call names as strings — this test
#: itself, and the registry that documents them.
EXEMPT_PATHS = {"tests"}


def _app_sources() -> list[Path]:
    app_dir = Path(__file__).resolve().parents[2] / "app"
    return [
        path
        for path in app_dir.rglob("*.py")
        if not any(part in EXEMPT_PATHS for part in path.parts)
        and "__pycache__" not in path.parts
    ]


def test_destructive_sdk_calls_appear_only_in_destructive_py():
    offenders = []
    patterns = {call: re.compile(rf"\b{re.escape(call)}\s*\(") for call in CONFINED_SDK_CALLS}

    for path in _app_sources():
        if path.name in ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for call, pattern in patterns.items():
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line} calls {call}()")

    assert not offenders, (
        "Destructive SDK calls outside providers/databricks/destructive.py:\n  "
        + "\n  ".join(offenders)
        + "\n\nAdd the call to destructive.py — where it will demand an "
        "authorised EffectiveAction — and call that from here."
    )


def test_every_confined_function_demands_authorization():
    """Each public function in `destructive.py` must call `_require_authorization`.

    A new function added without the check would be a destructive call with no
    gates in front of it, and it would look exactly like its neighbours.
    """
    path = Path(__file__).resolve().parents[2] / "app/providers/databricks/destructive.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    missing = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        calls = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        if "_require_authorization" not in calls:
            missing.append(node.name)

    assert not missing, (
        "Functions in destructive.py that do not check authorization: "
        + ", ".join(missing)
    )


def test_every_confined_function_takes_authorization_keyword_only():
    """`authorization` must be keyword-only, so it cannot be passed positionally.

    A positional argument can be supplied by accident from a `*args` forward.
    Keyword-only means every call site names it.
    """
    path = Path(__file__).resolve().parents[2] / "app/providers/databricks/destructive.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        kwonly = {arg.arg for arg in node.args.kwonlyargs}
        if "authorization" not in kwonly:
            offenders.append(node.name)

    assert not offenders, (
        "Functions not taking a keyword-only `authorization`: " + ", ".join(offenders)
    )


class _FakeWorkspaceClient:
    """Records nothing, because nothing should reach it."""

    def __getattr__(self, name):
        raise AssertionError(
            f"An unauthorized destructive call reached the SDK ({name})."
        )


@pytest.mark.parametrize(
    "authorization",
    [None, "DELETE", 0, object(), {"action": "DELETE"}],
)
def test_destructive_calls_refuse_a_non_effective_action(authorization):
    from app.providers.databricks import destructive

    with pytest.raises(UnauthorizedDestructiveCall):
        destructive.delete_job(
            _FakeWorkspaceClient(), "123", authorization=authorization
        )


def test_destructive_calls_refuse_a_forged_effective_action():
    """The dataclass can be constructed; it just cannot be authorised."""
    from app.core.actions import ActionTier
    from app.core.enforcement import EffectiveAction, ScanMode
    from app.providers.databricks import destructive

    forged = EffectiveAction(
        requested_action="DELETE",
        action="DELETE",
        tier=ActionTier.DESTRUCTIVE,
        requested_tier=ActionTier.DESTRUCTIVE,
        mode=ScanMode.ENFORCE,
    )

    with pytest.raises(UnauthorizedDestructiveCall):
        destructive.delete_job(_FakeWorkspaceClient(), "123", authorization=forged)


def test_destructive_calls_refuse_a_downgraded_authorization():
    """A real authorisation for WARN must not open the destructive path."""
    from app.core.enforcement import ActionRequest, ScanMode, resolve_effective_action
    from app.providers.databricks import destructive

    downgraded = resolve_effective_action(
        ActionRequest(
            requested_action="DELETE",
            resource_type="job",
            resource_id="123",
            workspace="unlisted",
            mode=ScanMode.ENFORCE,
        )
    )
    assert downgraded.is_authorized()
    assert not downgraded.is_destructive

    with pytest.raises(UnauthorizedDestructiveCall):
        destructive.delete_job(_FakeWorkspaceClient(), "123", authorization=downgraded)
