"""The assistant's tool surface is read-only, structurally.

The Q&A loop hands a model a set of functions and lets it choose. So the useful
question is not "does the assistant behave" but "what is the worst thing the
tool list permits". These tests answer that by reading the module rather than by
exercising it, which is what makes them hold for tools nobody has written yet.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.agents import tools as tools_module

TOOLS_SOURCE = Path(inspect.getfile(tools_module))

#: Importing any of these into the tool module would give the assistant a way to
#: change a resource. The confinement is an import-level fact, so it is checked
#: at import level and shows up in review as a new import line.
FORBIDDEN_IMPORTS = (
    "app.providers.databricks.handlers",
    "app.providers.databricks.destructive",
    "app.services.action_executor",
    "app.core.enforcement",
)


def imported_modules() -> set[str]:
    """Every module named by an import anywhere in the file, including inside
    functions — the tool bodies import lazily."""
    tree = ast.parse(TOOLS_SOURCE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("module", FORBIDDEN_IMPORTS)
def test_the_tool_module_cannot_reach_anything_that_acts(module):
    assert module not in imported_modules(), (
        f"{TOOLS_SOURCE.name} imports {module}, which puts a way to change a "
        "resource within reach of the assistant."
    )


def test_the_tool_list_is_fixed_at_import_time():
    """Dynamic registration would move the answer to "what can it do" at runtime."""
    assert isinstance(tools_module._TOOL_SPECS, list)
    assert tools_module._TOOL_SPECS


def test_narrowing_the_tool_set_cannot_widen_it():
    every = {tool.name for tool in tools_module.build_tools()}
    requested = tools_module.build_tools(["list_policies", "not_a_real_tool"])

    assert {tool.name for tool in requested} == {"list_policies"}
    assert "not_a_real_tool" not in every


def test_no_tool_is_named_after_an_action():
    """A tool called `terminate` would be one review away from doing it."""
    from app.core.actions import ACTIONS

    verbs = {
        spec.handler_method
        for spec in ACTIONS.values()
        if spec.handler_method
    }
    overlap = verbs & set(tools_module.tool_names())
    assert not overlap, f"Tools named after action verbs: {overlap}"


def test_every_tool_declares_a_schema_and_a_handler():
    for tool in tools_module.build_tools():
        assert tool.description, f"{tool.name} has no description for the model"
        assert tool.parameters.get("type") == "object"
        assert callable(tool.handler)


# --- Untrusted input --------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "../../../../etc/passwd",
        "../app/core/config.py",
        "/etc/passwd",
        "..%2f..%2fetc%2fpasswd",
    ],
)
async def test_a_policy_name_cannot_escape_the_policy_directory(name):
    """The model chooses this string, so it is untrusted input on a path."""
    result = await tools_module._read_policy({"policy_name": name})
    assert isinstance(result, str) and result.startswith("No policy named")


@pytest.mark.asyncio
async def test_a_missing_policy_name_is_reported_not_raised():
    """An exception here ends the loop; a message lets the model correct itself."""
    result = await tools_module._read_policy({})
    assert "required" in result


@pytest.mark.asyncio
async def test_the_enforcement_status_tool_says_what_would_actually_happen(app_db):
    """Answering from the requested action is the one guaranteed-wrong answer."""
    status = await tools_module._get_enforcement_status({})

    assert "enforcement_enabled" in status
    assert "action_ladder" in status
    assert "WARN" in status["note"]


@pytest.mark.asyncio
async def test_findings_are_capped_before_reaching_the_model(app_db, db_session):
    """Tens of thousands of rows would blow the context window and the bill."""
    from tests.factories import SentinelFindingFactory, SentinelRunFactory

    run = SentinelRunFactory.create(db_session)
    overflow = tools_module._MAX_ROWS + 25
    SentinelFindingFactory.create_many(db_session, run.id, overflow)

    result = await tools_module._search_findings({"run_id": run.id})

    assert result["total_matching"] == overflow
    assert result["returned"] == tools_module._MAX_ROWS
    assert len(result["findings"]) == tools_module._MAX_ROWS
