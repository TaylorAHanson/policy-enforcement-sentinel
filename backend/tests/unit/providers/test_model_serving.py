"""Gateway routing, retries, and response shapes.

The gateway route is preferred because rate limiting, cost controls, guardrails,
and payload logging are configured there rather than in this codebase. A silent
fall-through to the direct endpoint would bypass all of it, so most of what is
asserted here is *when the fallback is allowed to happen*.

Every test drives a fake transport. Nothing reaches the network.
"""
from __future__ import annotations

import httpx
import pytest

from app.providers.model_serving.client import (
    AI_GATEWAY_PATH,
    ChatMessage,
    ModelServingClient,
    ModelServingError,
)
from app.providers.model_serving import client as client_module

HOST = "https://example.cloud.databricks.com"


def completion(content: str = "ok") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def transport(monkeypatch):
    """Record every request and reply from a scripted queue."""
    state = {"requests": [], "responses": [], "sleeps": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if not state["responses"]:
            return httpx.Response(200, json=completion())
        nxt = state["responses"].pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    fake = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client_module, "_get_client", lambda timeout: fake)

    async def no_sleep(seconds):
        state["sleeps"].append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)
    return state


@pytest.fixture
def make_client(monkeypatch):
    def _make(**kwargs):
        kwargs.setdefault("gateway_model", "system.ai.gpt-5-6-luna")
        kwargs.setdefault("endpoint_name", "")
        client = ModelServingClient(host=HOST, token="dapi-test", **kwargs)
        monkeypatch.setattr(
            client, "_resolve_credentials", lambda: (HOST, "dapi-test")
        )
        return client

    return _make


def ask(client, **kwargs):
    return client.chat([ChatMessage(role="user", content="hello")], **kwargs)


# --- Routing ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_gateway_is_used_when_a_model_is_configured(transport, make_client):
    await ask(make_client())

    request = transport["requests"][0]
    assert request.url.path == AI_GATEWAY_PATH
    assert '"model"' in request.content.decode()


@pytest.mark.asyncio
async def test_the_direct_endpoint_names_the_model_in_the_url(transport, make_client):
    client = make_client(gateway_model="", endpoint_name="sentinel-agent-llm")
    await ask(client)

    request = transport["requests"][0]
    assert request.url.path == "/serving-endpoints/sentinel-agent-llm/invocations"
    assert '"model"' not in request.content.decode()


@pytest.mark.asyncio
async def test_a_missing_gateway_route_falls_through_to_the_endpoint(
    transport, make_client
):
    """404 means "this deployment has no gateway", which the fallback exists for."""
    transport["responses"] = [
        httpx.Response(404, text="not found"),
        httpx.Response(200, json=completion("from the endpoint")),
    ]
    client = make_client(endpoint_name="sentinel-agent-llm")

    message = await ask(client)

    assert message["content"] == "from the endpoint"
    assert [r.url.path for r in transport["requests"]] == [
        AI_GATEWAY_PATH,
        "/serving-endpoints/sentinel-agent-llm/invocations",
    ]


@pytest.mark.asyncio
async def test_a_rejected_request_does_not_fall_through(transport, make_client):
    """A 400 is our bug. Retrying past the gateway would evade its guardrails."""
    transport["responses"] = [httpx.Response(400, text="bad tool schema")]
    client = make_client(endpoint_name="sentinel-agent-llm")

    with pytest.raises(ModelServingError) as exc:
        await ask(client)

    assert exc.value.status == 400
    assert len(transport["requests"]) == 1


@pytest.mark.asyncio
async def test_an_auth_failure_does_not_fall_through(transport, make_client):
    """A 403 on the gateway is a permissions problem, not a routing one."""
    transport["responses"] = [httpx.Response(403, text="forbidden")]
    client = make_client(endpoint_name="sentinel-agent-llm")

    with pytest.raises(ModelServingError):
        await ask(client)

    assert len(transport["requests"]) == 1


# --- Credentials ------------------------------------------------------------
#
# The assistant must authenticate to the same workspace as the scanner. It did
# not: it built a bare WorkspaceClient(), which ignores backend/.env — pydantic
# loads that into `settings`, not into os.environ — and silently authenticated
# as whatever ~/.databrickscfg named as DEFAULT. The visible symptom was an
# expired CLI session reported as a model serving failure, which points at the
# wrong subsystem entirely.


@pytest.fixture
def configured(monkeypatch):
    """Workspace credentials present in settings, nothing in the environment."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABRICKS_HOST", HOST)
    monkeypatch.setattr(settings, "DATABRICKS_TOKEN", "dapi-from-env-file")
    monkeypatch.setattr(settings, "DATABRICKS_CLIENT_ID", None)
    monkeypatch.setattr(settings, "DATABRICKS_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")
    return settings


def test_the_configured_workspace_credentials_are_used(configured, monkeypatch):
    """Without this the SDK falls through to the CLI profile."""

    def explode():
        raise AssertionError(
            "fell through to the ambient SDK chain despite configured credentials"
        )

    monkeypatch.setattr(
        "databricks.sdk.WorkspaceClient", lambda *a, **k: explode(), raising=False
    )

    host, token = ModelServingClient()._resolve_credentials()

    assert host == HOST
    assert token == "dapi-from-env-file"


def test_the_assistant_and_the_scanner_share_a_host(configured):
    """Two subsystems authenticating to different workspaces is a support case
    nobody enjoys."""
    from app.core.config import settings

    assert ModelServingClient()._resolve_credentials()[0] == settings.DATABRICKS_HOST.rstrip("/")


def test_an_explicit_token_still_wins(configured):
    """A caller passing credentials means to override the configuration."""
    client = ModelServingClient(host="https://other.databricks.com", token="explicit")
    assert client._resolve_credentials() == ("https://other.databricks.com", "explicit")


def test_a_trailing_slash_on_the_host_does_not_double_up(monkeypatch):
    """Profiles routinely store the host with a trailing slash."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")
    client = ModelServingClient(host=f"{HOST}/", token="t")

    assert client._resolve_credentials()[0] == HOST


BARE_HOST = "adb-2548836972759138.18.azuredatabricks.net"


def test_a_host_without_a_scheme_is_still_a_usable_url(monkeypatch):
    """A deployed App is handed DATABRICKS_HOST as a bare hostname.

    The SDK prepends https:// itself, so every WorkspaceClient path works and
    this stays invisible until something builds a URL by hand — where httpx
    refuses it for having no protocol, and the assistant fails in a deployment
    that works locally.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")
    client = ModelServingClient(host=BARE_HOST, token="t")

    assert client._resolve_credentials()[0] == f"https://{BARE_HOST}"


def test_the_settings_host_is_qualified_wherever_it_came_from(monkeypatch):
    """Assignment is validated too, so a bare host from the Settings page or a
    test double is normalised the same way one from the environment is."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABRICKS_HOST", BARE_HOST)

    assert settings.DATABRICKS_HOST == f"https://{BARE_HOST}"


def test_routes_built_from_a_bare_host_carry_a_protocol(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")
    client = ModelServingClient(
        host=BARE_HOST, token="t", gateway_model="system.ai.gpt-5-6-luna"
    )
    host, _ = client._resolve_credentials()

    for _label, url, _model in client._routes(host):
        assert url.startswith("https://")
        assert httpx.URL(url).host == BARE_HOST


def test_a_service_principal_is_passed_to_the_sdk(monkeypatch):
    """Non-expiring credentials, so they must not be dropped in favour of the
    ambient chain."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABRICKS_HOST", HOST)
    monkeypatch.setattr(settings, "DATABRICKS_TOKEN", None)
    monkeypatch.setattr(settings, "DATABRICKS_CLIENT_ID", "client-abc")
    monkeypatch.setattr(settings, "DATABRICKS_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")

    captured = {}

    class FakeWorkspaceClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.config = type(
                "Cfg",
                (),
                {
                    "host": HOST,
                    "authenticate": lambda self: {"Authorization": "Bearer minted"},
                },
            )()

    monkeypatch.setattr(
        "databricks.sdk.WorkspaceClient", FakeWorkspaceClient, raising=False
    )

    host, token = ModelServingClient()._resolve_credentials()

    assert captured == {
        "host": HOST,
        "client_id": "client-abc",
        "client_secret": "secret-xyz",
    }
    assert (host, token) == (HOST, "minted")


def test_an_expired_cli_session_names_the_remedy(monkeypatch):
    """The original error said only "could not authenticate", which sent the
    reader looking at model serving rather than at their CLI login."""
    from app.core.config import settings

    for field in (
        "DATABRICKS_HOST",
        "DATABRICKS_WORKSPACE_URL",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
    ):
        monkeypatch.setattr(settings, field, None)
    monkeypatch.setattr(settings, "MODEL_SERVING_API_KEY", "")

    class DeadSession:
        def __init__(self, **kwargs):
            raise RuntimeError("refresh token is invalid")

    monkeypatch.setattr("databricks.sdk.WorkspaceClient", DeadSession, raising=False)

    with pytest.raises(ModelServingError) as exc:
        ModelServingClient()._resolve_credentials()

    assert "refresh token is invalid" in str(exc.value)


@pytest.mark.asyncio
async def test_nothing_configured_is_a_clear_error(make_client):
    client = make_client(gateway_model="", endpoint_name="")
    assert client.configured is False

    with pytest.raises(ModelServingError, match="No model is configured"):
        await ask(client)


# --- Retries ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cold_endpoint_is_retried(transport, make_client):
    """Scale-to-zero serving returns 503 while a replica starts."""
    transport["responses"] = [
        httpx.Response(503, text="starting"),
        httpx.Response(200, json=completion("awake")),
    ]

    message = await ask(make_client())

    assert message["content"] == "awake"
    assert len(transport["requests"]) == 2


@pytest.mark.asyncio
async def test_retries_back_off_and_then_give_up(transport, make_client):
    transport["responses"] = [httpx.Response(429, text="slow down")] * 5

    with pytest.raises(ModelServingError):
        await ask(make_client())

    assert len(transport["requests"]) == client_module._MAX_ATTEMPTS
    assert transport["sleeps"] == sorted(transport["sleeps"]), "backoff did not grow"


@pytest.mark.asyncio
async def test_a_connection_error_is_retried(transport, make_client):
    transport["responses"] = [
        httpx.ConnectError("connection reset"),
        httpx.Response(200, json=completion("recovered")),
    ]

    message = await ask(make_client())
    assert message["content"] == "recovered"


# --- Request shape ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_blank_reasoning_effort_omits_the_parameter(transport, make_client):
    """gpt-5.6 luna rejects tools combined with any effort other than none."""
    await ask(make_client(), reasoning_effort="")

    assert "reasoning_effort" not in transport["requests"][0].content.decode()


@pytest.mark.asyncio
async def test_a_configured_reasoning_effort_is_sent(transport, make_client):
    await ask(make_client(), reasoning_effort="none")

    assert '"reasoning_effort":"none"' in transport["requests"][0].content.decode().replace(
        ", ", ","
    ).replace(": ", ":")


@pytest.mark.asyncio
async def test_tools_imply_a_tool_choice(transport, make_client):
    import json

    tools = [{"type": "function", "function": {"name": "list_policies"}}]
    await ask(make_client(), tools=tools)

    body = json.loads(transport["requests"][0].content)
    assert body["tools"] == tools
    assert body["tool_choice"] == "auto"


def test_a_tool_call_turn_serialises_content_as_a_string():
    """Some servers reject a null content field; others require the key."""
    payload = ChatMessage(
        role="assistant",
        content=None,
        tool_calls=[{"id": "1", "function": {"name": "f", "arguments": "{}"}}],
    ).to_dict()

    assert payload["content"] == ""
    assert payload["tool_calls"]


# --- Response shapes --------------------------------------------------------


def test_the_standard_shape_is_read():
    message = ModelServingClient._extract_message(completion("hi"))
    assert message["content"] == "hi"


def test_a_predictions_wrapper_is_unwrapped():
    """Some serving endpoints nest the OpenAI response under `predictions`."""
    message = ModelServingClient._extract_message({"predictions": [completion("hi")]})
    assert message["content"] == "hi"


def test_a_bare_string_prediction_is_accepted():
    message = ModelServingClient._extract_message({"predictions": ["hi"]})
    assert message == {"role": "assistant", "content": "hi"}


@pytest.mark.parametrize(
    "data", ["a string", {}, {"choices": []}, {"choices": [{}]}, {"predictions": []}]
)
def test_an_unrecognisable_response_raises_rather_than_returning_empty(data):
    """An empty answer would be rendered to the user as though it were real."""
    with pytest.raises(ModelServingError):
        ModelServingClient._extract_message(data)
