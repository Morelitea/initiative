"""Tests for AI generation request hardening."""

import pytest

from app.schemas.ai_settings import AIProvider, ResolvedAISettings
from app.services import ai_generation


async def _resolved_settings(
    provider: AIProvider, base_url: str | None
) -> ResolvedAISettings:
    return ResolvedAISettings(
        enabled=True,
        provider=provider,
        api_key=None if provider == AIProvider.ollama else "test-key",
        base_url=base_url,
        model="test-model",
        source="user",
    )


@pytest.mark.unit
async def test_generate_subtasks_blocks_existing_private_ollama_base_url(monkeypatch):
    async def fake_resolve(*args, **kwargs):
        return await _resolved_settings(AIProvider.ollama, "http://169.254.169.254")

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)

    with pytest.raises(ai_generation.AIGenerationError) as exc_info:
        await ai_generation.generate_subtasks(None, object(), 1, object())

    assert str(exc_info.value) == "AI_INVALID_BASE_URL"


@pytest.mark.unit
async def test_generate_description_blocks_existing_private_custom_base_url(
    monkeypatch,
):
    async def fake_resolve(*args, **kwargs):
        return await _resolved_settings(AIProvider.custom, "http://10.0.0.1")

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)

    with pytest.raises(ai_generation.AIGenerationError) as exc_info:
        await ai_generation.generate_description(None, object(), 1, object())

    assert str(exc_info.value) == "AI_INVALID_BASE_URL"
