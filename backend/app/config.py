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
    reclaim_workflow_secret: str = ""

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load settings and reject an unset database URL."""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ConfigurationError(
                "DATABASE_URL is required. Set it to a PostgreSQL connection URL before starting Reclaim."
            )
        return cls(
            database_url=database_url,
            razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
            razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", ""),
            razorpay_base_url=os.getenv("RAZORPAY_BASE_URL", "https://api.razorpay.com/v1"),
            razorpay_actions_enabled=os.getenv("RAZORPAY_ACTIONS_ENABLED", "false").lower() == "true",
            razorpay_test_mode=os.getenv("RAZORPAY_TEST_MODE", "false").lower() == "true",
            reclaim_workflow_secret=os.getenv("RECLAIM_WORKFLOW_SECRET", ""),
        )


settings = Settings.from_environment()
