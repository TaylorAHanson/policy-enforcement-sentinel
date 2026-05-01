from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    PROJECT_NAME: str = "policy-enforcement-sentinel"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "*"

    DATABRICKS_HOST: Optional[str] = None
    DATABRICKS_TOKEN: Optional[str] = None
    DATABRICKS_CLIENT_ID: Optional[str] = None
    DATABRICKS_CLIENT_SECRET: Optional[str] = None
    DATABRICKS_WORKSPACE_URL: Optional[str] = None

    OPA_URL: Optional[str] = None
    USE_LOCAL_BINARY: bool = True
    POLICIES_DIR: str = "policies"
    OPA_BINARY: Optional[str] = None

    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: Optional[str] = None
    GITHUB_TARGET_BRANCH: str = "main"
    GITHUB_POLICIES_DIR: str = "backend/policies"

    DATABASE_URL: Optional[str] = None
    DATABASE_HOST: Optional[str] = None
    DATABASE_USER: Optional[str] = None
    DATABASE_NAME: Optional[str] = None
    DATABASE_PORT: str = "5432"
    DATABASE_PASSWORD: Optional[str] = None
    DATABASE_INSTANCE_NAME: Optional[str] = None

    SENTINEL_WORKSPACES: Optional[str] = None

    SENTINEL_CRON_SCHEDULE: Optional[str] = None
    SENTINEL_CRON_WORKSPACE: str = "ws-enterprise-prod"
    SENTINEL_CRON_ENV: str = "prod"
    SENTINEL_CRON_MODE: str = "audit"

    BRANDING_NAME: str = "Policy Enforcement Sentinel"
    BRANDING_LOGO_URL: str = "https://www.openpolicyagent.org/img/nav/logo.png"
    BRANDING_PRIMARY_COLOR: str = "#3253DC"
    BRANDING_SECONDARY_COLOR: str = "#000000"

    def opa_provider_config(self) -> dict:
        return {
            "opa_url": self.OPA_URL,
            "use_local_binary": self.USE_LOCAL_BINARY,
            "policies_dir": self.POLICIES_DIR,
            "opa_binary": self.OPA_BINARY,
        }

    def get_workspaces(self) -> List[Dict[str, str]]:
        import json
        if self.SENTINEL_WORKSPACES:
            try:
                return json.loads(self.SENTINEL_WORKSPACES)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to parse SENTINEL_WORKSPACES JSON: {e}")
        
        # Fallback to single workspace using legacy variables
        return [{
            "name": self.SENTINEL_CRON_WORKSPACE,
            "environment": self.SENTINEL_CRON_ENV,
            "host": self.DATABRICKS_HOST or self.DATABRICKS_WORKSPACE_URL or "",
            "token": self.DATABRICKS_TOKEN,
            "client_id": self.DATABRICKS_CLIENT_ID,
            "client_secret": self.DATABRICKS_CLIENT_SECRET
        }]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
