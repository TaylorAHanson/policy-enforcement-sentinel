"""Chat completions against Databricks Model Serving, preferring the AI Gateway.

Two routes exist and they are not interchangeable:

* ``/ai-gateway/mlflow/v1/chat/completions`` — the gateway. Rate limits, cost
  controls, guardrails, payload logging, and model fallbacks are configured on
  the gateway rather than written into this codebase. The model is named in the
  request body.
* ``/serving-endpoints/{name}/invocations`` — a specific endpoint, used when no
  gateway model is configured. The model is named in the URL.

The gateway is tried first because everything that makes an LLM call safe to
expose to users lives there. The direct route exists so a deployment without a
gateway still works, not as an equal alternative.

Authentication comes from the Databricks SDK's credential chain, so this works
under a service principal in a Databricks App, under a PAT locally, and under
workload identity in a job, without any of those being special-cased here.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

#: The gateway's OpenAI-compatible chat route.
AI_GATEWAY_PATH = "/ai-gateway/mlflow/v1/chat/completions"

#: Status codes worth retrying. Everything else is a request problem that
#: retrying will reproduce exactly.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.75

_clients: Dict[int, httpx.AsyncClient] = {}


class ModelServingError(RuntimeError):
    """A chat completion could not be obtained."""

    def __init__(self, message: str, *, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass
class ChatMessage:
    """One turn. ``tool_calls`` and ``tool_call_id`` carry the function-calling
    protocol, which the Q&A loop depends on."""

    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict:
        payload: Dict[str, Any] = {"role": self.role}
        # An assistant turn that is purely tool calls has no content, and some
        # servers reject `"content": null` while others require the key. Sending
        # an empty string satisfies both.
        payload["content"] = self.content if self.content is not None else ""
        if self.name:
            payload["name"] = self.name
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        return payload


def _get_client(timeout: float) -> httpx.AsyncClient:
    # Keyed by event loop for the same reason as the OPA client: an
    # AsyncClient bound to a closed loop raises on use, and the API and the
    # worker each run their own loop.
    loop = asyncio.get_event_loop()
    key = id(loop)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )
        _clients[key] = client
    return client


async def close_clients() -> None:
    """Close pooled clients. Called from the app lifespan on shutdown."""
    for client in list(_clients.values()):
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception as e:  # pragma: no cover - shutdown best effort
            logger.debug("Error closing a model serving client: %s", e)
    _clients.clear()


class ModelServingClient:
    """Talks to the gateway, or to a named serving endpoint."""

    def __init__(
        self,
        *,
        host: Optional[str] = None,
        token: Optional[str] = None,
        gateway_model: Optional[str] = None,
        endpoint_name: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        from app.core.config import settings

        self.gateway_model = (
            gateway_model
            if gateway_model is not None
            else settings.AI_GATEWAY_ENDPOINT
        ) or ""
        self.endpoint_name = (
            endpoint_name
            if endpoint_name is not None
            else settings.MODEL_SERVING_AGENT_LLM_ENDPOINT
        ) or ""
        self.timeout = timeout or settings.MODEL_SERVING_TIMEOUT_SECONDS

        # Fall back to the workspace credentials the rest of the app already
        # uses. Without this the bare WorkspaceClient() below ignores
        # backend/.env entirely — pydantic reads that file into `settings`, not
        # into os.environ — and silently authenticates as whatever
        # ~/.databrickscfg happens to name as DEFAULT. An expired CLI session
        # then surfaces here as a model serving error, which points at the
        # wrong thing.
        self._host = host or settings.DATABRICKS_HOST or settings.DATABRICKS_WORKSPACE_URL
        self._token = token or settings.MODEL_SERVING_API_KEY or settings.DATABRICKS_TOKEN
        self._client_id = settings.DATABRICKS_CLIENT_ID
        self._client_secret = settings.DATABRICKS_CLIENT_SECRET

    # --- Credentials ------------------------------------------------------

    def _resolve_credentials(self) -> tuple[str, str]:
        """(host, token), from the app's own config or the SDK's chain.

        Ordered the same way as :class:`DatabricksProvider`, so the assistant
        talks to the same workspace as the scanner. A deployment that configures
        one and not the other is a support case nobody enjoys.
        """
        from app.core.config import qualify_host

        if self._host and self._token:
            return qualify_host(self._host) or "", self._token

        try:
            from databricks.sdk import WorkspaceClient

            if self._host and self._client_id and self._client_secret:
                client = WorkspaceClient(
                    host=self._host,
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                )
            else:
                # Nothing configured: the ambient chain. This is the right
                # answer in a deployed App, where the platform supplies a
                # service principal, and the last resort locally.
                client = WorkspaceClient()

            host = qualify_host(self._host or client.config.host) or ""
            token = self._token
            if not token:
                # `authenticate()` runs whichever credential strategy applies —
                # PAT, OAuth service principal, workload identity — and returns
                # ready-made headers.
                headers = client.config.authenticate()
                authorization = headers.get("Authorization", "")
                token = authorization.removeprefix("Bearer ").strip()
            if not host or not token:
                raise ModelServingError(
                    "Could not resolve Databricks credentials for model serving. "
                    "Set DATABRICKS_HOST and DATABRICKS_TOKEN in backend/.env, or "
                    "run `databricks auth login`."
                )
            return host, token
        except ModelServingError:
            raise
        except Exception as e:
            raise ModelServingError(
                f"Could not authenticate to Databricks for model serving: {e}"
            ) from e

    @property
    def configured(self) -> bool:
        return bool(self.gateway_model or self.endpoint_name)

    # --- Requests ---------------------------------------------------------

    def _routes(self, host: str) -> List[tuple[str, str, Optional[str]]]:
        """(label, url, model) to try, in order."""
        routes: List[tuple[str, str, Optional[str]]] = []
        if self.gateway_model:
            routes.append(("ai-gateway", f"{host}{AI_GATEWAY_PATH}", self.gateway_model))
        if self.endpoint_name:
            routes.append(
                (
                    "serving-endpoint",
                    f"{host}/serving-endpoints/{self.endpoint_name}/invocations",
                    None,
                )
            )
        return routes

    async def chat(
        self,
        messages: List[ChatMessage],
        *,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> dict:
        """One chat completion. Returns the assistant message as a dict."""
        from app.core.config import settings

        if not self.configured:
            raise ModelServingError(
                "No model is configured. Set AI_GATEWAY_ENDPOINT (preferred) or "
                "MODEL_SERVING_AGENT_LLM_ENDPOINT in Settings."
            )

        host, token = self._resolve_credentials()

        body: Dict[str, Any] = {"messages": [m.to_dict() for m in messages]}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        effort = (
            reasoning_effort
            if reasoning_effort is not None
            else settings.AGENT_LLM_REASONING_EFFORT
        )
        # A blank effort omits the parameter. Reasoning models reject function
        # tools combined with any effort other than "none", and non-reasoning
        # models reject the parameter outright — so the only safe default is to
        # send exactly what was configured, and nothing when that is empty.
        if effort:
            body["reasoning_effort"] = effort

        client = _get_client(self.timeout)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None

        for label, url, model in self._routes(host):
            payload = dict(body)
            if model:
                payload["model"] = model

            try:
                data = await self._post_with_retries(client, url, headers, payload, label)
                return self._extract_message(data)
            except ModelServingError as e:
                last_error = e
                # Falling through to the direct endpoint is only worth doing for
                # a routing-shaped failure. A 400 means the request itself is
                # wrong and the second route will reject it identically.
                if e.status and e.status not in (404, 405, 501):
                    raise
                logger.warning("Model route %s unavailable (%s); trying the next.", label, e)

        raise ModelServingError(
            f"No model serving route succeeded: {last_error}"
        ) from last_error

    async def _post_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        label: str,
    ) -> dict:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.RequestError as e:
                if attempt == _MAX_ATTEMPTS:
                    raise ModelServingError(f"{label} unreachable: {e}") from e
                await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue

            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as e:
                    raise ModelServingError(
                        f"{label} returned a non-JSON response."
                    ) from e

            if response.status_code in RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                # Scale-to-zero endpoints return 503 while a replica starts, so
                # the first retry frequently succeeds on an otherwise healthy
                # deployment.
                delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "%s returned %s; retrying in %.1fs (attempt %d/%d).",
                    label,
                    response.status_code,
                    delay,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                await asyncio.sleep(delay)
                continue

            raise ModelServingError(
                f"{label} returned {response.status_code}: {response.text[:500]}",
                status=response.status_code,
            )

        raise ModelServingError(f"{label} exhausted retries.")

    @staticmethod
    def _extract_message(data: Any) -> dict:
        """Pull the assistant message out of an OpenAI-shaped response."""
        if not isinstance(data, dict):
            raise ModelServingError("Model response was not an object.")

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message")
            if isinstance(message, dict):
                return message

        # Some serving endpoints wrap the response in `predictions`.
        predictions = data.get("predictions")
        if isinstance(predictions, list) and predictions:
            first = predictions[0]
            if isinstance(first, dict) and "choices" in first:
                return ModelServingClient._extract_message(first)
            if isinstance(first, str):
                return {"role": "assistant", "content": first}

        raise ModelServingError(
            f"Could not find an assistant message in the response: "
            f"{json.dumps(data)[:300]}"
        )
