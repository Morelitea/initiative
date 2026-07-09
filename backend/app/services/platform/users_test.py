"""
Unit tests for user service functions.

Tests the business logic in app.services.users including:
- System user management
- Deletion eligibility checks
- Project ownership transfers
- User content reassignment
"""

from datetime import datetime, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.user import User, UserStatus
from app.services.platform import users as user_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
)


@pytest.mark.unit
@pytest.mark.service
async def test_get_or_create_system_user(session: AsyncSession):
    """Test that system user is created on first call and reused on subsequent calls."""
    # First call should create the system user
    system_user1 = await user_service.get_or_create_system_user(session)

    assert system_user1.id is not None
    assert system_user1.email == user_service.SYSTEM_USER_EMAIL
    assert system_user1.full_name == user_service.SYSTEM_USER_FULL_NAME
    assert system_user1.status == UserStatus.deactivated
    assert system_user1.email_verified is True

    # Second call should return the same user
    system_user2 = await user_service.get_or_create_system_user(session)

    assert system_user2.id == system_user1.id
    assert system_user2.email == system_user1.email

    # Verify only one system user exists
    from app.core.encryption import hash_email

    stmt = select(User).where(
        User.email_hash == hash_email(user_service.SYSTEM_USER_EMAIL)
    )
    result = await session.exec(stmt)
    all_system_users = result.all()
    assert len(all_system_users) == 1


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_true(session: AsyncSession):
    """Test detection when user is the last admin of a guild."""
    # Create a guild with one admin
    admin_user = await create_user(session)
    guild = await create_guild(session, creator=admin_user)
    await create_guild_membership(
        session,
        user=admin_user,
        guild=guild,
        role=GuildRole.admin,
    )

    # Check if user is last admin
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin_user.id)

    assert len(last_admin_guilds) == 1
    assert last_admin_guilds[0] == guild.name


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_false_multiple_admins(session: AsyncSession):
    """Test that user is not considered last admin when other admins exist."""
    # Create a guild with two admins
    admin1 = await create_user(session, email="admin1@example.com")
    admin2 = await create_user(session, email="admin2@example.com")
    guild = await create_guild(session, creator=admin1)

    await create_guild_membership(
        session, user=admin1, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=admin2, guild=guild, role=GuildRole.admin
    )

    # Check if admin1 is last admin (should be False)
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin1.id)

    assert len(last_admin_guilds) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_false_only_member(session: AsyncSession):
    """Test that regular members are not considered as last admin."""
    # Create a guild with an admin and a member
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    # Check if member is last admin (should be False)
    last_admin_guilds = await user_service.is_last_guild_admin(session, member.id)

    assert len(last_admin_guilds) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_multiple_guilds(session: AsyncSession):
    """Test detection across multiple guilds."""
    admin = await create_user(session)

    # Guild 1: admin is last admin
    guild1 = await create_guild(session, name="Guild 1", creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild1, role=GuildRole.admin
    )

    # Guild 2: admin is one of two admins
    other_admin = await create_user(session, email="other@example.com")
    guild2 = await create_guild(session, name="Guild 2", creator=other_admin)
    await create_guild_membership(
        session, user=admin, guild=guild2, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=other_admin, guild=guild2, role=GuildRole.admin
    )

    # Check which guilds admin is last admin of
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin.id)

    assert len(last_admin_guilds) == 1
    assert "Guild 1" in last_admin_guilds
    assert "Guild 2" not in last_admin_guilds


@pytest.mark.unit
@pytest.mark.service
async def test_check_deletion_eligibility_can_delete(session: AsyncSession):
    """Test that user can be deleted when they have no blocking conditions."""
    # Create a regular member user
    member = await create_user(session)
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    # Check deletion eligibility
    (
        can_delete,
        blockers,
        _warnings,
        owned_projects,
    ) = await user_service.check_deletion_eligibility(
        session,
        member.id,
    )

    assert can_delete is True
    assert len(blockers) == 0
    assert len(owned_projects) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_check_deletion_eligibility_blocked_last_admin(session: AsyncSession):
    """Test that user cannot be deleted when they are last admin of a guild."""
    # Create a guild where user is the only admin
    admin = await create_user(session)
    guild = await create_guild(session, name="My Guild", creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    # Check deletion eligibility
    (
        can_delete,
        blockers,
        _warnings,
        _owned_projects,
    ) = await user_service.check_deletion_eligibility(
        session,
        admin.id,
    )

    assert can_delete is False
    assert len(blockers) >= 1
    assert any("My Guild" in blocker for blocker in blockers)
    assert any("last admin" in blocker.lower() for blocker in blockers)


@pytest.mark.unit
@pytest.mark.service
async def test_deactivate_user(session: AsyncSession):
    """Deactivation flips status, drops memberships, bumps token_version,
    and leaves PII intact so an admin can later reactivate."""
    user = await create_user(
        session, email="todeactivate@example.com", full_name="Original Name"
    )
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    original_token_version = user.token_version

    await user_service.deactivate_user(session, user.id)

    stmt = select(User).where(User.id == user.id)
    result = await session.exec(stmt)
    deactivated = result.one()

    assert deactivated.status == UserStatus.deactivated
    assert deactivated.token_version == original_token_version + 1
    # PII preserved — admin can reactivate.
    assert deactivated.full_name == "Original Name"
    assert deactivated.email == "todeactivate@example.com"


@pytest.mark.unit
@pytest.mark.service
async def test_soft_delete_user_anonymizes_pii(session: AsyncSession):
    """Soft delete (anonymize) clears PII, blocks login, drops memberships,
    demotes platform admins to member, revokes auth artifacts, and keeps
    the row so historical FKs resolve."""
    from app.models.platform.api_key import UserApiKey
    from app.models.platform.push_token import PushToken
    from app.models.platform.user_token import UserToken
    from app.models.platform.user import UserRole

    user = await create_user(
        session,
        email="toanonymize@example.com",
        full_name="Anonymizer Test",
        avatar_url="https://example.com/avatar.png",
        role=UserRole.admin,
    )
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )

    # Seed auth artifacts that should be revoked.
    session.add(
        UserApiKey(
            user_id=user.id,
            name="key",
            token_prefix="ppk_xxxx",
            token_hash="hash-1",
        )
    )
    session.add(
        UserToken(
            user_id=user.id,
            token="utoken-1",
            purpose="password_reset",
            expires_at=datetime.now(timezone.utc),
        )
    )
    session.add(PushToken(user_id=user.id, push_token="device-token", platform="web"))
    await session.commit()

    original_id = user.id
    original_token_version = user.token_version
    original_email_hash = user.email_hash

    await user_service.soft_delete_user(session, user.id)

    stmt = select(User).where(User.id == original_id)
    result = await session.exec(stmt)
    anonymized = result.one()

    # The row stays — same id, same created_at — so FKs resolve.
    assert anonymized.id == original_id
    assert anonymized.status == UserStatus.anonymized
    # Platform-admin role demoted to member so the husk doesn't carry
    # elevated privileges.
    assert anonymized.role == UserRole.member
    # PII gone.
    assert anonymized.full_name is None
    assert anonymized.avatar_url is None
    assert anonymized.avatar_base64 is None
    assert anonymized.oidc_sub is None
    assert anonymized.email_hash != original_email_hash
    # Login is doubly impossible: the email_hash no longer matches the
    # user's old email, and the password hash is fresh nonsense.
    assert anonymized.email != "toanonymize@example.com"
    # Token version bumped (deactivate already bumped, anonymize keeps it).
    assert anonymized.token_version >= original_token_version + 1

    # Auth artifacts revoked.
    api_keys = (
        await session.exec(select(UserApiKey).where(UserApiKey.user_id == original_id))
    ).all()
    user_tokens_left = (
        await session.exec(select(UserToken).where(UserToken.user_id == original_id))
    ).all()
    push_tokens_left = (
        await session.exec(select(PushToken).where(PushToken.user_id == original_id))
    ).all()
    assert api_keys == []
    assert user_tokens_left == []
    assert push_tokens_left == []


@pytest.mark.unit
@pytest.mark.service
async def test_soft_delete_user_scrubs_addressed_invites(session: AsyncSession):
    """Anonymizing a user must erase their address from any guild invite bound
    to it — a lingering invite otherwise keeps a reversible copy of the very
    email the erasure was meant to remove. The matched invite is also
    neutralised so nulling its bound address can't demote a single-recipient
    invite into an open shareable link. Invites for other people, and unbound
    (shareable-link) invites, are left untouched."""
    from app.models.platform.guild import GuildInvite
    from app.services.platform import guilds as guild_service

    victim = await create_user(session, email="scrubme@example.com")
    admin = await create_user(session, email="inviteadmin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=victim, guild=guild, role=GuildRole.member
    )

    # Active invite addressed to the victim — the recoverable PII trace.
    victim_invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=admin.id,
        invitee_email="scrubme@example.com",
        max_uses=1,
        expires_at=None,
    )
    # Invite for someone else — must be untouched.
    other_invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=admin.id,
        invitee_email="keep@example.com",
        max_uses=1,
        expires_at=None,
    )
    # Unbound shareable link (no address) — must be untouched.
    open_invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=admin.id,
        invitee_email=None,
        max_uses=5,
        expires_at=None,
    )
    victim_invite_id = victim_invite.id
    other_invite_id = other_invite.id
    open_invite_id = open_invite.id

    # Sanity: the victim's invite is active/bound before erasure.
    assert guild_service.invite_is_active(victim_invite) is True

    await user_service.soft_delete_user(session, victim.id)
    session.expunge_all()

    scrubbed = (
        await session.exec(
            select(GuildInvite).where(GuildInvite.id == victim_invite_id)
        )
    ).one()
    # Address erased, and the invite neutralised so it can't act as an open link.
    assert scrubbed.invitee_email_encrypted is None
    assert scrubbed.invitee_email is None
    assert scrubbed.max_uses == 0
    assert guild_service.invite_is_active(scrubbed) is False

    # Someone else's invite is untouched.
    other_after = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == other_invite_id))
    ).one()
    assert other_after.invitee_email == "keep@example.com"
    assert other_after.max_uses == 1

    # Unbound shareable-link invites are untouched.
    open_after = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == open_invite_id))
    ).one()
    assert open_after.invitee_email is None
    assert open_after.max_uses == 5


@pytest.mark.integration
@pytest.mark.service
async def test_hard_delete_user_scrubs_addressed_invites(session: AsyncSession):
    """Hard delete has the same residual-PII gap: an invite addressed to the
    removed user keeps a reversible copy of their email. The invitee address
    must be scrubbed — distinct from the ``created_by_user_id`` NULLing, which
    only covers invites the user *sent* (here the inviter is a different
    admin, so only the invitee-scrub can clear it)."""
    from app.models.platform.guild import GuildInvite
    from app.services.platform import guilds as guild_service

    victim = await create_user(session, email="hardscrub@example.com")
    admin = await create_user(session, email="hardadmin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=victim, guild=guild, role=GuildRole.member
    )

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=admin.id,
        invitee_email="hardscrub@example.com",
        max_uses=1,
        expires_at=None,
    )
    invite_id = invite.id
    victim_id = victim.id

    await user_service.hard_delete_user(session, victim_id, {})
    session.expunge_all()

    # User row is gone...
    assert (
        await session.exec(select(User).where(User.id == victim_id))
    ).one_or_none() is None
    # ...and no invite retains their recoverable address.
    scrubbed = (
        await session.exec(select(GuildInvite).where(GuildInvite.id == invite_id))
    ).one()
    assert scrubbed.invitee_email_encrypted is None
    assert scrubbed.invitee_email is None
    # ...and it's neutralised so nulling the bound address can't leave it as an
    # open shareable link.
    assert scrubbed.max_uses == 0
    assert guild_service.invite_is_active(scrubbed) is False


@pytest.mark.unit
@pytest.mark.service
async def test_users_table_has_rls_delete_deny_policy(session: AsyncSession):
    """The migration must enable RLS on `users` and install the
    ``users_no_delete`` restrictive policy that blocks DELETE for any
    non-bypass session. Application code that tries to drop a user row
    via the regular ``app_user`` role would silently affect zero rows
    without this policy.

    Phase 2 (migration 0109) replaced the single wide-open ``users_open``
    policy with per-tier least-privilege policies; this also asserts that
    decomposition (open policy gone, floors + tier policies present)."""
    from sqlalchemy import text

    rls_enabled = await session.exec(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'users'"
        )
    )
    enabled, forced = rls_enabled.one()
    assert enabled is True
    assert forced is True

    policies = await session.exec(
        text(
            "SELECT polname, polcmd, polpermissive FROM pg_policy "
            "WHERE polrelid = 'users'::regclass ORDER BY polname"
        )
    )
    rows = list(policies)
    names = {row[0] for row in rows}
    assert "users_no_delete" in names
    # Phase 2 decomposed the broad open policy into per-tier policies.
    assert "users_open" not in names
    assert {
        "users_app_floor",
        "users_guild_floor",
        "users_platform_self",
        "users_platform_read",
        "users_platform_manage",
    } <= names
    deny_policy = next(row for row in rows if row[0] == "users_no_delete")
    # polcmd '6' = DELETE; polpermissive False = restrictive.
    # See: https://www.postgresql.org/docs/current/catalog-pg-policy.html
    assert deny_policy[2] is False  # restrictive


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_platform_admin_ignores_inactive_targets(session: AsyncSession):
    """An owner whose status isn't ``active`` doesn't contribute to the
    active config-manager count, so they can never be "the last owner".

    ``is_last_platform_admin`` now tracks holders of ``config.manage``
    (owners) — the invariant that keeps the platform able to manage its own
    configuration.
    """
    from app.models.platform.user import UserRole

    active_owner = await create_user(
        session, email="active-owner@example.com", role=UserRole.owner
    )
    deact_owner = await create_user(
        session, email="deact-owner@example.com", role=UserRole.owner
    )
    await user_service.deactivate_user(session, deact_owner.id)

    # The active owner really is the last *active* config manager.
    assert await user_service.is_last_platform_admin(session, active_owner.id) is True

    # The deactivated owner is never "the last owner" — they're not in
    # the count to begin with, so removing them changes nothing.
    assert await user_service.is_last_platform_admin(session, deact_owner.id) is False


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_platform_admin_with_other_active_owner(session: AsyncSession):
    """When a second active owner exists, neither is the last owner."""
    from app.models.platform.user import UserRole

    a = await create_user(session, email="a@example.com", role=UserRole.owner)
    b = await create_user(session, email="b@example.com", role=UserRole.owner)

    assert await user_service.is_last_platform_admin(session, a.id) is False
    assert await user_service.is_last_platform_admin(session, b.id) is False


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_platform_admin_excludes_plain_admin(session: AsyncSession):
    """A plain ``admin`` no longer holds ``config.manage``, so they're not
    counted as a config manager and are never "the last owner"."""
    from app.models.platform.user import UserRole

    await create_user(session, email="owner@example.com", role=UserRole.owner)
    plain_admin = await create_user(
        session, email="admin@example.com", role=UserRole.admin
    )

    assert await user_service.is_last_platform_admin(session, plain_admin.id) is False


@pytest.mark.unit
@pytest.mark.service
async def test_transfer_project_ownership_drops_previous_owners_permission_row(
    session: AsyncSession,
):
    """Transferring ownership has to drop the departing owner's
    ``ProjectPermission`` row. Otherwise that user keeps a stale
    ``level=owner`` row which, after a reactivation + readd cycle,
    leaves the project with two "owners" and a broken access
    dropdown that can't reconcile its value.
    """
    from app.models.tenant.resource_grant import ResourceGrant
    from app.testing.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    successor = await create_user(session, email="successor@example.com")
    departing = await create_user(session, email="departing@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=successor, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=departing, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=admin)
    project = await create_project(session, initiative=initiative, owner=departing)

    # Sanity: project factory grants the creator an owner-level
    # ProjectPermission.
    pre = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "project",
                ResourceGrant.resource_id == project.id,
                ResourceGrant.user_id == departing.id,
            )
        )
    ).one()
    assert pre is not None

    await user_service.transfer_project_ownership(session, project.id, successor.id)
    await session.commit()

    # Departing owner's row is gone.
    assert (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "project",
                ResourceGrant.resource_id == project.id,
                ResourceGrant.user_id == departing.id,
            )
        )
    ).one_or_none() is None

    # Successor has owner-level permission.
    successor_perm = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "project",
                ResourceGrant.resource_id == project.id,
                ResourceGrant.user_id == successor.id,
            )
        )
    ).one()
    assert successor_perm.level == "owner"


@pytest.mark.unit
@pytest.mark.service
async def test_reassign_user_content_moves_file_version_uploads(session: AsyncSession):
    """reassign_user_content must move document_file_versions.uploaded_by_id to
    the system user so hard-deleting an uploader doesn't violate the RESTRICT FK
    (and version history outlives the user)."""
    from app.models.tenant.document import Document, DocumentFileVersion, DocumentType
    from app.testing.factories import create_initiative

    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, owner)

    doc = Document(
        title="Versioned",
        initiative_id=initiative.id,
        guild_id=guild.id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.file,
        file_url="/uploads/v1.pdf",
        file_content_type="application/pdf",
        file_size=10,
        original_filename="v1.pdf",
    )
    session.add(doc)
    await session.flush()
    version = DocumentFileVersion(
        document_id=doc.id,
        guild_id=guild.id,
        version_number=1,
        file_url="/uploads/v1.pdf",
        file_content_type="application/pdf",
        file_size=10,
        original_filename="v1.pdf",
        uploaded_by_id=owner.id,
    )
    session.add(version)
    await session.commit()

    system_user = await user_service.get_or_create_system_user(session)
    await user_service.reassign_user_content(session, owner.id, system_user.id)
    await session.commit()

    refreshed = (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.id == version.id)
        )
    ).one()
    assert refreshed.uploaded_by_id == system_user.id


@pytest.mark.integration
async def test_soft_delete_removes_membership_in_guild_schema(session: AsyncSession):
    """Production-faithful routing check (schema-per-guild).

    The membership-drop cascade must operate on the GUILD schema where the
    rows actually live — not the frozen ``public`` backup. Factories write the
    InitiativeMember into ``guild_<id>`` (via the test routing harness), and
    soft_delete resets the session to ``public`` on the way out (as a real
    request would). So this asserts by EXPLICITLY re-routing into the guild
    schema afterwards: if the cascade had run unrouted against ``public``, the
    guild-schema row would still be here and this would fail."""
    from app.db.session import set_rls_context
    from app.models.tenant.initiative import InitiativeMember
    from app.testing.factories import create_initiative, create_initiative_member

    creator = await create_user(session, email="guild-creator@example.com")
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)

    member = await create_user(session, email="departing-member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative=initiative, user=member)

    # Sanity: the membership exists in the guild schema before deletion.
    await set_rls_context(session, guild_id=guild.id, guild_role="admin")
    before = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == member.id)
        )
    ).all()
    assert len(before) == 1

    await user_service.soft_delete_user(session, member.id)

    # Re-route into the guild schema and confirm the row is gone THERE.
    session.expunge_all()
    await set_rls_context(session, guild_id=guild.id, guild_role="admin")
    after = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == member.id)
        )
    ).all()
    assert after == []

    # And the user row itself (shared/public) is anonymized.
    await set_rls_context(session)
    refreshed = (await session.exec(select(User).where(User.id == member.id))).one()
    assert refreshed.status == UserStatus.anonymized


@pytest.mark.integration
@pytest.mark.service
async def test_soft_delete_scrubs_embedded_mentions(session: AsyncSession):
    """Anonymizing a user rewrites their display name wherever content embedded
    it as literal text: @-mention markup in comments, Lexical mention nodes in
    documents (with yjs_state cleared), and digest-row name snapshots
    (issue #794)."""
    from app.models.tenant.comment import Comment
    from app.models.tenant.document import Document
    from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
    from app.services.tenant.mention_parser import ANONYMIZED_MENTION_NAME
    from app.testing.factories import (
        create_comment,
        create_document,
        create_initiative,
        create_initiative_member,
        create_project,
        create_task,
    )
    from app.testing.schema_harness import route_session_to_guild

    author = await create_user(session, email="author@example.com")
    victim = await create_user(session, email="victim@example.com", full_name="Vic Tim")
    guild = await create_guild(session, creator=author)
    await create_guild_membership(session, user=victim, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, author)
    task = await create_task(session, project)

    comment = await create_comment(
        session, author, task=task, content=f"ping @[Vic Tim]({victim.id}) thanks"
    )
    document = await create_document(
        session,
        initiative,
        author,
        content={
            "root": {
                "type": "root",
                "children": [
                    {
                        "type": "paragraph",
                        "children": [
                            {
                                "type": "mention",
                                "mentionName": "Vic Tim",
                                "mentionUserId": victim.id,
                                "text": "Vic Tim",
                            }
                        ],
                    }
                ],
            }
        },
        yjs_state=b"stale-state",
    )
    digest = TaskAssignmentDigestItem(
        user_id=author.id,
        task_id=task.id,
        project_id=project.id,
        task_title=task.title,
        project_name=project.name,
        assigned_by_name="Vic Tim",
        assigned_by_id=victim.id,
    )
    session.add(digest)
    await session.commit()
    victim_id = victim.id

    await user_service.soft_delete_user(session, victim_id)

    session.expunge_all()
    await route_session_to_guild(session, guild.id)

    refreshed_comment = (
        await session.exec(select(Comment).where(Comment.id == comment.id))
    ).one()
    assert (
        refreshed_comment.content
        == f"ping @[{ANONYMIZED_MENTION_NAME}]({victim_id}) thanks"
    )

    refreshed_doc = (
        await session.exec(select(Document).where(Document.id == document.id))
    ).one()
    node = refreshed_doc.content["root"]["children"][0]["children"][0]
    assert node["mentionName"] == ANONYMIZED_MENTION_NAME
    assert node["text"] == ANONYMIZED_MENTION_NAME
    assert node["mentionUserId"] == victim_id
    assert refreshed_doc.yjs_state is None

    refreshed_digest = (
        await session.exec(
            select(TaskAssignmentDigestItem).where(
                TaskAssignmentDigestItem.assigned_by_id == victim_id
            )
        )
    ).one()
    assert refreshed_digest.assigned_by_name == ANONYMIZED_MENTION_NAME


@pytest.mark.integration
@pytest.mark.service
async def test_hard_delete_anonymized_user_cleans_guild_data(session: AsyncSession):
    """Hard-deleting an already-anonymized user must still clean their
    guild-scoped rows. Anonymize drops the membership rows, so enumerating
    memberships found no guilds and silently left everything behind
    (issue #794) — the sweep now covers every guild."""
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.task import Task, TaskAssignee
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
        create_project,
        create_task,
    )
    from app.testing.schema_harness import route_session_to_guild

    admin = await create_user(session, email="keeper@example.com")
    victim = await create_user(session, email="husk@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=victim, guild=guild)
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, admin)
    task = await create_task(session, project, assignees=[victim])
    guild_id = guild.id
    victim_id = victim.id
    task_id = task.id

    # Anonymize first — this drops the guild membership rows.
    await user_service.soft_delete_user(session, victim_id)
    session.expunge_all()

    await user_service.hard_delete_user(session, victim_id, {})
    session.expunge_all()

    # The users row is gone.
    remaining_user = (
        await session.exec(select(User).where(User.id == victim_id))
    ).one_or_none()
    assert remaining_user is None

    # And so are their guild-scoped rows, even though they had no
    # membership left at hard-delete time.
    await route_session_to_guild(session, guild_id)
    assignees = (
        await session.exec(
            select(TaskAssignee).where(TaskAssignee.user_id == victim_id)
        )
    ).all()
    assert assignees == []
    grants = (
        await session.exec(
            select(ResourceGrant).where(ResourceGrant.user_id == victim_id)
        )
    ).all()
    assert grants == []
    # The task itself survives.
    assert (
        await session.exec(select(Task).where(Task.id == task_id))
    ).one_or_none() is not None
