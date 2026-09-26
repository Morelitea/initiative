"""AI Generation service for task-related AI features.

This service provides AI-powered generation of checklist steps and descriptions
using the configured AI provider (OpenAI, Anthropic, Ollama, or custom).
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AIMessages
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.schemas.ai_settings import AIProvider
from app.services.ai_settings import failure_code, refusal_code, resolve_ai_settings
from app.services.export.lexical import editor_markdown
from app.services.safe_http import request_public_target

# Maximum output lengths to prevent excessive LLM responses
_MAX_CHECKLIST_ITEM_LENGTH = 200
_MAX_DESCRIPTION_LENGTH = 2000
_MAX_SUMMARY_LENGTH = 5000

_PROVIDER_FAULTS = frozenset(
    {AIMessages.PROVIDER_UNAVAILABLE, AIMessages.PROVIDER_ERROR}
)


class AIGenerationError(Exception):
    """A generation that failed, with the message code and status the
    endpoint answers: a fault on the provider's side is a bad gateway."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = 502 if code in _PROVIDER_FAULTS else 400


@dataclass(frozen=True)
class _Job:
    """What one kind of generation asks of the model."""

    temperature: float
    max_tokens: int
    timeout: float


_SHORT_JOB = _Job(temperature=0.7, max_tokens=500, timeout=60.0)
_SUMMARY_JOB = _Job(temperature=0.5, max_tokens=1000, timeout=120.0)


async def generate_checklist(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    task: Task,
    *,
    initiative_name: str | None = None,
    project_name: str | None = None,
) -> list[str]:
    """Suggest checklist steps using the configured AI provider."""
    prompt = _build_checklist_prompt(
        task, initiative_name, project_name, locale=user.locale or "en"
    )
    content = await _generate(session, user, guild_id, prompt, _SHORT_JOB)
    return _parse_checklist_response(content)


async def generate_description(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    task: Task,
    *,
    initiative_name: str | None = None,
    project_name: str | None = None,
) -> str:
    """Generate/enhance task description using configured AI provider."""
    prompt = _build_description_prompt(
        task, initiative_name, project_name, locale=user.locale or "en"
    )
    content = await _generate(session, user, guild_id, prompt, _SHORT_JOB)
    return _truncate_output(content.strip(), _MAX_DESCRIPTION_LENGTH)


async def generate_document_summary(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    document_content: dict | None,
    document_name: str,
) -> str:
    """Generate a summary of a document using configured AI provider."""
    # The editor state as markdown, which a model reads better than JSON
    markdown_content = editor_markdown(document_content, reading=True)
    if not markdown_content.strip():
        raise AIGenerationError(AIMessages.DOCUMENT_EMPTY)

    prompt = _build_summary_prompt(
        document_name, markdown_content, locale=user.locale or "en"
    )
    content = await _generate(session, user, guild_id, prompt, _SUMMARY_JOB)
    return _truncate_output(content.strip(), _MAX_SUMMARY_LENGTH)


def _locale_instruction(locale: str) -> str:
    """Return a prompt instruction for the target language, empty for English."""
    if locale == "en":
        return ""
    _LOCALE_NAMES = {
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
    }
    lang = _LOCALE_NAMES.get(locale, locale)
    return f"Write your response in {lang}.\n"


def _truncate_output(text: str, max_length: int) -> str:
    """Truncate LLM output to a maximum length."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    # Try to break at last word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


# ---------------------------------------------------------------------------
# Prompt builders — return (system_prompt, user_content) tuples.
#
# System prompts contain only instructions. User content wraps all
# user-provided data in XML tags so the LLM can distinguish it from
# instructions, mitigating prompt-injection risks.
# ---------------------------------------------------------------------------


def _build_summary_prompt(
    title: str, content: str, *, locale: str = "en"
) -> tuple[str, str]:
    """Build system/user prompt pair for document summarization."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Summarize the provided document in 2-4 paragraphs, focusing on the key points.\n"
        "Write a clear, concise summary that captures the main ideas and important details.\n"
        f"{lang_instruction}"
        "Return ONLY the summary text, no other commentary."
    )
    user_content = (
        f"<document>\n"
        f"  <title>{html.escape(title)}</title>\n"
        f"  <content>\n{html.escape(content)}\n  </content>\n"
        f"</document>"
    )
    return system_prompt, user_content


def _build_checklist_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Build system/user prompt pair for checklist generation."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Break the task provided by the user into checklist steps.\n"
        "Return 3-7 specific, actionable steps as a JSON array of strings.\n"
        "Each step should be a clear action that contributes to completing the task.\n"
        "Keep each step concise (under 100 characters).\n"
        "Do not include numbering or bullet points in the step text.\n"
        f"{lang_instruction}"
        "Return ONLY the JSON array, no other text."
    )

    context_parts = []
    if initiative_name:
        context_parts.append(
            f"  <initiative>{html.escape(initiative_name)}</initiative>"
        )
    if project_name:
        context_parts.append(f"  <project>{html.escape(project_name)}</project>")
    context_xml = (
        "\n<context>\n" + "\n".join(context_parts) + "\n</context>"
        if context_parts
        else ""
    )

    description_xml = (
        f"\n  <description>{html.escape(task.description)}</description>"
        if task.description
        else ""
    )
    user_content = (
        f"<task>\n"
        f"  <title>{html.escape(task.title)}</title>{description_xml}\n"
        f"</task>{context_xml}"
    )
    return system_prompt, user_content


def _build_description_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Build system/user prompt pair for description generation."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Write a clear task description for the task provided by the user.\n"
        "Write 2-4 sentences explaining what needs to be done, the expected outcome, "
        "and any key considerations.\n"
        "Be specific and actionable. Use markdown formatting if helpful.\n"
        f"{lang_instruction}"
        "Return ONLY the description text, no other commentary."
    )

    context_parts = []
    if initiative_name:
        context_parts.append(
            f"  <initiative>{html.escape(initiative_name)}</initiative>"
        )
    if project_name:
        context_parts.append(f"  <project>{html.escape(project_name)}</project>")
    context_xml = (
        "\n<context>\n" + "\n".join(context_parts) + "\n</context>"
        if context_parts
        else ""
    )

    existing_xml = (
        f"\n  <existing_description>{html.escape(task.description)}</existing_description>"
        if task.description
        else ""
    )
    user_content = (
        f"<task>\n"
        f"  <title>{html.escape(task.title)}</title>{existing_xml}\n"
        f"</task>{context_xml}"
    )
    return system_prompt, user_content


def _parse_checklist_response(text: str) -> list[str]:
    """Parse AI response to extract the list of steps."""
    text = text.strip()

    # Try to find JSON array in response
    start_idx = text.find("[")
    end_idx = text.rfind("]")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_text = text[start_idx : end_idx + 1]
        try:
            parsed = json.loads(json_text)
            if isinstance(parsed, list):
                return [
                    _truncate_output(str(s).strip(), _MAX_CHECKLIST_ITEM_LENGTH)
                    for s in parsed
                    if s and str(s).strip()
                ]
        except json.JSONDecodeError:
            pass

    # Fallback: split by newlines if JSON parsing fails
    lines = text.split("\n")
    items: list[str] = []
    for line in lines:
        line = line.strip()
        # Remove common list prefixes
        for prefix in ["- ", "* ", "• "]:
            if line.startswith(prefix):
                line = line[len(prefix) :]
                break
        # Remove numbered prefixes like "1. " or "1) "
        if line and line[0].isdigit():
            for sep in [". ", ") ", ": "]:
                if sep in line[:4]:
                    line = line.split(sep, 1)[-1]
                    break
        if line:
            items.append(_truncate_output(line, _MAX_CHECKLIST_ITEM_LENGTH))

    return items[:7]


def _openai_messages(system_prompt: str, user_content: str) -> list[dict[str, str]]:
    """Build a messages array for OpenAI-compatible APIs."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Providers — one request path, with what differs per provider in an adapter.
# ---------------------------------------------------------------------------


def _bearer(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _chat_body(
    model: str, system_prompt: str, user_content: str, job: _Job
) -> dict[str, Any]:
    """An OpenAI-compatible chat completion body."""
    return {
        "model": model,
        "messages": _openai_messages(system_prompt, user_content),
        "temperature": job.temperature,
        "max_tokens": job.max_tokens,
    }


def _openai_body(
    model: str, system_prompt: str, user_content: str, job: _Job
) -> dict[str, Any]:
    """Reasoning models (o1, o3) and GPT-5+ take ``max_completion_tokens``,
    which also counts reasoning tokens, and no temperature."""
    if not model.lower().startswith(("o1", "o3", "gpt-5")):
        return _chat_body(model, system_prompt, user_content, job)
    return {
        "model": model,
        "messages": _openai_messages(system_prompt, user_content),
        "max_completion_tokens": job.max_tokens * 2,
    }


def _anthropic_body(
    model: str, system_prompt: str, user_content: str, job: _Job
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": job.max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }


def _ollama_body(
    model: str, system_prompt: str, user_content: str, job: _Job
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": _openai_messages(system_prompt, user_content),
        "stream": False,
    }


def _choice_content(data: Any) -> str:
    return data["choices"][0]["message"]["content"]


@dataclass(frozen=True)
class _ProviderAdapter:
    """The parts of a chat completion that differ by provider."""

    default_model: str
    headers: Callable[[str | None], dict[str, str]]
    body: Callable[[str, str, str, _Job], dict[str, Any]]
    content: Callable[[Any], str]
    #: The provider's own endpoint. Without one, the request goes to the
    #: connection's base URL plus ``path``, through the pinned egress.
    endpoint: str | None = None
    path: str = ""
    default_base_url: str | None = None


_ADAPTERS: dict[AIProvider, _ProviderAdapter] = {
    AIProvider.openai: _ProviderAdapter(
        default_model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1/chat/completions",
        headers=_bearer,
        body=_openai_body,
        content=_choice_content,
    ),
    AIProvider.anthropic: _ProviderAdapter(
        default_model="claude-3-5-haiku-20241022",
        endpoint="https://api.anthropic.com/v1/messages",
        headers=lambda api_key: {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
        },
        body=_anthropic_body,
        content=lambda data: data["content"][0]["text"],
    ),
    AIProvider.ollama: _ProviderAdapter(
        default_model="llama3.2",
        path="/api/chat",
        default_base_url="http://localhost:11434",
        headers=lambda api_key: {},
        body=_ollama_body,
        content=lambda data: data["message"]["content"],
    ),
    AIProvider.custom: _ProviderAdapter(
        default_model="default",
        path="/chat/completions",
        headers=_bearer,
        body=_chat_body,
        content=_choice_content,
    ),
}


async def _generate(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    prompt: tuple[str, str],
    job: _Job,
) -> str:
    """Run one chat completion on the caller's resolved AI connection and
    return the model's text.

    ``allow_private`` is server-computed by :func:`resolve_ai_settings` (true
    only for an operator Ollama connection), never from request input.
    """
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError(AIMessages.NOT_ENABLED)

    if not resolved.provider or (
        not resolved.api_key and resolved.provider != AIProvider.ollama
    ):
        raise AIGenerationError(AIMessages.NOT_CONFIGURED)

    adapter = _ADAPTERS[resolved.provider]
    base_url = (resolved.base_url or adapter.default_base_url or "").rstrip("/")
    headers = adapter.headers(resolved.api_key)
    body = adapter.body(resolved.model or adapter.default_model, *prompt, job)
    try:
        if adapter.endpoint:
            async with httpx.AsyncClient(timeout=job.timeout) as client:
                response = await client.post(
                    adapter.endpoint, headers=headers, json=body
                )
        elif not base_url:
            raise AIGenerationError(AIMessages.INVALID_BASE_URL)
        else:
            response = await request_public_target(
                "POST",
                f"{base_url}{adapter.path}",
                headers=headers,
                json=body,
                timeout=job.timeout,
                allow_private=resolved.allow_private,
            )

        if response.status_code != 200:
            raise AIGenerationError(
                refusal_code(
                    resolved.provider, response, sent_key=bool(resolved.api_key)
                )
            )
        return adapter.content(response.json())
    except AIGenerationError:
        raise
    except Exception as exc:
        raise AIGenerationError(failure_code(resolved.provider, exc)) from exc
