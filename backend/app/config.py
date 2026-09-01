"""Application configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    app_name: str = "reclaim-api"
    database_url: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_base_url: str = "https://api.razorpay.com/v1"
    razorpay_actions_enabled: bool = False
    razorpay_test_mode: bool = False
    razorpay_webhook_secret: str = ""
    reclaim_workflow_secret: str = ""
    recovery_llm_api_key: str = ""
    recovery_llm_model: str = ""
    recovery_llm_base_url: str = "https://api.openai.com/v1"
    cors_allowed_origins: list[str] = None  # type: ignore[assignment]
    reconciliation_max_attempts: int = 3
    follow_up_lease_seconds: int = 300

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load settings and reject an unset database URL."""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ConfigurationError(
                "DATABASE_URL is required. Set it to a PostgreSQL connection URL before starting Reclaim."
            )

        cors_allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,https://*.vercel.app")
        parsed_origins = [origin.strip() for origin in cors_allowed_origins.split(",") if origin.strip()]

        return cls(
            database_url=database_url,
            razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
            razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", ""),
            razorpay_base_url=os.getenv("RAZORPAY_BASE_URL", "https://api.razorpay.com/v1"),
            razorpay_actions_enabled=os.getenv("RAZORPAY_ACTIONS_ENABLED", "false").lower() == "true",
            razorpay_test_mode=os.getenv("RAZORPAY_TEST_MODE", "false").lower() == "true",
            razorpay_webhook_secret=os.getenv("RAZORPAY_WEBHOOK_SECRET", ""),
            reclaim_workflow_secret=os.getenv("RECLAIM_WORKFLOW_SECRET", ""),
            recovery_llm_api_key=os.getenv("RECOVERY_LLM_API_KEY", ""),
            recovery_llm_model=os.getenv("RECOVERY_LLM_MODEL", ""),
            recovery_llm_base_url=os.getenv("RECOVERY_LLM_BASE_URL", "https://api.openai.com/v1"),
            cors_allowed_origins=parsed_origins,
            reconciliation_max_attempts=int(os.getenv("RECONCILIATION_MAX_ATTEMPTS", "3")),
            follow_up_lease_seconds=int(os.getenv("FOLLOW_UP_LEASE_SECONDS", "300")),
        )


settings = Settings.from_environment()
