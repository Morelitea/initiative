"""Unit tests for app.services.user_tokens (SEC-13).

Covers the at-rest hashing and sliding-window device-token TTL:
- tokens are stored as SHA-256 hashes, never plaintext
- lookups hash the presented value and match the stored hash
- expired / past-TTL tokens are rejected
- device tokens are minted within the 90-day cap
- presenting a near-expiry device token slides its expiry forward
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user_token import UserToken, UserTokenPurpose
from app.services import user_tokens
from app.services.user_tokens import (
    DEVICE_TOKEN_TTL_DAYS,
    _hash_token,
)
from app.testing.factories import create_user


@pytest.mark.unit
@pytest.mark.service
async def test_create_token_stores_hash_not_plaintext(session: AsyncSession):
    """create_token returns the raw token but persists only its SHA-256 hash."""
    user = await create_user(session)
    raw = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    row = (
        await session.exec(select(UserToken).where(UserToken.user_id == user.id))
    ).one()
    assert row.token != raw
    assert row.token == _hash_token(raw)


@pytest.mark.unit
@pytest.mark.service
async def test_get_valid_token_matches_hashed_value(session: AsyncSession):
    """Lookup hashes the presented value and finds the stored hash; a wrong
    token does not match."""
    user = await create_user(session)
    raw = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.email_verification,
    )

    found = await user_tokens.get_valid_token(
        session, token=raw, purpose=UserTokenPurpose.email_verification
    )
    assert found is not None
    assert found.user_id == user.id

    missing = await user_tokens.get_valid_token(
        session, token="not-the-token", purpose=UserTokenPurpose.email_verification
    )
    assert missing is None


@pytest.mark.unit
@pytest.mark.service
async def test_expired_token_rejected(session: AsyncSession):
    """A token whose expires_at is in the past is not returned by lookup."""
    user = await create_user(session)
    raw = "expired-raw-token-value"
    session.add(
        UserToken(
            user_id=user.id,
            token=_hash_token(raw),
            purpose=UserTokenPurpose.password_reset,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await session.commit()

    found = await user_tokens.get_valid_token(
        session, token=raw, purpose=UserTokenPurpose.password_reset
    )
    assert found is None


@pytest.mark.unit
@pytest.mark.service
async def test_create_device_token_stores_hash_and_caps_ttl(session: AsyncSession):
    """New device tokens are stored hashed and expire within the 90-day cap."""
    user = await create_user(session)
    before = datetime.now(timezone.utc)
    raw = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )
    after = datetime.now(timezone.utc)

    row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    assert row.token == _hash_token(raw)
    # Expiry sits at ~now + 90 days, never the legacy ~100-year value.
    assert row.expires_at <= after + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
    assert row.expires_at >= before + timedelta(days=DEVICE_TOKEN_TTL_DAYS - 1)


@pytest.mark.unit
@pytest.mark.service
async def test_get_device_token_matches_hash(session: AsyncSession):
    """Device-token lookup works against the stored hash via get_device_token."""
    user = await create_user(session)
    raw = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )

    found = await user_tokens.get_device_token(session, token=raw)
    assert found is not None
    assert found.user_id == user.id

    assert await user_tokens.get_device_token(session, token="wrong") is None


@pytest.mark.unit
@pytest.mark.service
async def test_device_token_sliding_refresh_extends_expiry(session: AsyncSession):
    """Presenting a near-expiry device token slides its expiry to now + cap."""
    user = await create_user(session)
    raw = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )

    # Force the token close to expiry so the sliding-refresh threshold trips.
    row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    row.expires_at = soon
    session.add(row)
    await session.commit()

    refreshed = await user_tokens.get_device_token(session, token=raw)
    assert refreshed is not None
    # Expiry was pushed well past the original near-expiry value.
    assert refreshed.expires_at > soon + timedelta(days=DEVICE_TOKEN_TTL_DAYS - 1)


@pytest.mark.unit
@pytest.mark.service
async def test_device_token_no_refresh_when_far_from_expiry(session: AsyncSession):
    """A freshly-minted device token (far from expiry) is not rewritten on use."""
    user = await create_user(session)
    raw = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )
    row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    original_expiry = row.expires_at

    refreshed = await user_tokens.get_device_token(session, token=raw)
    assert refreshed is not None
    assert refreshed.expires_at == original_expiry


@pytest.mark.integration
async def test_device_token_slides_after_a_day_of_no_refresh(session: AsyncSession):
    """A token whose last slide is over a day old is re-slid on use — expiry
    tracks last use to within a day, not just within the final day of the cap."""
    user = await create_user(session)
    raw = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )
    row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    # Simulate a token last refreshed two days ago (88 days remaining).
    two_days_in = datetime.now(timezone.utc) + timedelta(
        days=user_tokens.DEVICE_TOKEN_TTL_DAYS - 2
    )
    row.expires_at = two_days_in
    session.add(row)
    await session.commit()

    refreshed = await user_tokens.get_device_token(session, token=raw)
    assert refreshed is not None
    assert refreshed.expires_at > two_days_in + timedelta(days=1)
