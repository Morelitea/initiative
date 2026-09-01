from __future__ import annotations

from datetime import datetime, timezone
from typing import List


from sqlalchemy import func, update
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.core import usernames
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.db.session import set_rls_context
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.guild import GuildMembership, GuildRole
from app.services.auth import identity as identity_service
from app.services.platform import user_avatars as user_avatars_service
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import TaskAssignee
from app.models.platform.notification import Notification
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.project_activity import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref
from app.models.platform.api_key import UserApiKey
from app.models.platform.user_token import UserToken
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem


async def is_last_admin_of_guild(
    session: AsyncSession, guild_id: int, user_id: int, *, for_update: bool = False
) -> bool:
    """
    Check if user is the last admin of a specific guild.

    Args:
        session: Database session
        guild_id: Guild ID to check
        user_id: User ID to check
        for_update: If True, lock the existing admin membership rows so a
            concurrent demotion/removal of a *current* admin can't race this
            check within the same transaction.

    Concurrency caveat: ``for_update`` locks only the admin rows that already
    exist. It does NOT prevent a concurrent transaction from INSERTing a
    brand-new admin membership (a phantom — Postgres row locks aren't predicate
    locks outside SERIALIZABLE). So a caller relying on a True result to gate a
    follow-up mutation has a narrow window where a second admin could appear
    just after the check. Harmless for the current callers (demote-last-admin
    guards, and the blocker-scoped guild delete, which cascades that new row
    away anyway); a caller needing a hard guarantee should take a per-guild
    advisory lock that all admin-mutation paths also honor.
    """
    # Check if user is an admin of this guild
    if for_update:
        membership_stmt = (
            select(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
            .with_for_update()
        )
    else:
        membership_stmt = select(GuildMembership).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id == user_id,
        )
    result = await session.exec(membership_stmt)
    membership = result.one_or_none()

    if not membership or membership.role != GuildRole.admin:
        return False

    # Count all admins in this guild (with lock if for_update)
    if for_update:
        admin_stmt = (
            select(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == GuildRole.admin,
            )
            .with_for_update()
        )
        admin_result = await session.exec(admin_stmt)
        admin_count = len(admin_result.all())
    else:
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.role == GuildRole.admin,
        )
        count_result = await session.exec(count_stmt)
        admin_count = count_result.one()

    return admin_count <= 1


async def is_last_guild_admin(session: AsyncSession, user_id: int) -> List[str]:
    """
    Check if user is the last admin of any guild.
    Returns list of guild names where user is the last admin.
    """
    # Get all guilds where user is an admin
    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.role == GuildRole.admin,
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    last_admin_guild_names = []

    for membership in user_admin_memberships:
        # Count other admins in this guild
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == membership.guild_id,
            GuildMembership.role == GuildRole.admin,
            GuildMembership.user_id != user_id,
        )
        count_result = await session.exec(count_stmt)
        other_admin_count = count_result.one()

        if other_admin_count == 0:
            # User is the last admin, get guild name
            from app.models.platform.guild import Guild

            guild_stmt = select(Guild).where(Guild.id == membership.guild_id)
            guild_result = await session.exec(guild_stmt)
            guild = guild_result.one_or_none()
            if guild:
                last_admin_guild_names.append(guild.name)

    return last_admin_guild_names


async def get_guild_blocker_details(session: AsyncSession, user_id: int) -> List[dict]:
    """
    Get detailed info about guilds where user is the last admin.
    Returns list of dicts with guild_id, guild_name, and other_members who could be promoted.
    """
    from app.models.platform.guild import Guild

    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.role == GuildRole.admin,
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    blockers = []

    for membership in user_admin_memberships:
        # Count other admins in this guild
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == membership.guild_id,
            GuildMembership.role == GuildRole.admin,
            GuildMembership.user_id != user_id,
        )
        count_result = await session.exec(count_stmt)
        other_admin_count = count_result.one()

        if other_admin_count == 0:
            # User is the last admin - get guild info and other members
            guild_stmt = select(Guild).where(Guild.id == membership.guild_id)
            guild_result = await session.exec(guild_stmt)
            guild = guild_result.one_or_none()
            if not guild:
                continue

            # Get other members who could be promoted
            members_stmt = (
                select(User)
                .join(GuildMembership, GuildMembership.user_id == User.id)
                .where(
                    GuildMembership.guild_id == membership.guild_id,
                    GuildMembership.user_id != user_id,
                    User.status == UserStatus.active,
                )
            )
            members_result = await session.exec(members_stmt)
            other_members = members_result.all()

            blockers.append(
                {
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "other_members": other_members,
                }
            )

    return blockers


async def _user_guild_ids(session: AsyncSession, user_id: int) -> List[int]:
    """Guild ids the user belongs to. ``guild_memberships`` is shared/public, so
    this needs no guild routing — it's the entry point for fanning per-guild
    routed reads/writes out across the user's guilds."""
    return list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )


async def check_deletion_eligibility(
    session: AsyncSession,
    user_id: int,
    *,
    admin_context: bool = False,
) -> tuple[bool, List[str]]:
    """
    Check if user can be deleted.
    Returns: (can_delete, blockers)

    The only blocker is being the last admin of a guild. Owning content is not
    one: ownership is released on the way out and the content is left unowned
    for a guild admin to claim, so there is nothing for the departing user to
    decide.

    Args:
        session: Database session
        user_id: ID of the user to check
        admin_context: If True, adjust message wording for admin perspective
    """
    blockers = []

    # Check if user is last admin of any guild
    last_admin_guilds = await is_last_guild_admin(session, user_id)
    if last_admin_guilds:
        for guild_name in last_admin_guilds:
            if admin_context:
                blockers.append(
                    f"User is the last admin of community '{guild_name}'. "
                    f"Another user must be promoted to admin or the community must be deleted first."
                )
            else:
                blockers.append(
                    f"You are the last admin of community '{guild_name}'. "
                    f"Promote another user to admin or delete the community before deleting your account."
                )

    can_delete = len(blockers) == 0

    return can_delete, blockers


async def _drop_user_memberships(session: AsyncSession, user_id: int) -> User:
    """Remove the user from every guild and initiative they belong to,
    handing owned documents off to PMs along the way. Returns the loaded
    ``User`` row but does NOT commit — the caller is responsible for
    issuing exactly one commit so its own status / PII writes land in
    the same transaction as the membership cleanup.

    Splitting the membership work out of ``deactivate_user`` lets
    ``soft_delete_user`` perform PII erasure atomically: a failure
    during anonymization rolls back the membership delete too, instead
    of leaving the user as a half-deactivated row with PII intact.
    """
    from app.services.tenant import initiatives as initiatives_service

    # ``guild_memberships`` is a shared/public table, so this enumerates the
    # user's guilds without needing any guild routing.
    guild_ids = list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )

    # Initiative membership + owned-document handoff is guild-scoped — its rows
    # live in each guild's schema. Route into every guild as superadmin (system
    # cleanup, bypasses RESTRICTIVE policies) before the per-guild work. No
    # commit here: we ``flush`` so the SQL lands in the shared transaction the
    # caller will commit once, preserving the atomicity guarantee. ``expunge_all``
    # between guilds avoids ORM identity-map collisions (ids repeat per schema).
    from app.services.tenant import app_connections as app_connections_service
    from app.services.tenant import app_delegations as app_delegations_service

    for gid in guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, guild_role="admin")
        await initiatives_service.remove_user_from_guild_initiatives(
            session,
            guild_id=gid,
            user_id=user_id,
        )
        # Every app credential this person connected, in every guild they
        # belong to — one sweep rather than a per-guild chore, because losing
        # the account has to end the vendor access it opened. Routed as guild
        # admin, which is what lets the own-row policy admit rows the acting
        # session does not own (an admin removing somebody else's account).
        await app_connections_service.delete_member_connections(
            session, user_id=user_id, reason="account_closed"
        )
        # And every app this person let act as them. An authorization to carry
        # somebody's name has nothing left to mean once the account it named is
        # gone.
        await app_delegations_service.delete_member_delegations(
            session, user_id=user_id
        )
        await session.flush()

    # Back to the public, login-role baseline for the shared-table work: the
    # membership rows themselves and the caller's PII/status writes.
    session.expunge_all()
    await set_rls_context(session)
    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user_id)
        )
    ).all()
    for membership in memberships:
        await session.delete(membership)

    return (await session.exec(select(User).where(User.id == user_id))).one()


async def deactivate_user(session: AsyncSession, user_id: int) -> None:
    """Reversibly deactivate a user account.

    Sets ``status = deactivated``, drops the user from every guild and
    initiative they belong to, and bumps ``token_version`` so any
    outstanding JWTs stop authenticating. PII (name, email, avatar) is
    left intact so the user can be reactivated by an admin later.
    """
    user = await _drop_user_memberships(session, user_id)
    # Owned documents are handed off to other initiative PMs inside
    # ``_drop_user_memberships`` above, before the InitiativeMember
    # rows are dropped.
    user.status = UserStatus.deactivated
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await _dispatch_queued_revocations(session)


async def _scrub_invites_addressed_to(
    session: AsyncSession, *, email_hash: str
) -> None:
    """Erase a user's email from any guild invite addressed to them.

    ``GuildInvite.invitee_email_encrypted`` holds the invited person's address
    as *reversible* Fernet ciphertext, so a lingering (unexpired or already
    consumed) invite is a recoverable PII trace that survives user erasure —
    the one gap that otherwise makes anonymize/hard-delete not airtight.

    Fernet output is non-deterministic (the same address encrypts differently
    every time), so there is no indexed equality lookup: we load every bound
    invite and compare the decrypted address the same way redemption does
    (via ``hash_email``, matching the ``users.email_hash`` normalization).

    A match is NULLed (removing the PII) *and* neutralised (``max_uses = 0``, so
    ``invite_is_active`` returns False). Nulling alone is not enough: an invite
    with no bound address is treated as an open shareable link, so a
    still-active single-recipient invite would degrade into one anyone with the
    code could redeem. The system engine (``app_admin``) holds UPDATE but
    deliberately not DELETE on ``guild_invites`` (row removal rides the guild
    FK cascade — see ``SHARED_TABLE_SYSTEM_GRANTS``), so this scrubs the row in
    place rather than deleting it.
    """
    from app.models.platform.guild import GuildInvite

    bound_invites = (
        await session.exec(
            select(GuildInvite).where(GuildInvite.invitee_email_encrypted.is_not(None))
        )
    ).all()
    for invite in bound_invites:
        bound_email = invite.invitee_email  # decrypts invitee_email_encrypted
        if bound_email and hash_email(bound_email) == email_hash:
            invite.invitee_email_encrypted = None
            invite.max_uses = 0
            session.add(invite)


async def soft_delete_user(session: AsyncSession, user_id: int) -> None:
    """Soft-delete (anonymize) a user account.

    Drops memberships like ``deactivate_user``, then strips every PII
    field on the row, randomises ``email_hash`` / ``email_encrypted`` so
    no future signup or admin lookup can resolve to this row, blanks the
    password hash, and revokes auth artifacts (API keys, push tokens,
    user_tokens). The row stays so existing FKs (comment authors, task
    assignees, project owners, …) continue to resolve and the UI can
    render the placeholder "Deleted user #{id}" wherever the original
    user was referenced.

    The display name is also scrubbed out of content that embedded it as
    literal text — @-mention markup in comments, Lexical mention nodes in
    documents, digest-row name snapshots — in EVERY guild schema (not just
    current memberships: content survives leaving a guild).

    All of this happens inside a single transaction with one commit at
    the end, so a "right to be forgotten" request never ends up in a
    half-applied state — either every change lands or none do.

    This is irreversible — there is no undo.
    """
    import secrets
    from app.models.platform.guild import Guild
    from app.models.platform.push_token import PushToken
    from app.services.tenant.mention_parser import anonymize_user_mentions

    # Mention scrub first — it routes per guild and expunges between guilds,
    # so it must run before the ``user`` row below is loaded and mutated.
    all_guild_ids = list((await session.exec(select(Guild.id))).all())
    for gid in all_guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, guild_role="admin")
        await anonymize_user_mentions(session, user_id=user_id)
        # Drop the user's AI credentials (member API keys) + connection
        # preference in this guild — the encrypted keys are a secret we must not
        # leave behind. The CASCADE FK to public.users is a soft cross-schema ref
        # (dropped in the guild schema), so it never fires; delete explicitly,
        # routed as guild admin so the own-row RLS admits it.
        await session.exec(
            delete(GuildAIMemberKey).where(GuildAIMemberKey.user_id == user_id)
        )
        await session.exec(
            delete(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user_id)
        )
    session.expunge_all()
    await set_rls_context(session)

    user = await _drop_user_memberships(session, user_id)

    # Capture the real email hash before it's overwritten with the sentinel
    # below — it's how we find guild invites bound to this person's address.
    original_email_hash = user.email_hash

    user.status = UserStatus.anonymized
    user.token_version += 1
    # The handle stays — it is a pseudonym and a unique identifier, and what
    # keeps an old thread legible after the person behind it is gone. One that
    # was *assigned* rather than picked was seeded from a first name, so it is
    # replaced with a generated one; a handle its owner chose is theirs to be
    # left holding.
    if not user.username_chosen:
        user.username = usernames.random_name()
        user.discriminator = usernames.random_discriminator()
    # Demote any platform admin to member. The row is now an empty husk
    # that can't act on anything; leaving the admin role on it would be
    # misleading in audit views and would inflate any role-only count
    # that doesn't also filter by status.
    user.role = UserRole.member

    # Replace email with a sentinel that won't collide on the unique index
    # and can't be looked up by anyone trying to authenticate. The
    # encrypted blob holds the same nonsense so decryption (if ever invoked)
    # yields a string that's obviously not a real email. Domain is
    # RFC 2606 example.com so EmailStr serialization on user-facing
    # endpoints (admin user list, etc.) doesn't reject the row.
    sentinel_email = (
        f"anonymized-{user_id}-{secrets.token_hex(8)}@anonymized.example.com"
    )
    user.email_hash = hash_email(sentinel_email)
    user.email_encrypted = encrypt_field(sentinel_email, SALT_EMAIL)

    # No password: a NULL hash never verifies, so the husk cannot authenticate.
    user.hashed_password = None

    # Strip the rest of the PII surface. The IdP subject and refresh token
    # live on the identity links — remove the links themselves.
    await identity_service.delete_user_identities(session, user_id=user_id)
    user.full_name = None
    user.avatar_url = None
    # The picture is a row of its own now, so nulling the column is not enough
    # — the husk must not keep a face.
    await user_avatars_service.delete_avatar(session, user_id=user_id)

    # Reset notification + interface preferences to defaults so the row
    # doesn't leak the user's behavioural profile.
    user.email_initiative_addition = True
    user.email_task_assignment = True
    user.email_project_added = True
    user.email_overdue_tasks = True
    user.email_mentions = True
    user.email_comment_reactions = True
    user.push_initiative_addition = True
    user.push_task_assignment = True
    user.push_project_added = True
    user.push_overdue_tasks = True
    user.push_mentions = True
    user.push_comment_reactions = True

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)

    # Revoke auth artifacts. Whatever short-lived tokens existed are now
    # meaningless because token_version was bumped, but we still drop the
    # rows so they don't sit in the DB attributed to a "Deleted user".
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))

    # Scrub the user's address out of any guild invite bound to it. Without
    # this, an unexpired/lingering invite keeps a recoverable copy of the very
    # email this erasure was meant to remove. Runs in the same public,
    # ``app_admin`` context as the auth-artifact deletes above.
    if original_email_hash:
        await _scrub_invites_addressed_to(session, email_hash=original_email_hash)

    # Single commit: membership removal + PII wipe + auth-artifact
    # revocation either all succeed or all roll back together.
    await session.commit()
    await _dispatch_queued_revocations(session)


async def _dispatch_queued_revocations(session: AsyncSession) -> None:
    """Tell each app that this person's credentials are finished.

    After the commit, always: an app told to let go of a credential the database
    then kept would be the one disagreement worth avoiding. Delivery is
    best-effort — the account is closed either way, and our own delete is the
    authoritative half.
    """
    from app.services.tenant import app_revocation as app_revocation_service

    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )


async def count_capability_holders(
    session: AsyncSession, capability: Capability, *, for_update: bool = False
) -> int:
    """Count active users whose standing role grants ``capability``.

    Args:
        session: Database session
        capability: The platform capability to count holders of
        for_update: If True, lock the matching user rows to prevent race conditions
    """
    roles = list(roles_with_capability(capability))
    if not roles:
        return 0
    if for_update:
        # Lock the matching users to prevent a race when demoting/deleting.
        stmt = (
            select(User)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
            )
            .with_for_update()
        )
        result = await session.exec(stmt)
        return len(result.all())
    stmt = select(func.count(User.id)).where(
        User.role.in_(roles),
        User.status == UserStatus.active,
    )
    result = await session.exec(stmt)
    return result.one()


async def is_last_capability_holder(
    session: AsyncSession,
    user_id: int,
    capability: Capability,
    *,
    for_update: bool = False,
) -> bool:
    """True iff removing this user would leave zero active holders of ``capability``.

    A target whose role doesn't grant the capability, or whose ``status`` isn't
    ``active``, doesn't contribute to the count, so removing them can't drop it
    to zero — return False in those cases. Otherwise count OTHER active holders
    and return True iff none exist.
    """
    roles = list(roles_with_capability(capability))
    if for_update:
        stmt = select(User).where(User.id == user_id).with_for_update()
    else:
        stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or user.role not in roles or user.status != UserStatus.active:
        return False

    # PostgreSQL rejects ``SELECT COUNT(...) FOR UPDATE`` (aggregates
    # can't take row locks), so the for_update path locks the candidate
    # rows themselves and counts them in Python.
    if for_update:
        others_stmt = (
            select(User)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
                User.id != user_id,
            )
            .with_for_update()
        )
        others = (await session.exec(others_stmt)).all()
        return len(others) == 0
    others_stmt = select(func.count(User.id)).where(
        User.role.in_(roles),
        User.status == UserStatus.active,
        User.id != user_id,
    )
    return (await session.exec(others_stmt)).one() == 0


# Backwards-compatible wrappers. The invariant we protect is "can the platform
# still manage its own configuration", i.e. at least one ``owner`` remains
# (``config.manage`` is owner-only).
async def count_platform_admins(
    session: AsyncSession, *, for_update: bool = False
) -> int:
    """Count active users who can manage platform configuration (owners)."""
    return await count_capability_holders(
        session, Capability.CONFIG_MANAGE, for_update=for_update
    )


async def is_last_platform_admin(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> bool:
    """True iff removing this user would leave the platform with no config managers."""
    return await is_last_capability_holder(
        session, user_id, Capability.CONFIG_MANAGE, for_update=for_update
    )


async def hard_delete_user(
    session: AsyncSession,
    user_id: int,
) -> None:
    """
    Permanently delete a user account.

    Ownership and authorship part ways here. ``remove_user_from_guild_initiatives``
    releases the owner grants below, leaving that content unowned for a guild
    admin to claim. Authorship is left exactly where it is: ``created_by`` is a
    weak reference — a plain integer, with no foreign key that fires across the
    schema boundary — so the id stays and the rows keep telling one departed
    author from another. A guild that could once see who did what still can.

    Args:
        session: Database session
        user_id: ID of user to delete
    """
    from app.services.tenant import initiatives as initiatives_service
    from app.services.tenant.mention_parser import anonymize_user_mentions
    from app.models.tenant.queue import QueueItem
    from app.models.platform.push_token import PushToken
    from app.models.tenant.calendar_event import CalendarEventAttendee
    from app.models.platform.guild import Guild, GuildInvite
    from app.models.tenant.property import (
        TaskPropertyValue,
        DocumentPropertyValue,
        CalendarEventPropertyValue,
    )

    # Sweep EVERY guild schema, not just current memberships. An anonymized
    # user has no membership rows left (anonymize drops them), and even an
    # active user's authored content survives leaving a guild — enumerating
    # memberships here silently skipped all of it (issue #794).
    guild_ids = list((await session.exec(select(Guild.id))).all())

    # Phase 1 — guild-scoped cleanup, ROUTED INTO EACH GUILD'S SCHEMA. Every
    # statement below targets a guild-scoped table whose live rows live in
    # ``guild_<id>``; running them on the default (public) context would hit the
    # frozen pre-conversion backup and silently leave the user's content behind
    # in every guild. ``flush`` (not commit) keeps everything in the single
    # transaction committed at the end, so a failure rolls the whole delete back.
    for gid in guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, guild_role="admin")

        # Releases their owner grants (content is left unowned) and drops their
        # memberships.
        await initiatives_service.remove_user_from_guild_initiatives(
            session, guild_id=gid, user_id=user_id
        )

        # Scrub the display name out of content that embedded it as literal
        # text (@-mentions in comments, document mention nodes, digest name
        # snapshots). Already done if the user was anonymized first; direct
        # hard deletes need it here, before the row disappears.
        await anonymize_user_mentions(session, user_id=user_id)

        # Per-user guild-scoped rows with no ON DELETE CASCADE: delete or NULL.
        await session.exec(delete(ProjectOrder).where(ProjectOrder.user_id == user_id))
        await session.exec(
            delete(ProjectFavorite).where(ProjectFavorite.user_id == user_id)
        )
        await session.exec(delete(RecentView).where(RecentView.user_id == user_id))
        # AI credentials (member API keys) + connection preference for this
        # guild. CASCADE to public.users is a soft cross-schema ref (dropped in
        # the guild schema), so it never fires — delete explicitly.
        await session.exec(
            delete(GuildAIMemberKey).where(GuildAIMemberKey.user_id == user_id)
        )
        await session.exec(
            delete(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user_id)
        )
        await session.exec(
            delete(TaskAssignmentDigestItem).where(
                TaskAssignmentDigestItem.user_id == user_id
            )
        )
        await session.exec(
            update(TaskAssignmentDigestItem)
            .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
            .values(assigned_by_id=None)
        )
        # All per-user DAC grants (project, document, queue, counter group,
        # calendar event) live in the polymorphic resource_grants table now;
        # one delete clears every resource type for this user in the schema.
        await session.exec(
            delete(ResourceGrant).where(ResourceGrant.user_id == user_id)
        )
        await session.exec(delete(TaskAssignee).where(TaskAssignee.user_id == user_id))
        # Queue items: assigned-to is nullable, so just clear the pointer.
        await session.exec(
            update(QueueItem).where(QueueItem.user_id == user_id).values(user_id=None)
        )
        await session.exec(
            delete(CalendarEventAttendee).where(
                CalendarEventAttendee.user_id == user_id
            )
        )
        # User-typed custom-property values: NULL the reference (the value rows
        # belong to the entity, not the user).
        for table in (
            TaskPropertyValue,
            DocumentPropertyValue,
            CalendarEventPropertyValue,
        ):
            await session.exec(
                update(table)
                .where(table.value_user_id == user_id)
                .values(value_user_id=None)
            )
        await session.flush()

    # Phase 2 — shared/public cleanup. Reset to the public, login-role baseline
    # so these shared-table writes aren't trapped in the last guild's
    # schema/role (restoring the system engine's BYPASSRLS).
    session.expunge_all()
    await set_rls_context(session)

    await session.exec(delete(Notification).where(Notification.user_id == user_id))
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))

    # Clear nullable creator references on shared guild rows.
    await session.exec(
        update(Guild).where(Guild.created_by == user_id).values(created_by=None)
    )
    await session.exec(
        update(GuildInvite)
        .where(GuildInvite.created_by == user_id)
        .values(created_by=None)
    )

    # GuildMemberships cascade-delete via the User relationship. InitiativeMembers
    # were already removed per guild above.
    user = (await session.exec(select(User).where(User.id == user_id))).one()

    # Scrub the user's address out of any guild invite bound to it before the
    # row goes — a bound invite otherwise keeps a recoverable copy of the email
    # (the ``created_by`` NULLing above only covers invites this user
    # *sent*, not ones addressed *to* them).
    if user.email_hash:
        await _scrub_invites_addressed_to(session, email_hash=user.email_hash)

    await session.delete(user)

    await session.commit()


#: How close a typed name has to be to a member's to be worth offering.
#: Separate from the content-search threshold on purpose: a name is a short
#: string and a title is a sentence, so the two are tuned against different
#: things even where the number happens to agree.
MEMBER_MATCH_THRESHOLD = 0.4


def name_closeness(term: str, *, shows_names: bool):
    """How close a member's name is to what was typed, as a rankable number.

    Measured against the closest RUN of the name rather than the whole of it,
    so a surname matches a member listed by both names. Answers the misspelling
    that substring matching cannot — and its real work is the ORDER, putting the
    nearest name at the top of a page rather than whoever sorts first.

    ``shows_names`` is the guild's own setting, so a real name is matched
    exactly where it is shown and nowhere else.
    """
    closest = func.word_similarity(term, User.username)
    if shows_names:
        closest = func.greatest(
            closest, func.word_similarity(term, func.coalesce(User.full_name, ""))
        )
    return closest


def visible_to_other_people():
    """Rows that may appear where a person is listed as someone to work with.

    A suspended account is not one: it vanishes from rosters, pickers, search,
    mention candidates and presence for as long as the suspension lasts. What
    it does **not** vanish from is work it already touched — a comment it wrote
    still says who wrote it, because suspension is reversible and removes the
    account from nothing.

    A clause rather than a filtered query, so each surface keeps its own
    joins and its own gates and only borrows the predicate.
    """
    return User.status != UserStatus.suspended
