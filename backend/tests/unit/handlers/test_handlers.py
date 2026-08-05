"""Handlers: discovery, error propagation, and declared capabilities.

The previous version of this file called ``handler.kill()`` on every handler.
That method no longer exists, and its removal is the point: capability is now
nominal, so a handler can only be asked to delete something if it inherits
:class:`SupportsDelete`. These tests assert the declarations rather than the
call, because the declaration is what the chokepoint reads.
"""
from unittest.mock import MagicMock

import pytest

from app.providers.databricks.handlers import HANDLER_REGISTRY
from app.providers.databricks.handlers.app_handler import AppResourceHandler
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsTerminate,
    supported_methods,
)
from app.providers.databricks.handlers.cluster_handler import ClusterResourceHandler
from app.providers.databricks.handlers.job_handler import JobResourceHandler
from app.providers.databricks.handlers.sql_warehouse_handler import (
    SqlWarehouseResourceHandler,
)


# --- Discovery --------------------------------------------------------------


async def test_app_handler_discovers_apps():
    client = MagicMock()
    app = MagicMock()
    app.name = "test-app"
    app.creator = "user@company.com"
    client.apps.list.return_value = [app]

    resources = await AppResourceHandler(client).discover()
    assert [r["id"] for r in resources] == ["test-app"]
    assert resources[0]["type"] == "app"


async def test_cluster_handler_discovers_clusters():
    client = MagicMock()
    cluster = MagicMock()
    cluster.cluster_id = "0101-cluster"
    client.clusters.list.return_value = [cluster]

    resources = await ClusterResourceHandler(client).discover()
    assert [r["id"] for r in resources] == ["0101-cluster"]


async def test_job_handler_discovers_jobs():
    client = MagicMock()
    job = MagicMock()
    job.job_id = 123
    client.jobs.list.return_value = [job]

    resources = await JobResourceHandler(client).discover()
    assert resources[0]["id"] == "123"


async def test_warehouse_handler_discovers_warehouses():
    client = MagicMock()
    warehouse = MagicMock()
    warehouse.id = "wh-123"
    client.warehouses.list.return_value = [warehouse]

    resources = await SqlWarehouseResourceHandler(client).discover()
    assert [r["id"] for r in resources] == ["wh-123"]


# --- Error propagation ------------------------------------------------------


@pytest.mark.parametrize(
    "handler_class, sdk_path",
    [
        (AppResourceHandler, "apps"),
        (ClusterResourceHandler, "clusters"),
        (JobResourceHandler, "jobs"),
        (SqlWarehouseResourceHandler, "warehouses"),
    ],
)
async def test_discovery_errors_propagate(handler_class, sdk_path):
    """A failed lookup must not read as an empty workspace.

    Swallowing the exception turns "we could not look" into "there is nothing
    there", which the dashboard renders as compliant — the single most
    dangerous way for this system to be wrong.
    """
    client = MagicMock()
    service = getattr(client, sdk_path)
    for method in ("list", "list_pipelines"):
        if hasattr(service, method):
            getattr(service, method).side_effect = PermissionError("403 Forbidden")

    with pytest.raises(Exception):
        await handler_class(client).discover()


# --- Capabilities -----------------------------------------------------------


def test_no_handler_can_be_asked_to_act_by_accident():
    """`supported_methods` reflects inheritance, not method names.

    A handler that grows a method called `delete` for unrelated reasons does not
    thereby become deletable — this is what replaced the old `hasattr(handler,
    "kill")` dispatch.
    """

    class Impostor(BaseResourceHandler):
        resource_type = "impostor"

        async def discover(self):
            return []

        async def delete(self, resource_id, *, authorization=None):  # noqa: D401
            raise AssertionError("should never be reached")

    handler = Impostor(workspace_client=MagicMock())
    assert "delete" not in supported_methods(handler)
    assert supported_methods(handler) == frozenset({"warn"})


def test_every_registered_handler_can_warn():
    """WARN is the floor the safety model falls back to, so it must always exist."""
    for resource_type, handler_class in HANDLER_REGISTRY.items():
        handler = handler_class(MagicMock())
        assert "warn" in supported_methods(handler), (
            f"{resource_type} cannot warn, so a downgrade would land on nothing."
        )


def test_destructive_handlers_declare_their_capability_explicitly():
    """Anything with a Tier 3 verb inherits the corresponding mixin."""
    for resource_type, handler_class in HANDLER_REGISTRY.items():
        methods = supported_methods(handler_class(MagicMock()))
        if "delete" in methods:
            assert issubclass(handler_class, SupportsDelete), resource_type
        if "terminate" in methods:
            assert issubclass(handler_class, SupportsTerminate), resource_type


def test_every_reversible_capability_comes_with_its_undo():
    """A Tier 2 action with no undo is a Tier 3 action in disguise."""
    pairs = [
        ("revoke_access", "restore_access"),
        ("quarantine", "unquarantine"),
        ("disable", "enable"),
        ("throttle", "unthrottle"),
        ("annotate", "unannotate"),
    ]
    for resource_type, handler_class in HANDLER_REGISTRY.items():
        methods = supported_methods(handler_class(MagicMock()))
        for action, undo in pairs:
            if action in methods:
                assert undo in methods, (
                    f"{resource_type} supports {action} but not {undo}."
                )


def test_the_registry_covers_every_resource_type_handlers_declare():
    for resource_type, handler_class in HANDLER_REGISTRY.items():
        assert handler_class.resource_type == resource_type, (
            f"{handler_class.__name__} is registered under {resource_type!r} but "
            f"declares {handler_class.resource_type!r}."
        )
