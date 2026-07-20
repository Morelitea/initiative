"""The registry service's race guard: a slug collision that slips past the
app-level check and hits the namespace unique constraint at flush must come
back as the promised 409, not an unhandled 500. The window can't be
interleaved deterministically through the API, so the flush is stubbed with
the error shape the constraint produces."""

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.errors import UNIQUE_VIOLATION_SQLSTATE
from app.schemas.platform.settings import AuthProviderCreate
from app.services.auth import provider_registry

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PROVIDER_IN = AuthProviderCreate(
    slug="corp",
    display_name="Corp SSO",
    issuer="https://idp.example.com",
    client_id="corp-client",
)


def _integrity_error(sqlstate: str) -> IntegrityError:
    class _Orig(Exception):
        pass

    orig = _Orig()
    orig.sqlstate = sqlstate
    return IntegrityError("INSERT INTO auth_providers …", None, orig)


async def test_create_race_translates_unique_violation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    async def _raise_unique() -> None:
        raise _integrity_error(UNIQUE_VIOLATION_SQLSTATE)

    monkeypatch.setattr(session, "flush", _raise_unique)

    with pytest.raises(HTTPException) as excinfo:
        await provider_registry.create_provider(session, PROVIDER_IN, guild_id=None)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "AUTH_PROVIDER_SLUG_TAKEN"


async def test_create_reraises_other_integrity_errors(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    async def _raise_fk() -> None:
        raise _integrity_error("23503")

    monkeypatch.setattr(session, "flush", _raise_fk)

    with pytest.raises(IntegrityError):
        await provider_registry.create_provider(session, PROVIDER_IN, guild_id=None)
