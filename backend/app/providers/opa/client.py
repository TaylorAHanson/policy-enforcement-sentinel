"""OPA provider.

Two things dominate scan performance here, and both are addressed:

* **One HTTP call per resource, not per resource per policy.**
  :meth:`OpaProvider.evaluate_namespace` queries the whole
  ``data.databricks.governance`` namespace once and gets back every policy's
  verdict for that resource. Evaluating 12 policies used to mean 12 round trips.

* **A shared, pooled client.** Creating an ``httpx.AsyncClient`` per call throws
  away the connection pool and pays TLS/TCP setup every time. The client is
  cached per event loop, because a client bound to a closed loop raises on use —
  which is exactly what happens in tests and in the worker's own loop.

The CLI fallback remains for environments with no server, and runs under
``asyncio.to_thread`` so a 25ms subprocess spawn doesn't block the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional

import httpx

from app.core.exceptions import PermanentError, RetryableError
from app.providers.base import BaseProvider
from app.providers.opa.binary import OPA_SETUP_HINT, resolve_opa_binary

logger = logging.getLogger(__name__)

#: The Rego namespace every governance policy lives under.
GOVERNANCE_NAMESPACE = "databricks.governance"

#: Packages in the namespace that are libraries, not policies. Their results
#: would otherwise show up as a policy called "common" with no violations.
NON_POLICY_PACKAGES = {"common"}

# Keyed by event loop: an AsyncClient bound to a closed loop raises on use, and
# the app legitimately runs more than one loop (the API's, and the worker's).
_clients: Dict[int, httpx.AsyncClient] = {}


def _get_client(timeout: float = 30.0) -> httpx.AsyncClient:
    loop = asyncio.get_event_loop()
    key = id(loop)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        _clients[key] = client
    return client


async def close_clients() -> None:
    """Close every pooled client. Called from the app lifespan on shutdown."""
    for client in list(_clients.values()):
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception as e:
            logger.debug("Error closing an OPA HTTP client: %s", e)
    _clients.clear()


class OpaProvider(BaseProvider):
    """Evaluates Rego policies against a local binary or an OPA server."""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.opa_url = self.config.get("opa_url")
        self.use_local_binary = self.config.get("use_local_binary", True)
        self.policies_dir = self.config.get("policies_dir", "policies")
        self.opa_binary = self.config.get("opa_binary")
        self.require_server = self.config.get("require_server", False)

    # --- Binary / health --------------------------------------------------

    def _resolve_opa_executable(self) -> Optional[str]:
        return resolve_opa_binary(self.opa_binary)

    def _require_local_opa(self) -> str:
        exe = self._resolve_opa_executable()
        if not exe:
            raise PermanentError(OPA_SETUP_HINT)
        return exe

    def _policies_path(self) -> str:
        if os.path.isabs(self.policies_dir):
            return self.policies_dir
        return os.path.join(os.getcwd(), self.policies_dir)

    async def health_check(self) -> bool:
        if self.opa_url:
            try:
                client = _get_client()
                response = await client.get(f"{self.opa_url}/health", timeout=5.0)
                return response.status_code == 200
            except Exception:
                return False
        return self._resolve_opa_executable() is not None

    # --- The hot path -----------------------------------------------------

    async def evaluate_namespace(
        self, input_data: Dict[str, Any], namespace: str = GOVERNANCE_NAMESPACE
    ) -> Dict[str, Any]:
        """Evaluate every policy in the namespace against one resource.

        Returns ``{package_name: result}`` with library packages removed.
        """
        if self.opa_url:
            raw = await self._evaluate_remote(f"data.{namespace}", input_data)
        elif self.require_server:
            raise PermanentError(
                "OPA_REQUIRE_SERVER is set but no OPA server URL is configured. "
                "Refusing to fall back to the (much slower) CLI."
            )
        else:
            raw = await self._evaluate_local_namespace(namespace, input_data)

        if not isinstance(raw, dict):
            logger.warning(
                "OPA returned %s for namespace %s; expected an object.",
                type(raw).__name__,
                namespace,
            )
            return {}

        return {
            package: result
            for package, result in raw.items()
            if package not in NON_POLICY_PACKAGES and isinstance(result, dict)
        }

    async def _evaluate_local_namespace(
        self, namespace: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await self._evaluate_local(None, f"data.{namespace}", input_data)

    # --- Validation -------------------------------------------------------

    async def check(self, policy_name: str, content: str) -> Dict[str, Any]:
        """Validate Rego syntax with ``opa check``.

        The whole policies directory is copied to a temp dir with the candidate
        content swapped in, so cross-file imports resolve the way they will
        after the save.
        """
        try:
            opa_exe = self._require_local_opa()
        except PermanentError:
            if self.opa_url:
                # A remote server can't check unsaved text without mutating its
                # state, and pushing a draft policy to a live server to test it
                # would be worse than not checking.
                logger.warning("No local OPA binary; skipping syntax validation.")
                return {"valid": True, "errors": [], "skipped": True}
            raise

        return await asyncio.to_thread(self._check_sync, opa_exe, policy_name, content)

    def _check_sync(self, opa_exe: str, policy_name: str, content: str) -> Dict[str, Any]:
        policies_dir_path = self._policies_path()

        with tempfile.TemporaryDirectory() as temp_dir:
            if os.path.exists(policies_dir_path):
                shutil.copytree(policies_dir_path, temp_dir, dirs_exist_ok=True)

            with open(os.path.join(temp_dir, policy_name), "w") as f:
                f.write(content)

            try:
                process = subprocess.run(
                    [opa_exe, "check", temp_dir, "-f", "json"],
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as e:
                raise PermanentError(OPA_SETUP_HINT) from e

            if process.returncode == 0:
                return {"valid": True, "errors": []}

            try:
                output = json.loads(process.stdout)
            except (ValueError, TypeError):
                return {
                    "valid": False,
                    "errors": [process.stderr or process.stdout or "Invalid Rego syntax"],
                }

            errors = []
            for err in output.get("errors", []):
                location = err.get("location", {})
                file_loc = location.get("file", "")
                if not file_loc or policy_name in file_loc:
                    errors.append(
                        f"{err.get('message', 'Unknown error')} (Line {location.get('row', '?')})"
                    )

            return {"valid": False, "errors": errors or ["Validation failed in a related file."]}

    # --- Evaluation -------------------------------------------------------

    async def evaluate(
        self, policy_path: str, query: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        if self.opa_url:
            return await self._evaluate_remote(query, input_data)
        return await self._evaluate_local(policy_path, query, input_data)

    async def evaluate_content(
        self, policy_name: str, content: str, query: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate unsaved editor content. Always local — a server would have to
        be mutated to test a draft."""
        opa_exe = self._require_local_opa()
        return await asyncio.to_thread(
            self._evaluate_local_content_sync, opa_exe, policy_name, content, query, input_data
        )

    def _evaluate_local_content_sync(
        self,
        opa_exe: str,
        policy_name: str,
        content: str,
        query: str,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        policies_dir_path = self._policies_path()

        with tempfile.TemporaryDirectory() as temp_dir:
            if os.path.exists(policies_dir_path):
                shutil.copytree(policies_dir_path, temp_dir, dirs_exist_ok=True)

            with open(os.path.join(temp_dir, policy_name), "w") as f:
                f.write(content)

            input_path = os.path.join(temp_dir, "__input.json")
            with open(input_path, "w") as f:
                json.dump(input_data, f)

            return self._run_eval(opa_exe, temp_dir, input_path, query)

    async def _evaluate_remote(self, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        path = query.replace("data.", "", 1).replace(".", "/")
        endpoint = f"{self.opa_url}/v1/data/{path}"
        try:
            client = _get_client()
            response = await client.post(endpoint, json={"input": input_data})
            response.raise_for_status()
            return response.json().get("result", {})
        except httpx.HTTPStatusError as e:
            raise PermanentError(f"OPA server returned an error: {e.response.text}")
        except httpx.RequestError as e:
            raise RetryableError(f"Failed to communicate with the OPA server: {e}")

    async def _evaluate_local(
        self, policy_file: Optional[str], query: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        opa_exe = self._require_local_opa()
        policies_dir_path = self._policies_path()
        if not os.path.exists(policies_dir_path):
            raise PermanentError(f"Policies directory not found: {policies_dir_path}")

        # Off the event loop: `opa eval` is a subprocess spawn, and blocking the
        # loop here serialises an otherwise concurrent scan.
        return await asyncio.to_thread(
            self._evaluate_local_sync, opa_exe, policies_dir_path, query, input_data
        )

    def _evaluate_local_sync(
        self, opa_exe: str, policies_dir_path: str, query: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        temp_in_path = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as temp_in:
                json.dump(input_data, temp_in)
                temp_in_path = temp_in.name
            return self._run_eval(opa_exe, policies_dir_path, temp_in_path, query)
        finally:
            if temp_in_path and os.path.exists(temp_in_path):
                os.remove(temp_in_path)

    @staticmethod
    def _run_eval(opa_exe: str, data_dir: str, input_path: str, query: str) -> Dict[str, Any]:
        cmd = [opa_exe, "eval", "-d", data_dir, "-i", input_path, "-f", "values", query]
        try:
            process = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise PermanentError(OPA_SETUP_HINT) from e

        if process.returncode != 0:
            raise PermanentError(
                f"OPA evaluation failed: {process.stderr or process.stdout}"
            )

        output = json.loads(process.stdout or "[]")
        if not output:
            return {}
        return output[0] if isinstance(output, list) else output
