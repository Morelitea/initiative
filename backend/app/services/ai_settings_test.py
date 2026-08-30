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


def _openai_compatible_catalog(count: int) -> list[dict[str, str]]:
    return [{"id": f"vendor/model-{i}"} for i in range(count)]


def _custom_conn(model: str) -> ai_settings._ConnRow:
    return ai_settings._ConnRow(
        scope="guild",
        id=1,
        label="OpenRouter",
        provider=AIProvider.custom.value,
        base_url="https://openrouter.test/api/v1",
        model=model,
        api_key_encrypted=None,
        enabled=True,
        is_default=True,
        allow_member_keys=False,
    )


def _stub_catalog(monkeypatch, catalog: list[dict[str, str]]) -> None:
    class _Resp:
        status_code = 200

        def json(self):
            return {"data": catalog}

    async def fake_request(method, url, **kwargs):
        return _Resp()

    monkeypatch.setattr(ai_settings, "request_public_target", fake_request)


@pytest.mark.unit
async def test_list_custom_models_returns_whole_catalog(monkeypatch):
    # Gateways like OpenRouter list hundreds of models; a short cap would hide
    # most of them from the selector and from the probe's membership check.
    _stub_catalog(monkeypatch, _openai_compatible_catalog(400))
    models, error = await ai_settings._list_custom_models(
        "key", "https://openrouter.test/api/v1", allow_private=False
    )
    assert error is None
    assert len(models) == 400
    assert "vendor/model-399" in models


@pytest.mark.unit
async def test_probe_accepts_model_beyond_the_first_page(monkeypatch):
    _stub_catalog(monkeypatch, _openai_compatible_catalog(400))
    result = await ai_settings._probe(_custom_conn("vendor/model-114"), "key")
    assert result.success is True


@pytest.mark.unit
async def test_probe_reports_a_model_the_catalog_does_not_have(monkeypatch):
    _stub_catalog(monkeypatch, _openai_compatible_catalog(400))
    result = await ai_settings._probe(_custom_conn("vendor/nope"), "key")
    assert result.success is False
    assert "not found" in result.message


@pytest.mark.unit
async def test_probe_does_not_reject_against_a_truncated_catalog(monkeypatch):
    # At the cap the listing is known-incomplete, so absence proves nothing.
    _stub_catalog(
        monkeypatch, _openai_compatible_catalog(ai_settings._MODEL_LIST_CAP + 10)
    )
    result = await ai_settings._probe(_custom_conn("vendor/unlisted"), "key")
    assert result.success is True


@pytest.mark.unit
async def test_list_anthropic_models_requests_a_full_page(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [{"id": "claude-haiku-4-5-20251001"}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            captured["params"] = kwargs.get("params")
            return _Resp()

    monkeypatch.setattr(ai_settings.httpx, "AsyncClient", lambda **kw: _Client())
    models, error = await ai_settings._list_anthropic_models("key")
    assert error is None
    assert models == ["claude-haiku-4-5-20251001"]
    # Without an explicit limit the endpoint returns only its small first page.
    assert captured["params"] == {"limit": ai_settings._MODEL_LIST_CAP}
