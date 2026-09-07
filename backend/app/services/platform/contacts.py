"""What the My Contacts page reads.

Two halves that do not share a source. The **sections** are the rosters of the
reader's own guilds, gathered the way every other ``/me`` aggregate is — one
routed visit per guild, via ``gather_across_guilds``. The **favorites** are
rows of ``public.profile_favorites`` resolved against ``public.user_profiles``,
which needs no guild at all and may name people the reader shares none with.
"""

from typing import Iterable, Optional, Sequence

from sqlalchemy import String, cast, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core import usernames
from app.core.role_context import guild_shows_member_names
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildMembership, GuildStatus
from app.models.platform.guild_image import GuildImageVariant
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user import User, UserStatus
from app.models.platform.user_profile_view import MemberProfile, user_profiles
from app.schemas.platform.contact import (
    ContactGuildSection,
    ContactRead,
    FavoriteContactsResponse,
)
from app.services.cross_guild import gather_across_guilds
from app.services.platform import guild_images as guild_images_service
from app.services.platform import presence as presence_service
from app.services.platform import users as users_service

#: Members per guild section. Small enough that somebody in a dozen guilds gets
#: a sane first response, and every section pages from there.
DEFAULT_PAGE_SIZE = 20

#: ``(guild_id, name, icon_url)`` — one of the reader's guilds, as a section.
GuildRow = tuple[int, str, Optional[str]]


async def ordered_member_guilds(
    session: AsyncSession, *, user_id: int
) -> list[GuildRow]:
    """The reader's guilds in rail order.

    ``GuildMembership.position`` is the order they dragged the rail into, so
    this is the same rule the rail uses rather than a second one. A suspended
    guild is left out, matching ``member_guild_ids`` and the ``/g/{guild_id}``
    path it stands in for.
    """
    await set_rls_context(session, user_id=user_id)
    rows = (
        await session.exec(
            select(Guild.id, Guild.name)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .join(User, User.id == GuildMembership.user_id)
            .where(
                GuildMembership.user_id == user_id,
                Guild.status != GuildStatus.suspended.value,
                User.status != UserStatus.suspended,
            )
            .order_by(col(GuildMembership.position).asc(), col(Guild.id).asc())
        )
    ).all()
    # One query for every section's icon, projected to the digest — a list
    # payload names images rather than carrying them.
    icons = await guild_images_service.image_urls(
        session, [row[0] for row in rows], GuildImageVariant.icon
    )
    return [
        (row[0], row[1], icons.get(row[0], {}).get(GuildImageVariant.icon))
        for row in rows
    ]


def _reads(users: Iterable[MemberProfile]) -> list[ContactRead]:
    """Validate inside the caller's current guild context.

    ``ContactRead`` inherits the guild-name visibility validator, so where this
    runs decides whether ``full_name`` survives.
    """
    reads = []
    for user in users:
        read = ContactRead.model_validate(user)
        read.presence = presence_service.online.presence_of(user.id)
        reads.append(read)
    return reads


async def guild_sections(
    session: AsyncSession,
    *,
    user_id: int,
    guilds: Sequence[GuildRow],
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[ContactGuildSection]:
    """One section per guild, in the order given.

    Each guild is visited in its own routed context, which is what makes both
    reads below possible: ``guild_memberships`` answers for the current guild
    there, and ``full_name`` renders per that guild's own setting.
    """
    if not guilds:
        return []

    # guild_id -> everyone in it, collected while that guild is the current
    # one. Inverted afterwards into "which of the reader's guilds is this
    # person also in", which cannot be derived from the paged rows themselves:
    # a person may be on page 1 of one section and page 3 of another.
    membership_map: dict[int, list[int]] = {}
    sections: dict[int, ContactGuildSection] = {}
    named = {gid: (name, icon) for gid, name, icon in guilds}

    # Who, of each community, this reader may actually reach — asked here, on
    # the platform-tier session, because that is the only role the rule is
    # callable from. It has to happen before the walk below, which routes this
    # same session into each guild in turn.
    listable = await listable_by_guild(
        session, user_id=user_id, guilds=[gid for gid, _n, _i in guilds]
    )

    async def _fetch(guild_session: AsyncSession, guild_id: int) -> list[int]:
        shows_names = guild_shows_member_names()

        # Ids only, unpaginated — an index-only scan of the primary key, which
        # leads with guild_id.
        membership_map[guild_id] = list(
            (
                await guild_session.exec(
                    select(GuildMembership.user_id).where(
                        GuildMembership.guild_id == guild_id,
                        GuildMembership.user_id != user_id,
                    )
                )
            ).all()
        )

        # A community of one is not a section. Nobody is in it to list, and an
        # empty section there would read as a remark about people who are not
        # there — the reader is by themselves, which the page should not
        # dress up as everybody being unreachable.
        if not membership_map[guild_id]:
            return []

        # Read from the guild projection, not from ``users``: this is a roster,
        # and a routed session has no reach into the account row behind it. The
        # predicates below already speak this shape — selecting the account and
        # filtering the projection is what left the two unjoined.
        base = (
            select(MemberProfile)
            .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
            .where(
                GuildMembership.guild_id == guild_id,
                # You are not your own contact.
                MemberProfile.id != user_id,
                users_service.visible_to_other_people(),
                # And a contact is somebody you could actually reach out to.
                col(MemberProfile.id).in_(listable.get(guild_id, set())),
            )
        )
        closest = None
        if search and (term := search.strip()):
            matches, closest = users_service.member_match(term, shows_names=shows_names)
            base = base.where(matches)

        total = (
            await guild_session.exec(select(func.count()).select_from(base.subquery()))
        ).one()

        rows = (
            await guild_session.exec(
                base.order_by(
                    *users_service.member_order(closest, shows_names=shows_names),
                    col(MemberProfile.username).asc(),
                    col(MemberProfile.discriminator).asc(),
                    col(MemberProfile.id).asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        name, icon = named[guild_id]
        sections[guild_id] = ContactGuildSection(
            guild_id=guild_id,
            guild_name=name,
            icon_url=icon,
            total_count=total,
            items=_reads(rows),
            has_next=page * page_size < total,
        )
        return []

    guild_ids = [gid for gid, _name, _icon in guilds]
    await gather_across_guilds(session, user_id, guild_ids, _fetch)

    shared: dict[int, list[int]] = {}
    for guild_id in guild_ids:
        for member_id in membership_map.get(guild_id, ()):
            shared.setdefault(member_id, []).append(guild_id)

    ordered = [sections[gid] for gid in guild_ids if gid in sections]
    for section in ordered:
        for item in section.items:
            item.shared_guild_ids = shared.get(item.id, [])
    return ordered


async def listable_by_guild(
    session: AsyncSession, *, user_id: int, guilds: Sequence[int]
) -> dict[int, set[int]]:
    """Per community, the members this reader may ask to message.

    One call per section rather than one per member: the rule does the join
    itself, so nothing large crosses the boundary in either direction.

    Deliberately **not** narrowed by who has ignored the reader: an ignore
    governs what arrives, not who is listed, so both rosters stay as they were.
    """
    # The rule reads who is asking from the request context, so this runs on
    # the caller's own session rather than being told an id.
    await set_rls_context(session, user_id=user_id)
    result: dict[int, set[int]] = {}
    for guild_id in guilds:
        rows = await session.exec(
            text("SELECT public.dm_listable_in_guild(:g)").bindparams(g=guild_id)
        )
        result[guild_id] = {row[0] for row in rows}
    return result


async def favorites(
    session: AsyncSession,
    *,
    user_id: int,
    search: Optional[str] = None,
) -> FavoriteContactsResponse:
    """The starred section.

    Read from ``public.user_profiles`` — the view that *is* the public
    projection of an account — so a favorite the reader shares no guild with
    still resolves. That view carries no ``full_name``, a real name being a
    per-guild disclosure rather than a public fact, so a search here matches
    the handle and nothing else.
    """
    stmt = (
        select(
            user_profiles.c.id,
            user_profiles.c.username,
            user_profiles.c.discriminator,
            user_profiles.c.avatar_url,
            user_profiles.c.status,
            user_profiles.c.profile_decorations,
        )
        .join(
            ProfileFavorite,
            ProfileFavorite.favorite_user_id == user_profiles.c.id,
        )
        .where(
            ProfileFavorite.user_id == user_id,
            users_service.visible_to_other_people(user_profiles.c.status),
        )
    )
    if search and (term := search.strip()):
        name_part, number = usernames.parse_handle(term)
        stmt = stmt.where(user_profiles.c.username.ilike(f"%{name_part}%"))
        if number is not None:
            stmt = stmt.where(
                func.lpad(cast(user_profiles.c.discriminator, String), 4, "0").like(
                    f"{number}%"
                )
            )

    rows = (
        await session.exec(
            stmt.order_by(
                func.lower(user_profiles.c.username).asc(),
                user_profiles.c.discriminator.asc(),
            )
        )
    ).all()

    items = [
        ContactRead(
            id=row.id,
            username=row.username,
            discriminator=row.discriminator,
            avatar_url=row.avatar_url,
            status=row.status,
            profile_decorations=row.profile_decorations or {},
            presence=presence_service.online.presence_of(row.id),
        )
        for row in rows
    ]
    return FavoriteContactsResponse(items=items, total_count=len(items))
