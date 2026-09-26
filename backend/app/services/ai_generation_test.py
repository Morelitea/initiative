"""Tests for AI generation egress hardening.

Ollama + custom generation both route through the pinned ``request_public_target``
egress; ``allow_private`` is server-computed from the resolved connection (true
only for an operator Ollama connection) and never from request input.
"""

import json

import httpx
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


_CHOICES = {"choices": [{"message": {"content": " generated text "}}]}


@pytest.mark.parametrize(
    ("provider", "base_url", "url", "auth", "fields", "reply", "rejected"),
    [
        (
            AIProvider.openai,
            None,
            "https://api.openai.com/v1/chat/completions",
            {"authorization": "Bearer test-key"},
            {"temperature": 0.7, "max_tokens": 500},
            _CHOICES,
            "Invalid OpenAI API key",
        ),
        (
            AIProvider.anthropic,
            None,
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": "test-key", "anthropic-version": "2023-06-01"},
            {"max_tokens": 500},
            {"content": [{"text": " generated text "}]},
            "Invalid Anthropic API key",
        ),
        (
            AIProvider.ollama,
            "https://93.184.216.34:11434/",
            "https://93.184.216.34:11434/api/chat",
            {},
            {"stream": False},
            {"message": {"content": " generated text "}},
            "Ollama API error: 401",
        ),
        (
            AIProvider.custom,
            "https://93.184.216.34/v1",
            "https://93.184.216.34/v1/chat/completions",
            {"authorization": "Bearer test-key"},
            {"temperature": 0.7, "max_tokens": 500},
            _CHOICES,
            "Invalid API key",
        ),
    ],
)
async def test_every_provider_through_one_request_path(
    monkeypatch, provider, base_url, url, auth, fields, reply, rejected
):
    """Each provider's request carries its own endpoint, credentials and body
    shape, its reply is read from where that provider puts the text, and a
    rejected request reads as that provider's error."""
    sent: list[httpx.Request] = []
    status = 200

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json=reply if status == 200 else {})

    real_client = httpx.AsyncClient

    class _Client(real_client):
        def __init__(self, **kwargs):
            super().__init__(**{**kwargs, "transport": httpx.MockTransport(handler)})

    async def fake_resolve(*args, **kwargs):
        return _resolved(provider, base_url, allow_private=False)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_generation, "resolve_ai_settings", fake_resolve)

    out = await ai_generation.generate_description(None, _User(), 1, _Task())
    assert out == "generated text"
    request = sent[0]
    sent_to = f"{request.url.scheme}://{request.headers['host']}{request.url.path}"
    assert sent_to == url
    assert {k: request.headers.get(k) for k in auth} == auth
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert {k: body[k] for k in fields} == fields

    status = 401
    with pytest.raises(ai_generation.AIGenerationError) as exc:
        await ai_generation.generate_description(None, _User(), 1, _Task())
    assert str(exc.value) == rejected


# --- the editor state as markdown ---------------------------------------------


def _lexical_text(text):
    return {"type": "text", "text": text, "format": 0}


def test_a_callout_is_shown_as_its_kind_and_its_blocks():
    content = {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "callout",
                    "variant": "warning",
                    "children": [
                        {"type": "paragraph", "children": [_lexical_text("Careful")]},
                        {"type": "paragraph", "children": [_lexical_text("Really")]},
                    ],
                }
            ],
        }
    }
    assert (
        ai_generation.lexical_to_markdown(content)
        == "> [!warning]\n> Careful\n>\n> Really"
    )


def test_columns_are_shown_one_after_another():
    content = {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "layout-container",
                    "children": [
                        {
                            "type": "layout-item",
                            "children": [
                                {
                                    "type": "paragraph",
                                    "children": [_lexical_text("left")],
                                }
                            ],
                        },
                        {
                            "type": "layout-item",
                            "children": [
                                {
                                    "type": "paragraph",
                                    "children": [_lexical_text("right")],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    }
    assert ai_generation.lexical_to_markdown(content) == "left\n\nright"
