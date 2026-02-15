"""AI Generation service for task-related AI features.

This service provides AI-powered generation of subtasks and descriptions
using the configured AI provider (OpenAI, Anthropic, Ollama, or custom).
"""

from __future__ import annotations

import json
import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.task import Task
from app.models.user import User
from app.schemas.ai_settings import AIProvider
from app.services.ai_settings import resolve_ai_settings


class AIGenerationError(Exception):
    """Raised when AI generation fails."""
    pass


async def generate_subtasks(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    task: Task,
    *,
    initiative_name: str | None = None,
    project_name: str | None = None,
) -> list[str]:
    """Generate subtask suggestions using configured AI provider."""
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError("AI features are not enabled")

    if not resolved.api_key and resolved.provider != AIProvider.ollama:
        raise AIGenerationError("No API key configured for AI provider")

    if not resolved.provider:
        raise AIGenerationError("No AI provider configured")

    locale = getattr(user, "locale", None) or "en"
    prompt = _build_subtasks_prompt(task, initiative_name, project_name, locale=locale)

    if resolved.provider == AIProvider.openai:
        return await _generate_openai_subtasks(
            api_key=resolved.api_key,
            model=resolved.model or "gpt-4o-mini",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.anthropic:
        return await _generate_anthropic_subtasks(
            api_key=resolved.api_key,
            model=resolved.model or "claude-3-5-haiku-20241022",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.ollama:
        return await _generate_ollama_subtasks(
            base_url=resolved.base_url or "http://localhost:11434",
            model=resolved.model or "llama3.2",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.custom:
        return await _generate_custom_subtasks(
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            model=resolved.model,
            prompt=prompt,
        )
    else:
        raise AIGenerationError(f"Unsupported AI provider: {resolved.provider}")


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
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError("AI features are not enabled")

    if not resolved.api_key and resolved.provider != AIProvider.ollama:
        raise AIGenerationError("No API key configured for AI provider")

    if not resolved.provider:
        raise AIGenerationError("No AI provider configured")

    locale = getattr(user, "locale", None) or "en"
    prompt = _build_description_prompt(task, initiative_name, project_name, locale=locale)

    if resolved.provider == AIProvider.openai:
        return await _generate_openai_description(
            api_key=resolved.api_key,
            model=resolved.model or "gpt-4o-mini",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.anthropic:
        return await _generate_anthropic_description(
            api_key=resolved.api_key,
            model=resolved.model or "claude-3-5-haiku-20241022",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.ollama:
        return await _generate_ollama_description(
            base_url=resolved.base_url or "http://localhost:11434",
            model=resolved.model or "llama3.2",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.custom:
        return await _generate_custom_description(
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            model=resolved.model,
            prompt=prompt,
        )
    else:
        raise AIGenerationError(f"Unsupported AI provider: {resolved.provider}")


async def generate_document_summary(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    document_content: dict | None,
    document_title: str,
) -> str:
    """Generate a summary of a document using configured AI provider."""
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError("AI features are not enabled")

    if not resolved.api_key and resolved.provider != AIProvider.ollama:
        raise AIGenerationError("No API key configured for AI provider")

    if not resolved.provider:
        raise AIGenerationError("No AI provider configured")

    # Convert Lexical JSON to markdown for better AI comprehension
    markdown_content = lexical_to_markdown(document_content)
    if not markdown_content.strip():
        raise AIGenerationError("Document has no content to summarize")

    locale = getattr(user, "locale", None) or "en"
    prompt = _build_summary_prompt(document_title, markdown_content, locale=locale)

    if resolved.provider == AIProvider.openai:
        return await _generate_openai_summary(
            api_key=resolved.api_key,
            model=resolved.model or "gpt-4o-mini",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.anthropic:
        return await _generate_anthropic_summary(
            api_key=resolved.api_key,
            model=resolved.model or "claude-3-5-haiku-20241022",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.ollama:
        return await _generate_ollama_summary(
            base_url=resolved.base_url or "http://localhost:11434",
            model=resolved.model or "llama3.2",
            prompt=prompt,
        )
    elif resolved.provider == AIProvider.custom:
        return await _generate_custom_summary(
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            model=resolved.model,
            prompt=prompt,
        )
    else:
        raise AIGenerationError(f"Unsupported AI provider: {resolved.provider}")


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


def _build_summary_prompt(title: str, content: str, *, locale: str = "en") -> str:
    """Build prompt for document summarization."""
    lang_instruction = _locale_instruction(locale)
    return f"""Summarize this document in 2-4 paragraphs, focusing on the key points.

Document Title: {title}

Document Content:
{content}

Write a clear, concise summary that captures the main ideas and important details.
{lang_instruction}Return ONLY the summary text, no other commentary."""


async def _generate_openai_summary(
    api_key: str | None,
    model: str,
    prompt: str,
) -> str:
    """Generate summary using OpenAI API."""
    if not api_key:
        raise AIGenerationError("API key is required for OpenAI")

    try:
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _is_openai_new_api_model(model):
            payload["max_completion_tokens"] = 2000
        else:
            payload["temperature"] = 0.5
            payload["max_tokens"] = 1000

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid OpenAI API key")
            elif response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
                raise AIGenerationError(f"OpenAI API error: {error_msg}")

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        raise AIGenerationError("OpenAI request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"OpenAI request failed: {str(e)}")


async def _generate_anthropic_summary(
    api_key: str | None,
    model: str,
    prompt: str,
) -> str:
    """Generate summary using Anthropic API."""
    if not api_key:
        raise AIGenerationError("API key is required for Anthropic")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid Anthropic API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"Anthropic API error: {response.status_code}")

            data = response.json()
            return data["content"][0]["text"].strip()
    except httpx.TimeoutException:
        raise AIGenerationError("Anthropic request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Anthropic request failed: {str(e)}")


async def _generate_ollama_summary(
    base_url: str,
    model: str,
    prompt: str,
) -> str:
    """Generate summary using Ollama API."""
    url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise AIGenerationError(f"Ollama API error: {response.status_code}")

            data = response.json()
            return data["message"]["content"].strip()
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to Ollama at {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Ollama request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Ollama request failed: {str(e)}")


async def _generate_custom_summary(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    prompt: str,
) -> str:
    """Generate summary using custom OpenAI-compatible API."""
    if not base_url:
        raise AIGenerationError("Base URL is required for custom provider")

    url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{url}/chat/completions",
                headers=headers,
                json={
                    "model": model or "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": 1000,
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"API error: {response.status_code}")

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Request failed: {str(e)}")


def _build_subtasks_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> str:
    """Build prompt for subtask generation."""
    context_parts = []
    if initiative_name:
        context_parts.append(f"Initiative: {initiative_name}")
    if project_name:
        context_parts.append(f"Project: {project_name}")
    context_section = "\n".join(context_parts) + "\n" if context_parts else ""

    lang_instruction = _locale_instruction(locale)
    description_part = f"\nDescription: {task.description}" if task.description else ""
    return f"""Generate actionable subtasks for this task.

{context_section}Title: {task.title}{description_part}

Return 3-7 specific, actionable subtasks as a JSON array of strings.
Each subtask should be a clear action item that contributes to completing the main task.
Keep each subtask concise (under 100 characters).
Do not include numbering or bullet points in the subtask text.
{lang_instruction}Return ONLY the JSON array, no other text."""


def _build_description_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> str:
    """Build prompt for description generation."""
    context_parts = []
    if initiative_name:
        context_parts.append(f"Initiative: {initiative_name}")
    if project_name:
        context_parts.append(f"Project: {project_name}")
    context_section = "\n".join(context_parts) + "\n" if context_parts else ""

    existing_description = ""
    if task.description:
        existing_description = f"\n\nExisting description (enhance this): {task.description}"

    lang_instruction = _locale_instruction(locale)
    return f"""Write a clear task description.

{context_section}Title: {task.title}{existing_description}

Write 2-4 sentences explaining what needs to be done, the expected outcome, and any key considerations.
Be specific and actionable. Use markdown formatting if helpful.
{lang_instruction}Return ONLY the description text, no other commentary."""


def _parse_subtasks_response(text: str) -> list[str]:
    """Parse AI response to extract subtask list."""
    text = text.strip()

    # Try to find JSON array in response
    start_idx = text.find("[")
    end_idx = text.rfind("]")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_text = text[start_idx:end_idx + 1]
        try:
            subtasks = json.loads(json_text)
            if isinstance(subtasks, list):
                return [str(s).strip() for s in subtasks if s and str(s).strip()]
        except json.JSONDecodeError:
            pass

    # Fallback: split by newlines if JSON parsing fails
    lines = text.split("\n")
    subtasks = []
    for line in lines:
        line = line.strip()
        # Remove common list prefixes
        for prefix in ["- ", "* ", "• "]:
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        # Remove numbered prefixes like "1. " or "1) "
        if line and line[0].isdigit():
            for sep in [". ", ") ", ": "]:
                if sep in line[:4]:
                    line = line.split(sep, 1)[-1]
                    break
        if line:
            subtasks.append(line)

    return subtasks[:7]  # Limit to 7 subtasks


def _is_openai_new_api_model(model: str) -> bool:
    """Check if the model uses the newer OpenAI API parameters.

    Reasoning models (o1, o3) and GPT-5+ models use:
    - max_completion_tokens instead of max_tokens
    - Don't support temperature parameter
    """
    model_lower = model.lower()
    # Reasoning models and GPT-5+ series
    return model_lower.startswith(("o1", "o3", "gpt-5"))


# OpenAI implementation
async def _generate_openai_subtasks(
    api_key: str | None,
    model: str,
    prompt: str,
) -> list[str]:
    """Generate subtasks using OpenAI API."""
    if not api_key:
        raise AIGenerationError("API key is required for OpenAI")

    try:
        # Build request payload - newer models have different parameter requirements
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _is_openai_new_api_model(model):
            # Reasoning models and GPT-5+ use max_completion_tokens, no temperature
            payload["max_completion_tokens"] = 1000
        else:
            payload["temperature"] = 0.7
            payload["max_tokens"] = 500

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid OpenAI API key")
            elif response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
                raise AIGenerationError(f"OpenAI API error: {error_msg}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return _parse_subtasks_response(content)
    except httpx.TimeoutException:
        raise AIGenerationError("OpenAI request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"OpenAI request failed: {str(e)}")


async def _generate_openai_description(
    api_key: str | None,
    model: str,
    prompt: str,
) -> str:
    """Generate description using OpenAI API."""
    if not api_key:
        raise AIGenerationError("API key is required for OpenAI")

    try:
        # Build request payload - newer models have different parameter requirements
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _is_openai_new_api_model(model):
            # Reasoning models and GPT-5+ use max_completion_tokens, no temperature
            payload["max_completion_tokens"] = 1000
        else:
            payload["temperature"] = 0.7
            payload["max_tokens"] = 500

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid OpenAI API key")
            elif response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
                raise AIGenerationError(f"OpenAI API error: {error_msg}")

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        raise AIGenerationError("OpenAI request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"OpenAI request failed: {str(e)}")


# Anthropic implementation
async def _generate_anthropic_subtasks(
    api_key: str | None,
    model: str,
    prompt: str,
) -> list[str]:
    """Generate subtasks using Anthropic API."""
    if not api_key:
        raise AIGenerationError("API key is required for Anthropic")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid Anthropic API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"Anthropic API error: {response.status_code}")

            data = response.json()
            content = data["content"][0]["text"]
            return _parse_subtasks_response(content)
    except httpx.TimeoutException:
        raise AIGenerationError("Anthropic request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Anthropic request failed: {str(e)}")


async def _generate_anthropic_description(
    api_key: str | None,
    model: str,
    prompt: str,
) -> str:
    """Generate description using Anthropic API."""
    if not api_key:
        raise AIGenerationError("API key is required for Anthropic")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid Anthropic API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"Anthropic API error: {response.status_code}")

            data = response.json()
            return data["content"][0]["text"].strip()
    except httpx.TimeoutException:
        raise AIGenerationError("Anthropic request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Anthropic request failed: {str(e)}")


# Ollama implementation
async def _generate_ollama_subtasks(
    base_url: str,
    model: str,
    prompt: str,
) -> list[str]:
    """Generate subtasks using Ollama API."""
    url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise AIGenerationError(f"Ollama API error: {response.status_code}")

            data = response.json()
            content = data["message"]["content"]
            return _parse_subtasks_response(content)
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to Ollama at {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Ollama request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Ollama request failed: {str(e)}")


async def _generate_ollama_description(
    base_url: str,
    model: str,
    prompt: str,
) -> str:
    """Generate description using Ollama API."""
    url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise AIGenerationError(f"Ollama API error: {response.status_code}")

            data = response.json()
            return data["message"]["content"].strip()
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to Ollama at {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Ollama request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Ollama request failed: {str(e)}")


# Custom OpenAI-compatible implementation
async def _generate_custom_subtasks(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    prompt: str,
) -> list[str]:
    """Generate subtasks using custom OpenAI-compatible API."""
    if not base_url:
        raise AIGenerationError("Base URL is required for custom provider")

    url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{url}/chat/completions",
                headers=headers,
                json={
                    "model": model or "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"API error: {response.status_code}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return _parse_subtasks_response(content)
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Request failed: {str(e)}")


async def _generate_custom_description(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    prompt: str,
) -> str:
    """Generate description using custom OpenAI-compatible API."""
    if not base_url:
        raise AIGenerationError("Base URL is required for custom provider")

    url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{url}/chat/completions",
                headers=headers,
                json={
                    "model": model or "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
            )

            if response.status_code == 401:
                raise AIGenerationError("Invalid API key")
            elif response.status_code != 200:
                raise AIGenerationError(f"API error: {response.status_code}")

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.ConnectError:
        raise AIGenerationError(f"Could not connect to {url}")
    except httpx.TimeoutException:
        raise AIGenerationError("Request timed out")
    except AIGenerationError:
        raise
    except Exception as e:
        raise AIGenerationError(f"Request failed: {str(e)}")


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
