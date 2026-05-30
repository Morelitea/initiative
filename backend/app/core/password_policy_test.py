"""Unit tests for the password policy module."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.messages import PasswordMessages
from app.core.password_policy import (
    PASSWORD_MIN_LENGTH,
    PasswordPolicyError,
    enforce_password_policy,
    validate_new_password,
)
from app.services import hibp


@pytest.mark.unit
class TestValidateNewPassword:
    async def test_accepts_password_at_minimum_length(self, monkeypatch):
        # HIBP is already disabled by the autouse fixture in conftest,
        # but assert explicitly to make the unit boundary clear.
        async def _not_breached(_pw: str) -> bool:
            return False

        monkeypatch.setattr(hibp, "is_password_breached", _not_breached)
        # Should not raise.
        await validate_new_password("a" * PASSWORD_MIN_LENGTH)

    async def test_rejects_password_one_char_short(self):
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password("a" * (PASSWORD_MIN_LENGTH - 1))
        assert excinfo.value.code == PasswordMessages.TOO_SHORT

    async def test_rejects_empty_password(self):
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password("")
        assert excinfo.value.code == PasswordMessages.TOO_SHORT

    async def test_rejects_breached_password(self, monkeypatch):
        calls: list[str] = []

        async def _breached(pw: str) -> bool:
            calls.append(pw)
            return True

        monkeypatch.setattr(hibp, "is_password_breached", _breached)

        candidate = "long-enough-but-pwned"
        with pytest.raises(PasswordPolicyError) as excinfo:
            await validate_new_password(candidate)
        assert excinfo.value.code == PasswordMessages.BREACHED
        # The breach lookup must receive the plaintext (so it can hash
        # and send the prefix). If we ever change that boundary, the
        # k-anonymity guarantee breaks — test ratchets it down.
        assert calls == [candidate]

    async def test_skips_breach_check_when_too_short(self, monkeypatch):
        """Cheap local checks fire first — a short password must never
        cause a network call, which would otherwise leak information
        and waste latency."""
        called = False

        async def _breached(_pw: str) -> bool:
            nonlocal called
            called = True
            return True

        monkeypatch.setattr(hibp, "is_password_breached", _breached)

        with pytest.raises(PasswordPolicyError):
            await validate_new_password("short")
        assert called is False


@pytest.mark.unit
class TestEnforcePasswordPolicy:
    async def test_raises_http_422_on_policy_failure(self):
        with pytest.raises(HTTPException) as excinfo:
            await enforce_password_policy("short")
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == PasswordMessages.TOO_SHORT

    async def test_returns_silently_on_valid_password(self, monkeypatch):
        async def _not_breached(_pw: str) -> bool:
            return False

        monkeypatch.setattr(hibp, "is_password_breached", _not_breached)
        await enforce_password_policy("a" * PASSWORD_MIN_LENGTH)
