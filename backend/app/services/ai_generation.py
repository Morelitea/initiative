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
) -> list[str]:
    """Generate subtask suggestions using configured AI provider."""
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError("AI features are not enabled")

    if not resolved.api_key and resolved.provider != AIProvider.ollama:
        raise AIGenerationError("No API key configured for AI provider")

    if not resolved.provider:
        raise AIGenerationError("No AI provider configured")

    prompt = _build_subtasks_prompt(task)

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
) -> str:
    """Generate/enhance task description using configured AI provider."""
    resolved = await resolve_ai_settings(session, user, guild_id)

    if not resolved.enabled:
        raise AIGenerationError("AI features are not enabled")

    if not resolved.api_key and resolved.provider != AIProvider.ollama:
        raise AIGenerationError("No API key configured for AI provider")

    if not resolved.provider:
        raise AIGenerationError("No AI provider configured")

    prompt = _build_description_prompt(task)

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


def _build_subtasks_prompt(task: Task) -> str:
    """Build prompt for subtask generation."""
    description_part = f"\nDescription: {task.description}" if task.description else ""
    return f"""Generate actionable subtasks for this task.

Title: {task.title}{description_part}

Return 3-7 specific, actionable subtasks as a JSON array of strings.
Each subtask should be a clear action item that contributes to completing the main task.
Keep each subtask concise (under 100 characters).
Do not include numbering or bullet points in the subtask text.
Return ONLY the JSON array, no other text."""


def _build_description_prompt(task: Task) -> str:
    """Build prompt for description generation."""
    existing_description = ""
    if task.description:
        existing_description = f"\n\nExisting description (enhance this): {task.description}"

    return f"""Write a clear task description.

Title: {task.title}{existing_description}

Write 2-4 sentences explaining what needs to be done, the expected outcome, and any key considerations.
Be specific and actionable. Use markdown formatting if helpful.
Return ONLY the description text, no other commentary."""


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
