"""Tests for AI settings SSRF guard on base_url."""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.ai_settings import (
    _test_ollama_connection,
    _test_custom_connection,
    _fetch_ollama_models,
    _fetch_custom_models,
)


@pytest.mark.unit
async def test_ollama_test_connection_blocks_private_ip():
    """_test_ollama_connection rejects a private-IP base_url."""
    result = await _test_ollama_connection("http://169.254.169.254/", None)
    assert result.success is False
    assert "Invalid base URL" in result.message


@pytest.mark.unit
async def test_ollama_test_connection_allows_no_base_url():
    """_test_ollama_connection with no base_url uses the localhost default (not SSRF-guarded)."""
    with patch("app.services.ai_settings.httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3"}]}
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)

        result = await _test_ollama_connection(None, None)
        assert result.success is True


@pytest.mark.unit
async def test_custom_test_connection_blocks_private_ip():
    """_test_custom_connection rejects a private-IP base_url."""
    result = await _test_custom_connection(None, "http://10.0.0.1/", None)
    assert result.success is False
    assert "Invalid base URL" in result.message


@pytest.mark.unit
async def test_fetch_ollama_models_blocks_private_ip():
    """_fetch_ollama_models rejects a private-IP base_url."""
    models, error = await _fetch_ollama_models("http://192.168.1.1/")
    assert models == []
    assert error is not None
    assert "Invalid base URL" in error


@pytest.mark.unit
async def test_fetch_custom_models_blocks_private_ip():
    """_fetch_custom_models rejects a private-IP base_url."""
    models, error = await _fetch_custom_models(None, "http://172.16.0.1/")
    assert models == []
    assert error is not None
    assert "Invalid base URL" in error


@pytest.mark.unit
async def test_fetch_ollama_models_allows_no_base_url():
    """_fetch_ollama_models with no base_url uses localhost default (not SSRF-guarded)."""
    with patch("app.services.ai_settings.httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3"}]}
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)

        models, error = await _fetch_ollama_models(None)
        assert error is None
        assert "llama3" in models
