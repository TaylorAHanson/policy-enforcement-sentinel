"""Locating the OPA executable.

Extracted from the provider so the embedded server and the CLI fallback resolve
the binary the same way. The search order matters in deployment: Databricks Apps
run from a read-only filesystem, so a bundled binary has to be copied to /tmp
before it can be marked executable.
"""
import logging
import os
import platform
import shutil
import stat
from typing import Optional

logger = logging.getLogger(__name__)

OPA_SETUP_HINT = (
    "Open Policy Agent (opa) is not available. Install it (e.g. `brew install opa`) so "
    "`opa` is on PATH, or set OPA_BINARY in .env to the executable, or set OPA_URL to a "
    "running OPA server that already has your Rego bundles loaded. "
    "See https://www.openpolicyagent.org/docs/latest/"
)

OPA_DOWNLOAD_VERSION = "v0.61.0"

_cached_path: Optional[str] = None


def _make_executable(path: str) -> bool:
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return os.access(path, os.X_OK)
    except Exception as e:
        logger.warning("Could not mark %s executable: %s", path, e)
        return False


def _bundled_candidate() -> Optional[str]:
    # backend/ is four levels up from app/providers/opa/binary.py
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    bundled = os.path.join(base_dir, "bin", "opa_linux_amd64")
    if not os.path.isfile(bundled):
        return None

    if os.access(bundled, os.X_OK):
        return bundled

    # Read-only filesystem (Databricks Apps): stage a copy we can chmod.
    dest = "/tmp/opa_linux_amd64"
    try:
        if not os.path.exists(dest) or os.path.getsize(bundled) != os.path.getsize(dest):
            shutil.copy2(bundled, dest)
        if _make_executable(dest):
            return dest
    except Exception as e:
        logger.warning("Could not stage the bundled OPA binary in /tmp: %s", e)
    return None


def _downloaded_candidate() -> Optional[str]:
    os_name = "darwin" if platform.system().lower() == "darwin" else "linux"
    arch = "arm64_static" if platform.machine().lower() in ("aarch64", "arm64") else "amd64_static"
    dest = f"/tmp/opa_{os_name}_{arch}"

    if os.path.isfile(dest) and os.access(dest, os.X_OK):
        return dest

    url = f"https://openpolicyagent.org/downloads/{OPA_DOWNLOAD_VERSION}/opa_{os_name}_{arch}"
    logger.info("OPA binary not found locally; downloading from %s", url)
    try:
        import urllib.request

        urllib.request.urlretrieve(url, dest)
        if _make_executable(dest):
            logger.info("Downloaded OPA to %s", dest)
            return dest
    except Exception as e:
        logger.warning("Could not download OPA: %s", e)
    return None


def resolve_opa_binary(configured: Optional[str] = None, *, use_cache: bool = True) -> Optional[str]:
    """Find an OPA executable, or ``None``.

    Order: explicitly configured path, then a bundled binary, then PATH, then a
    download. PATH comes before the download so a developer's own install wins
    over pulling one down.
    """
    global _cached_path

    if configured:
        expanded = os.path.expanduser(configured.strip())
        if os.path.isfile(expanded):
            return expanded
        logger.warning("Configured OPA path %s is not a file.", expanded)
        return None

    if use_cache and _cached_path and os.path.isfile(_cached_path):
        return _cached_path

    for candidate in (_bundled_candidate(), shutil.which("opa"), _downloaded_candidate()):
        if candidate:
            _cached_path = candidate
            return candidate

    logger.error("Could not resolve an OPA executable by any method.")
    return None
