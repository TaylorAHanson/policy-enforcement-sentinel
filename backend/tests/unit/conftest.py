"""Guards that apply to the unit suite only.

Integration tests get their own conftest and are allowed to talk to things.
"""
import pytest


@pytest.fixture(autouse=True)
def no_live_databricks(monkeypatch):
    """Make a real Databricks client fail instantly instead of hanging.

    `DatabricksProvider.__init__` builds a `WorkspaceClient` eagerly, and the
    SDK's OAuth flow waits five minutes before giving up. A unit test that
    constructs the provider by accident therefore does not fail — it stalls, and
    only if no token happens to be cached. The suite ran in fifty seconds on a
    machine with fresh credentials and fifteen minutes on one without, which
    reads as a flaky hang rather than as a test reaching the network.

    Tests that want a client still patch `WorkspaceClient` themselves; their
    monkeypatch runs after this one and wins. What this stops is the accidental
    case, and it stops it in milliseconds with a message saying what happened.
    """

    def refuse(*args, **kwargs):
        raise AssertionError(
            "A unit test tried to build a real Databricks WorkspaceClient. "
            "Construct the service with SentinelService.__new__, or patch the "
            "client, rather than letting the SDK attempt live authentication."
        )

    monkeypatch.setattr(
        "app.providers.databricks.client.WorkspaceClient", refuse, raising=False
    )
