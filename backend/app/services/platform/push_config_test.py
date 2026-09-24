"""Tests for the resolved push-config cache.

Same precedence rules as the captcha and storage caches, plus the one thing
specific to this credential: the service-account JSON is big enough that the
column it is stored in had to be sized for it, so a round trip is asserted on a
realistic document rather than on a short string.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.services.platform import app_settings as app_settings_service
from app.services.platform import push_config


def _service_account(project: str = "demo-project") -> str:
    """A service account the shape Google issues, padded to a realistic size.

    The private key is what makes the document over 2 kB, and the size is the
    point: Fernet takes it past the 2000 characters every other credential
    column is sized for.
    """
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project,
            "private_key_id": "0" * 40,
            "private_key": "-----BEGIN PRIVATE KEY-----\n"
            + "\n".join(["A" * 64] * 32)
            + "\n-----END PRIVATE KEY-----\n",
            "client_email": f"push@{project}.iam.gserviceaccount.com",
            "client_id": "1" * 21,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    push_config.reset_for_tests()
    yield
    push_config.reset_for_tests()


@pytest.mark.unit
def test_current_config_falls_back_to_env_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before the first load the resolver reads env, so a deployment that has
    always configured FCM through the environment keeps working unchanged."""
    monkeypatch.setattr(app_config, "FCM_ENABLED", True, raising=False)
    monkeypatch.setattr(app_config, "FCM_PROJECT_ID", "env-project", raising=False)
    monkeypatch.setattr(
        app_config, "FCM_SERVICE_ACCOUNT_JSON", _service_account("env"), raising=False
    )

    cfg = push_config.current_push_config()
    assert cfg.enabled is True
    assert cfg.project_id == "env-project"
    assert json.loads(cfg.service_account_json or "{}")["project_id"] == "env"


@pytest.mark.integration
async def test_refresh_loads_db_over_env(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a save the snapshot is the stored row, env ignored."""
    monkeypatch.setattr(app_config, "FCM_ENABLED", False, raising=False)
    monkeypatch.setattr(app_config, "FCM_PROJECT_ID", "env-project", raising=False)

    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=True,
        project_id="db-project",
        application_id="1:2:android:3",
        api_key="db-api-key",
        sender_id="123456",
        service_account_json=_service_account("db-project"),
        secret_provided=True,
    )

    cfg = push_config.current_push_config()
    assert cfg.enabled is True
    assert cfg.project_id == "db-project"
    assert cfg.api_key == "db-api-key"
    assert cfg.sender_id == "123456"


@pytest.mark.integration
async def test_full_service_account_survives_the_round_trip(
    session: AsyncSession,
) -> None:
    """A realistic service account comes back byte-identical, and parses.

    Stored truncated it would encrypt and save without complaint and then fail at
    ``json.loads`` on the next push — a long way from the settings page that
    accepted it. That is why the column is 8000 and not 2000.
    """
    account = _service_account()
    assert len(account) > 2000, "the fixture must exercise the wide column"

    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=True,
        project_id="demo-project",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=account,
        secret_provided=True,
    )

    stored = push_config.current_push_config().service_account_json
    assert stored == account
    assert json.loads(stored or "{}")["project_id"] == "demo-project"


@pytest.mark.integration
async def test_credential_is_kept_when_not_sent(session: AsyncSession) -> None:
    """Toggling the switch without re-pasting the JSON keeps the JSON."""
    account = _service_account()
    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=True,
        project_id="p",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=account,
        secret_provided=True,
    )
    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=False,
        project_id="p",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=None,
        secret_provided=False,
    )

    cfg = push_config.current_push_config()
    assert cfg.enabled is False
    assert cfg.service_account_json == account
