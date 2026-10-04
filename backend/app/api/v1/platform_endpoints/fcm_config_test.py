"""``GET /settings/fcm-config``: the Firebase settings the app starts with.

With a service account the server's own settings are served; without one
pushes go through the push relay, and the relay's Android settings are.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.platform import push_config, push_relay

URL = "/api/v1/settings/fcm-config"

_RELAY_ANDROID = push_relay.AndroidConfig(
    project_id="morelitea-app",
    application_id="1:2:android:3",
    api_key="relay-api-key",
    sender_id="42",
)


def _configure(monkeypatch, *, enabled: bool, service_account: bool) -> None:
    cfg = push_config.ResolvedPushConfig(
        enabled=enabled,
        project_id="own-project",
        application_id="1:9:android:9",
        api_key="own-api-key",
        sender_id="9",
        service_account_json='{"type": "service_account"}' if service_account else None,
    )
    monkeypatch.setattr(
        push_config, "ensure_push_config_fresh", AsyncMock(return_value=cfg)
    )


@pytest.fixture
def relay_android(monkeypatch) -> AsyncMock:
    fetch = AsyncMock(return_value=_RELAY_ANDROID)
    monkeypatch.setattr(push_relay, "android_config", fetch)
    return fetch


async def test_push_off_serves_nothing(client, monkeypatch, relay_android):
    _configure(monkeypatch, enabled=False, service_account=False)

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "project_id": None,
        "application_id": None,
        "api_key": None,
        "sender_id": None,
    }
    relay_android.assert_not_awaited()


async def test_a_service_account_serves_the_servers_own_settings(
    client, monkeypatch, relay_android
):
    _configure(monkeypatch, enabled=True, service_account=True)

    response = await client.get(URL)

    assert response.json() == {
        "enabled": True,
        "project_id": "own-project",
        "application_id": "1:9:android:9",
        "api_key": "own-api-key",
        "sender_id": "9",
    }
    relay_android.assert_not_awaited()


async def test_no_service_account_serves_the_relays_settings(
    client, monkeypatch, relay_android
):
    _configure(monkeypatch, enabled=True, service_account=False)

    response = await client.get(URL)

    assert response.json() == {
        "enabled": True,
        "project_id": "morelitea-app",
        "application_id": "1:2:android:3",
        "api_key": "relay-api-key",
        "sender_id": "42",
    }


async def test_relay_settings_unavailable_still_says_enabled(
    client, monkeypatch, relay_android
):
    """An iPhone needs only ``enabled``; Android gets no Firebase project."""
    _configure(monkeypatch, enabled=True, service_account=False)
    relay_android.return_value = None

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "project_id": None,
        "application_id": None,
        "api_key": None,
        "sender_id": None,
    }
