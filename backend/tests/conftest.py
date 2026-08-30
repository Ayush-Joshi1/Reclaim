"""Test configuration for the Reclaim backend."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/reclaim")


@pytest.fixture(autouse=True)
def disable_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test on the deterministic fake LLM client."""
    for variable in ("RECOVERY_LLM_API_KEY", "RECOVERY_LLM_MODEL", "RECOVERY_LLM_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)
