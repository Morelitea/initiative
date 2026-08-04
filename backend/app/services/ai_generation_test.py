"""Tests for AI generation egress hardening.

Ollama + custom generation both route through the pinned ``request_public_target``
egress; ``allow_private`` is server-computed from the resolved connection (true
only for an operator Ollama connection) and never from request input.
"""

import pytest

from app.schemas.ai_settings import AIProvider, ConnectionScope, ResolvedAISettings
from app.services import ai_generation


class _Task:
    def __init__(self, title: str = "Ship it", description: str = "Do the thing"):
        self.title = title
        self.description = description


class _User:
    locale = "en"


def _resolved(
    provider: AIProvider, base_url: str | None, *, allow_private: bool
) -> ResolvedAISettings:
    return ResolvedAISettings(
        enabled=True,
        provider=provider,
        api_key=None if provider == AIProvider.ollama else "test-key",
        base_url=base_url,
        model="test-model",
        allow_private=allow_private,
        scope=ConnectionScope.platform if allow_private else ConnectionScope.guild,
        source="platform" if allow_private else "guild",
    )


class _Resp:
    status_code = 200

    def json(self):
        return {"message": {"content": "generated text"}}


@pytest.mark.unit
async def test_custom_private_base_url_rejected(monkeypatch):
    """A custom connection is always public (allow_private=False), so the pinned
    egress refuses a private target — no member/guild path reaches a private
    host."""

    async def fake_resolve(*args, **kwargs):
        return _resolved(AIProvider.custom, "http://10.0.0.1", allow_private=False)

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)

    with pytest.raises(ai_generation.AIGenerationError) as exc:
        await ai_generation.generate_description(None, _User(), 1, _Task())
    assert str(exc.value) == "AI_INVALID_BASE_URL"


@pytest.mark.unit
async def test_ollama_private_permitted_and_pinned(monkeypatch):
    """An operator Ollama connection (allow_private=True) reaches a private host,
    and the request goes through the pinned egress with allow_private threaded
    through."""
    captured: dict = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["allow_private"] = kwargs.get("allow_private")
        return _Resp()

    async def fake_resolve(*args, **kwargs):
        return _resolved(
            AIProvider.ollama, "http://169.254.169.254:11434", allow_private=True
        )

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)
    monkeypatch.setattr(ai_generation, "request_public_target", fake_request)

    out = await ai_generation.generate_description(None, _User(), 1, _Task())
    assert out == "generated text"
    assert captured["allow_private"] is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/chat")


@pytest.mark.unit
async def test_ollama_generation_does_not_allow_private_for_guild_scope(monkeypatch):
    """A guild-scoped Ollama connection (allow_private=False) cannot reach a
    private host — the pinned egress refuses it."""

    async def fake_resolve(*args, **kwargs):
        return _resolved(
            AIProvider.ollama, "http://10.1.2.3:11434", allow_private=False
        )

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)

    with pytest.raises(ai_generation.AIGenerationError) as exc:
        await ai_generation.generate_description(None, _User(), 1, _Task())
    assert str(exc.value) == "AI_INVALID_BASE_URL"
