"""Configuration tests."""

import pytest

from app.config import ConfigurationError, Settings


def test_settings_load_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/reclaim")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "key-id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key-secret")
    monkeypatch.setenv("RAZORPAY_BASE_URL", "https://test.example")

    settings = Settings.from_environment()

    assert settings.database_url == "postgresql://user:pass@localhost:5432/reclaim"
    assert settings.razorpay_key_id == "key-id"
    assert settings.razorpay_key_secret == "key-secret"
    assert settings.razorpay_base_url == "https://test.example"


def test_settings_default_razorpay_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/reclaim")
    monkeypatch.delenv("RAZORPAY_BASE_URL", raising=False)

    settings = Settings.from_environment()

    assert settings.razorpay_base_url == "https://api.razorpay.com/v1"


def test_settings_reject_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL is required"):
        Settings.from_environment()
