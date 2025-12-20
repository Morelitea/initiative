"""
Unit tests for guild service functions.

Tests the business logic in app.services.guilds including:
- Guild creation and management
- Membership management
- Invite generation and redemption
- Guild resolution and permissions
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import Guild, GuildInvite, GuildMembership, GuildRole
from app.services import guilds as guild_service
from tests.factories import create_guild, create_guild_membership, create_user


@pytest.mark.unit
@pytest.mark.service
async def test_get_primary_guild_creates_if_missing(session: AsyncSession):
    """Test that primary guild is created if none exists."""
    guild = await guild_service.get_primary_guild(session)

    assert guild.id is not None
    assert guild.name == "Primary Guild"
    assert guild.description == "Default guild"


@pytest.mark.unit
@pytest.mark.service
async def test_get_primary_guild_returns_existing(session: AsyncSession):
    """Test that existing guild is returned as primary."""
    # Create a guild first
    first_guild = await create_guild(session, name="First Guild")

    # Get primary guild should return this one
    primary = await guild_service.get_primary_guild(session)

    assert primary.id == first_guild.id
    assert primary.name == "First Guild"


@pytest.mark.unit
@pytest.mark.service
async def test_get_guild_by_id(session: AsyncSession):
    """Test retrieving a guild by ID."""
    guild = await create_guild(session, name="Test Guild")

    retrieved = await guild_service.get_guild(session, guild_id=guild.id)

    assert retrieved.id == guild.id
    assert retrieved.name == "Test Guild"


@pytest.mark.unit
@pytest.mark.service
async def test_get_guild_not_found(session: AsyncSession):
    """Test that getting nonexistent guild raises error."""
    with pytest.raises(ValueError, match="Guild not found"):
        await guild_service.get_guild(session, guild_id=99999)


@pytest.mark.unit
@pytest.mark.service
async def test_create_guild(session: AsyncSession):
    """Test creating a new guild."""
    creator = await create_user(session, email="creator@example.com")

    guild = await guild_service.create_guild(
        session,
        name="New Guild",
        description="A test guild",
        creator=creator,
    )

    assert guild.id is not None
    assert guild.name == "New Guild"
    assert guild.description == "A test guild"
    assert guild.created_by_user_id == creator.id


@pytest.mark.unit
@pytest.mark.service
async def test_create_guild_creates_admin_membership(session: AsyncSession):
    """Test that creating a guild makes the creator an admin."""
    creator = await create_user(session, email="creator@example.com")

    guild = await guild_service.create_guild(
        session,
        name="New Guild",
        creator=creator,
    )

    # Check membership was created
    membership = await guild_service.get_membership(
        session,
        guild_id=guild.id,
        user_id=creator.id,
    )

    assert membership is not None
    assert membership.role == GuildRole.admin


@pytest.mark.unit
@pytest.mark.service
async def test_ensure_membership_creates_new(session: AsyncSession):
    """Test that ensure_membership creates a new membership if none exists."""
    user = await create_user(session)
    guild = await create_guild(session)

    membership = await guild_service.ensure_membership(
        session,
        guild_id=guild.id,
        user_id=user.id,
        role=GuildRole.member,
    )

    assert membership.guild_id == guild.id
    assert membership.user_id == user.id
    assert membership.role == GuildRole.member


@pytest.mark.unit
@pytest.mark.service
async def test_ensure_membership_returns_existing(session: AsyncSession):
    """Test that ensure_membership returns existing membership."""
    user = await create_user(session)
    guild = await create_guild(session)

    # Create membership first
    first = await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=GuildRole.member,
    )

    # Ensure membership should return the same one
    second = await guild_service.ensure_membership(
        session,
        guild_id=guild.id,
        user_id=user.id,
        role=GuildRole.admin,  # Different role, but should not change without force_role
    )

    assert second.guild_id == first.guild_id
    assert second.user_id == first.user_id
    assert second.role == GuildRole.member  # Should still be member


@pytest.mark.unit
@pytest.mark.service
async def test_ensure_membership_force_role_updates(session: AsyncSession):
    """Test that force_role updates an existing membership's role."""
    user = await create_user(session)
    guild = await create_guild(session)

    # Create as member
    await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=GuildRole.member,
    )

    # Force upgrade to admin
    membership = await guild_service.ensure_membership(
        session,
        guild_id=guild.id,
        user_id=user.id,
        role=GuildRole.admin,
        force_role=True,
    )

    assert membership.role == GuildRole.admin


@pytest.mark.unit
@pytest.mark.service
async def test_resolve_user_guild_id_from_header(session: AsyncSession):
    """Test that explicit guild_id takes precedence."""
    user = await create_user(session)
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    # Explicit guild_id should be used
    resolved = await guild_service.resolve_user_guild_id(
        session,
        user=user,
        guild_id=guild2.id,
    )

    assert resolved == guild2.id


@pytest.mark.unit
@pytest.mark.service
async def test_resolve_user_guild_id_from_active_guild(session: AsyncSession):
    """Test that active_guild_id is used when no explicit guild_id."""
    user = await create_user(session)
    guild1 = await create_guild(session)
    guild2 = await create_guild(session)

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    # Set active guild
    user.active_guild_id = guild2.id
    session.add(user)
    await session.commit()

    resolved = await guild_service.resolve_user_guild_id(
        session,
        user=user,
        guild_id=None,
    )

    assert resolved == guild2.id


@pytest.mark.unit
@pytest.mark.service
async def test_list_memberships(session: AsyncSession):
    """Test listing all memberships for a user."""
    user = await create_user(session)
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    memberships = await guild_service.list_memberships(session, user_id=user.id)

    assert len(memberships) == 2
    guild_names = {guild.name for guild, _membership in memberships}
    assert "Guild 1" in guild_names
    assert "Guild 2" in guild_names


@pytest.mark.unit
@pytest.mark.service
async def test_reorder_memberships(session: AsyncSession):
    """Test reordering user's guild memberships."""
    user = await create_user(session)
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    guild3 = await create_guild(session, name="Guild 3")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)
    await create_guild_membership(session, user=user, guild=guild3)

    # Reorder: guild3, guild1, guild2
    await guild_service.reorder_memberships(
        session,
        user_id=user.id,
        ordered_guild_ids=[guild3.id, guild1.id, guild2.id],
    )

    # Verify order
    memberships = await guild_service.list_memberships(session, user_id=user.id)
    ordered_ids = [guild.id for guild, _membership in memberships]

    assert ordered_ids == [guild3.id, guild1.id, guild2.id]


@pytest.mark.unit
@pytest.mark.service
async def test_create_guild_invite(session: AsyncSession):
    """Test creating a guild invite."""
    creator = await create_user(session, email="creator@example.com")
    guild = await create_guild(session, creator=creator)

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=creator.id,
        invitee_email="invitee@example.com",
        max_uses=1,
        expires_at=None,
    )

    assert invite.id is not None
    assert invite.guild_id == guild.id
    assert invite.created_by_user_id == creator.id
    assert invite.invitee_email == "invitee@example.com"
    assert invite.max_uses == 1
    assert invite.uses == 0
    assert len(invite.code) == 32  # 16 bytes as hex


@pytest.mark.unit
@pytest.mark.service
async def test_invite_code_is_unique(session: AsyncSession):
    """Test that invite codes are unique."""
    guild = await create_guild(session)
    user = await create_user(session)

    invite1 = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=user.id,
    )
    invite2 = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=user.id,
    )

    assert invite1.code != invite2.code


@pytest.mark.unit
@pytest.mark.service
async def test_invite_is_active_valid(session: AsyncSession):
    """Test that invite_is_active returns True for valid invite."""
    guild = await create_guild(session)
    user = await create_user(session)

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=user.id,
        max_uses=5,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    assert guild_service.invite_is_active(invite) is True


@pytest.mark.unit
@pytest.mark.service
async def test_invite_is_active_expired(session: AsyncSession):
    """Test that invite_is_active returns False for expired invite."""
    guild = await create_guild(session)
    user = await create_user(session)

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
    )

    assert guild_service.invite_is_active(invite) is False


@pytest.mark.unit
@pytest.mark.service
async def test_invite_is_active_max_uses_exceeded(session: AsyncSession):
    """Test that invite_is_active returns False when max uses exceeded."""
    guild = await create_guild(session)
    user = await create_user(session)

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=user.id,
        max_uses=1,
    )

    # Manually set uses to exceed max
    invite.uses = 1
    session.add(invite)
    await session.commit()

    assert guild_service.invite_is_active(invite) is False


@pytest.mark.unit
@pytest.mark.service
async def test_redeem_invite_for_user(session: AsyncSession):
    """Test redeeming an invite code for a user."""
    guild = await create_guild(session, name="Test Guild")
    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")

    # Create invite
    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=creator.id,
        max_uses=5,
    )

    # Redeem invite
    redeemed_guild = await guild_service.redeem_invite_for_user(
        session,
        code=invite.code,
        user=invitee,
        promote_to_active=False,
    )

    assert redeemed_guild.id == guild.id

    # Check membership was created
    membership = await guild_service.get_membership(
        session,
        guild_id=guild.id,
        user_id=invitee.id,
    )
    assert membership is not None
    assert membership.role == GuildRole.member

    # Check invite use count increased
    stmt = select(GuildInvite).where(GuildInvite.id == invite.id)
    result = await session.exec(stmt)
    updated_invite = result.one()
    assert updated_invite.uses == 1


@pytest.mark.unit
@pytest.mark.service
async def test_redeem_invite_promotes_to_active(session: AsyncSession):
    """Test that redeeming invite can promote guild to active."""
    guild = await create_guild(session)
    creator = await create_user(session)
    invitee = await create_user(session, email="invitee@example.com")

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=creator.id,
    )

    await guild_service.redeem_invite_for_user(
        session,
        code=invite.code,
        user=invitee,
        promote_to_active=True,
    )

    # Refresh user and check active_guild_id
    await session.refresh(invitee)
    assert invitee.active_guild_id == guild.id


@pytest.mark.unit
@pytest.mark.service
async def test_redeem_invite_expired_raises_error(session: AsyncSession):
    """Test that redeeming expired invite raises error."""
    guild = await create_guild(session)
    creator = await create_user(session)
    invitee = await create_user(session, email="invitee@example.com")

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=creator.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    with pytest.raises(guild_service.GuildInviteError, match="expired"):
        await guild_service.redeem_invite_for_user(
            session,
            code=invite.code,
            user=invitee,
        )


@pytest.mark.unit
@pytest.mark.service
async def test_delete_guild_invite(session: AsyncSession):
    """Test deleting a guild invite."""
    guild = await create_guild(session)
    creator = await create_user(session)

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        creator_user_id=creator.id,
    )

    await guild_service.delete_guild_invite(
        session,
        guild_id=guild.id,
        invite_id=invite.id,
    )

    # Verify invite is deleted
    stmt = select(GuildInvite).where(GuildInvite.id == invite.id)
    result = await session.exec(stmt)
    deleted_invite = result.one_or_none()
    assert deleted_invite is None
