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
    # Convert Lexical JSON to markdown for better AI comprehension
    markdown_content = lexical_to_markdown(document_content)
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
    resolved = await resolve_ai_settings(session, user, guild_id, with_key=True)

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


# ---------------------------------------------------------------------------
# Lexical JSON → Markdown converter
# ---------------------------------------------------------------------------


def lexical_to_markdown(content: dict | None) -> str:
    """Convert Lexical JSON editor state to Markdown.

    Recursively traverses Lexical nodes and converts to markdown,
    preserving document structure so AI models can understand:
    - Document hierarchy via headings
    - Emphasis via bold/italic
    - Lists and enumerated items
    - Code snippets and quotes
    - Links
    """
    if not content:
        return ""

    root = content.get("root")
    if not root:
        return ""

    children = root.get("children", [])
    return _convert_nodes(children)


def _convert_nodes(nodes: list[dict], list_depth: int = 0) -> str:
    """Convert a list of Lexical nodes to markdown."""
    result = []
    for node in nodes:
        converted = _convert_node(node, list_depth)
        if converted:
            result.append(converted)
    return "\n\n".join(result)


def _convert_node(node: dict, list_depth: int = 0) -> str:
    """Convert a single Lexical node to markdown."""
    node_type = node.get("type", "")

    if node_type == "paragraph":
        return _convert_paragraph(node)
    elif node_type == "heading":
        return _convert_heading(node)
    elif node_type == "list":
        return _convert_list(node, list_depth)
    elif node_type == "listitem":
        return _convert_list_item(node, list_depth)
    elif node_type == "quote":
        return _convert_quote(node)
    elif node_type == "callout":
        return _convert_callout(node, list_depth)
    elif node_type in ("layout-container", "layout-item"):
        # Columns read one after another: what matters to a model is the
        # words and their order, not where they sat on the page.
        return _convert_nodes(node.get("children", []), list_depth)
    elif node_type == "code":
        return _convert_code_block(node)
    elif node_type == "horizontalrule":
        return "---"
    elif node_type == "text":
        return _convert_text(node)
    elif node_type == "link":
        return _convert_link(node)
    elif node_type == "linebreak":
        return "\n"
    elif node_type in ("mention", "custom-mention"):
        # Handle mention nodes - extract display text
        text = node.get("text", "") or node.get("mentionName", "")
        return f"@{text}" if text else ""
    else:
        # For unknown node types, try to extract text from children
        children = node.get("children", [])
        if children:
            return _convert_inline_children(children)
        return node.get("text", "")


def _convert_callout(node: dict, list_depth: int = 0) -> str:
    """A callout as Obsidian writes one: its kind, then its blocks behind
    ``>``."""
    variant = str(node.get("variant") or "note")
    body = _convert_nodes(node.get("children", []), list_depth)
    lines = [f"> [!{variant}]"]
    lines.extend(f"> {line}" if line else ">" for line in body.split("\n"))
    return "\n".join(lines)


def _convert_paragraph(node: dict) -> str:
    """Convert a paragraph node."""
    children = node.get("children", [])
    return _convert_inline_children(children)


def _convert_heading(node: dict) -> str:
    """Convert a heading node."""
    tag = node.get("tag", "h1")
    level = int(tag[1]) if tag and len(tag) == 2 and tag[1].isdigit() else 1
    prefix = "#" * level
    children = node.get("children", [])
    text = _convert_inline_children(children)
    return f"{prefix} {text}"


def _convert_list(node: dict, list_depth: int = 0) -> str:
    """Convert a list node."""
    list_type = node.get("listType", "bullet")
    children = node.get("children", [])
    items = []
    for i, item in enumerate(children):
        items.append(_convert_list_item(item, list_depth, list_type, i + 1))
    return "\n".join(items)


def _convert_list_item(
    node: dict,
    list_depth: int = 0,
    list_type: str = "bullet",
    index: int = 1,
) -> str:
    """Convert a list item node."""
    indent = "  " * list_depth
    prefix = "-" if list_type == "bullet" else f"{index}."
    children = node.get("children", [])

    # Check for nested list
    nested_list = None
    inline_children = []
    for child in children:
        if child.get("type") == "list":
            nested_list = child
        else:
            inline_children.append(child)

    text = _convert_inline_children(inline_children)
    result = f"{indent}{prefix} {text}"

    if nested_list:
        nested_md = _convert_list(nested_list, list_depth + 1)
        result = f"{result}\n{nested_md}"

    return result


def _convert_quote(node: dict) -> str:
    """Convert a quote/blockquote node."""
    children = node.get("children", [])
    # Handle nested paragraphs in blockquote
    lines = []
    for child in children:
        if child.get("type") == "paragraph":
            lines.append(_convert_paragraph(child))
        else:
            lines.append(_convert_inline_children([child]))
    text = "\n".join(lines)
    # Prefix each line with >
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _convert_code_block(node: dict) -> str:
    """Convert a code block node."""
    language = node.get("language", "")
    # Code blocks store text directly or in children
    code = node.get("code", "")
    if not code:
        children = node.get("children", [])
        code = _convert_inline_children(children)
    return f"```{language}\n{code}\n```"


def _convert_inline_children(children: list[dict]) -> str:
    """Convert inline children (text, links, etc.) to markdown."""
    result = []
    for child in children:
        child_type = child.get("type", "")
        if child_type == "text":
            result.append(_convert_text(child))
        elif child_type == "link":
            result.append(_convert_link(child))
        elif child_type == "linebreak":
            result.append("\n")
        elif child_type in ("mention", "custom-mention"):
            text = child.get("text", "") or child.get("mentionName", "")
            result.append(f"@{text}" if text else "")
        else:
            # Unknown inline type - try to get text or recurse
            text = child.get("text", "")
            if text:
                result.append(text)
            elif child.get("children"):
                result.append(_convert_inline_children(child.get("children", [])))
    return "".join(result)


def _convert_text(node: dict) -> str:
    """Convert a text node with formatting."""
    text = node.get("text", "")
    if not text:
        return ""

    format_flags = node.get("format", 0)
    # Lexical format flags: 1=bold, 2=italic, 4=strikethrough, 8=underline, 16=code
    is_bold = bool(format_flags & 1)
    is_italic = bool(format_flags & 2)
    is_code = bool(format_flags & 16)

    if is_code:
        return f"`{text}`"
    if is_bold and is_italic:
        return f"***{text}***"
    if is_bold:
        return f"**{text}**"
    if is_italic:
        return f"*{text}*"
    return text


def _convert_link(node: dict) -> str:
    """Convert a link node."""
    url = node.get("url", "")
    children = node.get("children", [])
    text = _convert_inline_children(children)
    return f"[{text}]({url})"
