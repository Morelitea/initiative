"""Unit tests for the AI settings service (mode-based connections).

Covers the security-critical pure logic that needs no DB:
- ``allow_private`` is derived ONLY from (provider == ollama, scope == platform).
- A stored connection's ``base_url`` is validated public-only except for a
  platform Ollama connection.
- The model-list / probe egress threads ``allow_private`` through the pinned
  ``request_public_target``.

End-to-end resolution, connection CRUD, and the exfil-impossible property are
covered by the endpoint integration tests (``ai_connections_test.py``).
"""

import pytest
from fastapi import HTTPException

from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider
from app.services import ai_settings
from app.services.ai_settings import (
    _allow_private_for,
    _validate_connection_base_url,
)


@pytest.mark.unit
def test_allow_private_only_for_platform_ollama():
    assert _allow_private_for(AIProvider.ollama, "platform") is True
    # Every other combination is public-only.
    assert _allow_private_for(AIProvider.ollama, "guild") is False
    assert _allow_private_for(AIProvider.custom, "platform") is False
    assert _allow_private_for(AIProvider.openai, "platform") is False
    assert _allow_private_for(AIProvider.custom, "guild") is False


@pytest.mark.unit
async def test_guild_ollama_private_base_url_rejected():
    """A guild admin can never persist a private/internal target."""
    with pytest.raises(HTTPException) as exc:
        await _validate_connection_base_url(
            AIProvider.ollama, "http://169.254.169.254", "guild"
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == AIMessages.INVALID_BASE_URL


@pytest.mark.unit
async def test_platform_custom_private_base_url_rejected():
    """Even the operator gets the guard for a custom connection — only Ollama is
    exempt at platform scope."""
    with pytest.raises(HTTPException):
        await _validate_connection_base_url(
            AIProvider.custom, "http://10.0.0.1", "platform"
        )


@pytest.mark.unit
async def test_platform_ollama_private_base_url_allowed():
    """The one permitted private egress: an operator Ollama connection."""
    # Should not raise.
    await _validate_connection_base_url(
        AIProvider.ollama, "http://10.0.0.1:11434", "platform"
    )


@pytest.mark.unit
async def test_no_base_url_is_allowed():
    await _validate_connection_base_url(AIProvider.openai, None, "platform")


@pytest.mark.unit
async def test_list_ollama_models_threads_allow_private(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"models": [{"name": "llama3.2"}]}

    async def fake_request(method, url, **kwargs):
        captured["url"] = url
        captured["allow_private"] = kwargs.get("allow_private")
        return _Resp()

    monkeypatch.setattr(ai_settings, "request_public_target", fake_request)
    models, error = await ai_settings._list_ollama_models(
        "http://10.0.0.1:11434", allow_private=True
    )
    assert error is None
    assert "llama3.2" in models
    assert captured["allow_private"] is True
    assert captured["url"].endswith("/api/tags")


@pytest.mark.unit
async def test_list_custom_models_rejects_private_when_not_allowed(monkeypatch):
    # Real pinned egress: a private literal IP with allow_private=False is
    # refused before any network call.
    models, error = await ai_settings._list_custom_models(
        None, "http://192.168.1.5", allow_private=False
    )
    assert models == []
    assert error == AIMessages.INVALID_BASE_URL
