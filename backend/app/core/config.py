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

    DATABASE_URL: str = "sqlite:///atlas_hub.db"

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
