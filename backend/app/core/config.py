"""Environment configuration layer.

Layer two of three: in-code defaults (``default_config``) -> **env / .env /
databricks.yml** -> DB overrides (``settings_store``).

Read ``settings.X`` at call time. DB overrides are applied at startup, after
modules have been imported, so a module-level ``FOO = settings.FOO`` freezes the
pre-override value and silently ignores whatever the admin configured.
"""
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.default_config import DEFAULTS


def qualify_host(value: Optional[str]) -> Optional[str]:
    """Give a workspace host a scheme and no trailing slash.

    A deployed Databricks App receives ``DATABRICKS_HOST`` as a bare hostname.
    The SDK tolerates that and prepends https:// itself, so anything going
    through ``WorkspaceClient`` works and the gap stays hidden — until something
    builds a URL by hand, at which point httpx rejects it for having no
    protocol.
    """
    if not value:
        return value

    host = value.strip().rstrip("/")
    if not host:
        return None
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


class Settings(BaseSettings):
    PROJECT_NAME: str = "policy-enforcement-sentinel"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "*"

    DATABRICKS_HOST: Optional[str] = None
    DATABRICKS_TOKEN: Optional[str] = None
    DATABRICKS_CLIENT_ID: Optional[str] = None
    DATABRICKS_CLIENT_SECRET: Optional[str] = None
    DATABRICKS_WORKSPACE_URL: Optional[str] = None

    # --- OPA ---------------------------------------------------------------
    OPA_URL: Optional[str] = None
    USE_LOCAL_BINARY: bool = True
    POLICIES_DIR: str = "backend/policies"
    OPA_BINARY: Optional[str] = None
    # Run a long-lived `opa run --server` in-process instead of spawning the CLI
    # per evaluation. Turns a ~25ms subprocess spawn into a ~1ms HTTP call, which
    # is the difference between minutes and seconds on a large estate.
    OPA_EMBEDDED_ENABLED: bool = True
    # Refuse to fall back to the CLI. Useful in deployed environments where a
    # silent fallback would mask a broken embedded server.
    OPA_REQUIRE_SERVER: bool = False

    # Blank resolves to docs/release-notes/ next to the repository root. Set it
    # when the backend is deployed without the docs tree beside it.
    RELEASE_NOTES_DIR: str = ""

    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: Optional[str] = None
    GITHUB_TARGET_BRANCH: str = "main"
    GITHUB_POLICIES_DIR: str = "backend/policies"
    # How often the working copy is rebuilt from the target branch, so a merged
    # policy PR takes effect without a redeploy. Zero disables the loop; the
    # startup sync and the manual refresh still run.
    POLICY_SYNC_INTERVAL_SECONDS: int = 300

    # --- Database ----------------------------------------------------------
    DATABASE_URL: Optional[str] = None
    DATABASE_HOST: Optional[str] = None
    DATABASE_USER: Optional[str] = None
    DATABASE_NAME: Optional[str] = None
    DATABASE_PORT: str = "5432"
    DATABASE_PASSWORD: Optional[str] = None
    DATABASE_INSTANCE_NAME: Optional[str] = None
    DB_SCHEMA: str = "policy_enforcement_sentinel"
    # Lakebase drops idle connections. Recycling below that threshold means a
    # long scan doesn't come back to a dead socket.
    DB_POOL_RECYCLE_SECONDS: int = 1800

    SENTINEL_WORKSPACES: Optional[str] = None

    SENTINEL_CRON_SCHEDULE: Optional[str] = None
    SENTINEL_CRON_WORKSPACE: str = "ws-enterprise-prod"
    SENTINEL_CRON_ENV: str = "prod"
    SENTINEL_CRON_MODE: str = DEFAULTS["SENTINEL_CRON_MODE"]

    # --- Safety gates ------------------------------------------------------
    # Each of these defaults to the least capable value. A fresh install records
    # findings and does nothing else until an admin makes an explicit decision.
    # See app/core/enforcement.py for how they combine.
    ENFORCEMENT_ENABLED: bool = DEFAULTS["ENFORCEMENT_ENABLED"]
    DESTRUCTIVE_ACTION_WORKSPACES: str = DEFAULTS["DESTRUCTIVE_ACTION_WORKSPACES"]
    DESTRUCTIVE_ACTION_MAX_RESOURCES: int = DEFAULTS["DESTRUCTIVE_ACTION_MAX_RESOURCES"]
    ENFORCEMENT_APPROVAL_TTL_MINUTES: int = DEFAULTS["ENFORCEMENT_APPROVAL_TTL_MINUTES"]

    # --- Scan tuning -------------------------------------------------------
    SENTINEL_SCAN_CONCURRENCY: int = DEFAULTS["SENTINEL_SCAN_CONCURRENCY"]
    SENTINEL_WORKSPACE_CONCURRENCY: int = DEFAULTS["SENTINEL_WORKSPACE_CONCURRENCY"]
    SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS: int = DEFAULTS[
        "SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS"
    ]
    SENTINEL_SDK_HTTP_TIMEOUT_SECONDS: int = DEFAULTS["SENTINEL_SDK_HTTP_TIMEOUT_SECONDS"]
    # Walking the whole workspace tree is expensive; off unless asked for.
    SENTINEL_SCAN_NOTEBOOKS: bool = DEFAULTS["SENTINEL_SCAN_NOTEBOOKS"]

    # --- Branding ----------------------------------------------------------
    BRANDING_NAME: str = DEFAULTS["BRANDING_NAME"]
    BRANDING_LOGO_URL: str = DEFAULTS["BRANDING_LOGO_URL"]
    BRANDING_PRIMARY_COLOR: str = DEFAULTS["BRANDING_PRIMARY_COLOR"]
    BRANDING_SECONDARY_COLOR: str = DEFAULTS["BRANDING_SECONDARY_COLOR"]

    # --- AI Gateway / model serving ---------------------------------------
    # Prefer the gateway: model routing, rate and cost limits, and input
    # guardrails then live in gateway config rather than in this codebase.
    AI_GATEWAY_ENDPOINT: str = DEFAULTS["AI_GATEWAY_ENDPOINT"]
    MODEL_SERVING_AGENT_LLM_ENDPOINT: str = DEFAULTS["MODEL_SERVING_AGENT_LLM_ENDPOINT"]
    MODEL_SERVING_API_KEY: str = ""
    MODEL_SERVING_TIMEOUT_SECONDS: float = DEFAULTS["MODEL_SERVING_TIMEOUT_SECONDS"]
    # Reasoning models reject function tools combined with a non-"none" effort.
    # Blank omits the parameter entirely so non-reasoning models aren't sent
    # something they'd reject.
    AGENT_LLM_REASONING_EFFORT: str = DEFAULTS["AGENT_LLM_REASONING_EFFORT"]
    AGENT_ENABLED: bool = DEFAULTS["AGENT_ENABLED"]
    AGENT_MAX_ITERATIONS: int = DEFAULTS["AGENT_MAX_ITERATIONS"]
    AGENT_TIMEOUT_SECONDS: int = DEFAULTS["AGENT_TIMEOUT_SECONDS"]
    AGENT_MAX_TOOL_OUTPUT_CHARS: int = DEFAULTS["AGENT_MAX_TOOL_OUTPUT_CHARS"]

    MLFLOW_TRACING_ENABLED: bool = False
    MLFLOW_TRACKING_URI: str = "databricks"
    MLFLOW_EXPERIMENT: str = ""

    # --- Notifications -----------------------------------------------------
    SMTP_SERVER: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "admin@your-company.com"
    SMTP_ADMIN_EMAIL: str = "admin@your-company.com"

    @property
    def get_policies_dir(self) -> str:
        import os

        # This file is backend/app/core/config.py, so backend/ is three up.
        base_dir = Path(__file__).parent.parent.parent
        policies_path = base_dir / "policies"
        if policies_path.exists():
            return str(policies_path)
        return os.path.abspath(self.POLICIES_DIR)

    def opa_provider_config(self) -> dict:
        """Resolve how the OPA provider should talk to OPA.

        Order: an explicit ``OPA_URL`` wins, then the embedded server if it came
        up, then the CLI. ``use_local_binary`` is derived rather than trusted
        from config, so a stale ``USE_LOCAL_BINARY=true`` can't send every
        evaluation back through subprocess spawning after the server started.
        """
        explicit_url = (self.OPA_URL or "").strip()

        embedded_url = None
        if not explicit_url and self.OPA_EMBEDDED_ENABLED:
            try:
                from app.providers.opa.server_manager import get_opa_url

                embedded_url = get_opa_url()
            except Exception:  # pragma: no cover - defensive
                embedded_url = None

        url = explicit_url or embedded_url or None
        return {
            "opa_url": url,
            "use_local_binary": not bool(url),
            "policies_dir": self.get_policies_dir,
            "opa_binary": self.OPA_BINARY,
            "require_server": bool(self.OPA_REQUIRE_SERVER),
        }

    def get_workspaces(self) -> List[Dict[str, str]]:
        import json
        import logging

        if self.SENTINEL_WORKSPACES:
            try:
                return json.loads(self.SENTINEL_WORKSPACES)
            except Exception as e:
                logging.getLogger(__name__).error(
                    f"Failed to parse SENTINEL_WORKSPACES JSON: {e}"
                )

        # Fallback to a single workspace built from the legacy variables.
        return [
            {
                "name": self.SENTINEL_CRON_WORKSPACE,
                "environment": self.SENTINEL_CRON_ENV,
                "host": self.DATABRICKS_HOST or self.DATABRICKS_WORKSPACE_URL or "",
                "token": self.DATABRICKS_TOKEN,
                "client_id": self.DATABRICKS_CLIENT_ID,
                "client_secret": self.DATABRICKS_CLIENT_SECRET,
            }
        ]

    def destructive_workspaces(self) -> List[str]:
        raw = self.DESTRUCTIVE_ACTION_WORKSPACES or ""
        return [part.strip() for part in raw.split(",") if part.strip()]

    @field_validator("DATABRICKS_HOST", "DATABRICKS_WORKSPACE_URL", mode="after")
    @classmethod
    def _qualify_host(cls, value: Optional[str]) -> Optional[str]:
        """Every reader of the host gets a usable base URL, whatever supplied it
        — the platform, a .env, or the Settings page."""
        return qualify_host(value)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # So an override written by settings_store, which assigns to the live
        # object, runs the validators above rather than bypassing them.
        validate_assignment=True,
    )


settings = Settings()
