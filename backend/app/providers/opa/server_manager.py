"""Embedded OPA server.

The CLI path spawns a subprocess per evaluation, which costs 20-25ms of process
startup before OPA does any work. A scan evaluating a few thousand resources
spends most of its wall clock in ``fork``/``exec``. Running one long-lived
``opa run --server`` and talking to it over loopback HTTP turns that into about
a millisecond per call.

The server is started in the FastAPI lifespan and torn down with the app. If it
fails to come up, the provider falls back to the CLI — correct but slow — unless
``OPA_REQUIRE_SERVER`` is set, which is worth doing in deployed environments
where a silent fallback would just look like an inexplicably slow scan.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from typing import Optional

import httpx

from app.providers.opa.binary import resolve_opa_binary

logger = logging.getLogger(__name__)

_process: Optional[subprocess.Popen] = None
_url: Optional[str] = None


def get_opa_url() -> Optional[str]:
    """The embedded server's base URL, or ``None`` if it isn't running."""
    return _url


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def _free_port() -> int:
    """Reserve an ephemeral port and hand it to OPA.

    Binding to :0 and asking OPA to report its own port means parsing its log
    output; taking the port ourselves and passing it explicitly is a smaller
    moving part, and the race window is negligible on loopback.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(policies_dir: str, *, opa_binary: Optional[str] = None, timeout: float = 15.0) -> Optional[str]:
    """Start the server and block until it reports healthy. Returns its URL."""
    global _process, _url

    if is_running():
        return _url

    binary = resolve_opa_binary(opa_binary)
    if not binary:
        logger.warning("No OPA binary available; the embedded server cannot start.")
        return None

    if not os.path.isdir(policies_dir):
        logger.error("Policies directory %s does not exist; not starting OPA.", policies_dir)
        return None

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    cmd = [
        binary,
        "run",
        "--server",
        "--addr",
        f"127.0.0.1:{port}",
        # Reload policies when the editor writes a file, so a saved policy takes
        # effect without restarting the app.
        "--watch",
        "--log-level",
        "error",
        policies_dir,
    ]

    logger.info("Starting embedded OPA server on %s (policies: %s)", url, policies_dir)
    try:
        _process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as e:
        logger.error("Failed to spawn the OPA server: %s", e)
        _process = None
        return None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _process.poll() is not None:
            stderr = (_process.stderr.read() or b"").decode(errors="replace")
            logger.error("OPA server exited during startup: %s", stderr.strip()[:2000])
            _process = None
            return None

        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
            if response.status_code == 200:
                _url = url
                logger.info("Embedded OPA server is healthy at %s", url)
                return url
        except Exception:
            pass

        time.sleep(0.1)

    logger.error("Embedded OPA server did not become healthy within %.0fs.", timeout)
    stop()
    return None


def stop() -> None:
    """Terminate the server, escalating to a kill if it doesn't exit."""
    global _process, _url

    if _process is None:
        _url = None
        return

    logger.info("Stopping the embedded OPA server.")
    try:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("OPA server did not exit after SIGTERM; killing it.")
            _process.kill()
            _process.wait(timeout=5)
    except Exception as e:
        logger.warning("Error while stopping the OPA server: %s", e)
    finally:
        _process = None
        _url = None
