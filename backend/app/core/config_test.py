"""Tests for application settings parsing."""

from app.core.config import Settings


def test_cors_allowed_origins_accepts_comma_separated_string():
    settings = Settings(
        SECRET_KEY="test-secret",
        DATABASE_URL_APP="postgresql+asyncpg://app:app@localhost/app",
        DATABASE_URL_ADMIN="postgresql+asyncpg://admin:admin@localhost/app",
        CORS_ALLOWED_ORIGINS="https://app.example.com, https://admin.example.com",
    )

    assert settings.CORS_ALLOWED_ORIGINS == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_cors_allowed_origins_blank_defaults_to_wildcard():
    settings = Settings(
        SECRET_KEY="test-secret",
        DATABASE_URL_APP="postgresql+asyncpg://app:app@localhost/app",
        DATABASE_URL_ADMIN="postgresql+asyncpg://admin:admin@localhost/app",
        CORS_ALLOWED_ORIGINS="",
    )

    assert settings.CORS_ALLOWED_ORIGINS == ["*"]
