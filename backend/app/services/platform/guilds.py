from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import logging
import secrets

from sqlalchemy import Integer, bindparam, func, or_, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import col, select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.role_context import set_guild_shows_member_names
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.messages import GuildMessages
from app.models.platform.guild import (
    BANNER_TEXT_COLORS,
    DEFAULT_BANNER,
    DEFAULT_BANNER_TEXT_COLOR,
    Guild,
    GuildCategory,
    GuildInvite,
    GuildMembership,
    GuildRole,
    GuildStatus,
)
from app.models.platform.guild_administration import GuildAdministration
from app.models.tenant.guild_setting import GuildSetting
from app.models.platform.user import User
from app.services.platform import billing_ping

from app.services.platform import account_stream
from app.services.platform import contact_grants as contact_grants_service

logger = logging.getLogger(__name__)

DEFAULT_INVITE_EXPIRATION_DAYS = 7
INVITE_CODE_BYTES = 16


class GuildInviteError(Exception):
    """Raised when an invite cannot be redeemed."""


class GuildCapacityError(Exception):
    """Raised when adding a member would exceed the guild's ``max_users`` cap."""


class CommunityJoinError(Exception):
    """Raised when a guild cannot be joined from the community directory."""


class CommunityListingError(Exception):
    """Raised when a guild does not qualify to be listed in the directory."""


class CommunityDirectoryDisabledError(Exception):
    """Raised when the deployment runs no community directory at all."""


class AgeConfirmationRequiredError(Exception):
    """The caller has not confirmed their age and asked to join a listed guild."""


class BannerColorError(Exception):
    """Raised when a banner colour is not a ``#rrggbb`` value."""


# A guild whose seat cap is one can never admit a joiner, so listing it would
# publish a card whose only button is guaranteed to fail. Unlike a guild that is
# merely full today, this one can never have room, which is why it is refused
# outright rather than left to the capacity check at join time.
MIN_COMMUNITY_SEATS = 2


# Canonical order for a guild's categories: the order they are declared in
# ``GuildCategory``. Storing them sorted means every card, filter chip, and
# assertion sees the same sequence regardless of the order they were checked.
_CATEGORY_ORDER = {
    category.value: index for index, category in enumerate(GuildCategory)
}


def normalize_categories(categories: Sequence[str] | None) -> list[str]:
    """De-duplicate a category selection and put it in canonical order.

    Unknown values are dropped rather than rejected: the schema layer has
    already validated the request against ``GuildCategory``, and the database
    CHECK is the backstop, so anything else reaching here is a value this build
    no longer recognizes and simply has no shelf to sit on.
    """
    if not categories:
        return []
    unique = {value for value in categories if value in _CATEGORY_ORDER}
    return sorted(unique, key=lambda value: _CATEGORY_ORDER[value])


async def _persist_new_guild(session: AsyncSession, guild: Guild) -> Guild:
    """Add a new guild row together with the administration row it must have.

    Every guild has exactly one ``guild_administration`` companion, carrying the
    defaults (no caps, no plan, guild sign-in off). Writing the pair here rather
    than at each creation site is what lets every reader assume the row exists —
    ``get_administration`` raises without it, and the operator dashboard joins
    against it. The caller commits.
    """
    session.add(guild)
    await session.flush()
    session.add(GuildAdministration(guild_id=guild.id))
    await session.flush()
    return guild


async def get_primary_guild(session: AsyncSession) -> Guild:
    result = await session.exec(select(Guild).order_by(Guild.id.asc()))
    guild = result.first()
    if guild:
        return guild
    # Zero VISIBLE guilds is either a genuinely fresh database (the designed
    # quiet path: the first boot seeds the primary guild before the first
    # registration, and every registration creates or joins a guild) or a
    # session that cannot see the real rows (wrong DATABASE_URL* target, a
    # blinded system engine). A blinded session reads zero rows in users too,
    # so row counts alone can't tell the two apart — but guild_<id> schemas
    # live in the catalog, which row-level security never filters, and
    # deprovisioning drops a deleted guild's schema. Either signal means this
    # database is NOT fresh: say so before seeding a default guild into what
    # may be a live install.
    user_count = (await session.exec(select(func.count()).select_from(User))).one()
    schema_count = (
        await session.exec(
            text("SELECT count(*) FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'")
        )
    ).one()[0]
    if user_count or schema_count:
        logger.warning(
            "no guilds visible, but the database is not fresh (%d visible "
            "user(s), %d guild schema(s)) — creating a default primary guild. "
            "If this instance previously had guilds, verify the DATABASE_URL* "
            "variables point at the intended database and that the system "
            "engine can read public.guilds",
            user_count,
            schema_count,
        )
    now = datetime.now(timezone.utc)
    guild = await _persist_new_guild(
        session,
        Guild(
            name="Primary Community",
            description="Default community",
            created_at=now,
            updated_at=now,
        ),
    )
    # Commit the new guild row, then provision its schema — a brand-new primary
    # guild is schema-native from birth. (Only the first time the primary guild is
    # created, i.e. fresh-DB seeding.)
    await session.commit()
    from app.db.schema_provisioning import provision_guild

    await provision_guild(guild.id)
    return guild


async def get_primary_guild_id(session: AsyncSession) -> int:
    guild = await get_primary_guild(session)
    return guild.id  # ty: ignore[invalid-return-type]


async def get_guild(session: AsyncSession, guild_id: int) -> Guild:
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await session.exec(stmt)
    guild = result.one_or_none()
    if not guild:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return guild


async def get_administration(
    session: AsyncSession, guild_id: int
) -> GuildAdministration:
    """The guild's operator-set row (caps / plan label / sign-in entitlement).

    Created with the guild, so a missing row means the guild is missing too —
    or that the caller's session cannot see it. The row is readable by the
    guild's own members (RLS scopes it to their guilds) but writable by no
    request-path role; write it on the system engine.
    """
    result = await session.exec(
        select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
    )
    administration = result.one_or_none()
    if not administration:
        raise ValueError(GuildMessages.GUILD_NOT_FOUND)
    return administration


async def ensure_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: GuildRole = GuildRole.member,
    force_role: bool = False,
    oidc_managed: bool = False,
) -> GuildMembership:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        updated = False
        if force_role and membership.role != role:
            membership.role = role
            updated = True
        if oidc_managed and not membership.oidc_managed:
            membership.oidc_managed = True
            updated = True
        if updated:
            session.add(membership)
            await session.flush()
        return membership
    # New member: enforce the per-guild cap. Only reached on a genuine insert
    # (re-joins / role updates return above), so an existing member is never
    # blocked. SSO/OIDC provisioning uses a separate insert path
    # (oidc_sync._create_guild_membership) and is intentionally exempt.
    await _assert_member_capacity(session, guild_id=guild_id)
    next_position = await _next_membership_position(session, user_id=user_id)
    membership = GuildMembership(
        guild_id=guild_id,
        user_id=user_id,
        role=role,
        position=next_position,
        oidc_managed=oidc_managed,
    )
    session.add(membership)
    await session.flush()
    # Belonging somewhere new can change what this account is asked for — a
    # listed community asks its members their age — and the person may have
    # had nothing to do with arriving here. Their open tabs re-read the
    # account once this commits.
    account_stream.queue_account_signal(session, user_id, "membership")
    # Nudge billing that this guild's membership changed. No-op unless a
    # hosted deployment configured the outbound billing settings.
    billing_ping.notify_membership_changed(guild_id)
    await enroll_new_member_in_auto_join_initiatives(
        session, guild_id=guild_id, user_id=user_id, role=role
    )
    return membership


async def enroll_new_member_in_auto_join_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: GuildRole,
) -> None:
    """Put a brand-new guild member into the guild's auto-join initiatives.

    Called on a genuine membership insert only, which is what makes this the
    onboarding hook rather than a sweep: someone who was already in the guild
    is returned earlier and is never re-enrolled.

    A guild admin is skipped. Their membership row is written before the guild's
    schema exists at all — guild creation is the case — and their standing
    already reaches every initiative, so nothing here is theirs to be handed.
    They pick which initiatives they navigate by joining them.

    The initiatives live in the guild's schema and the join paths that reach here
    run on the system engine with ``search_path = public``, so the work is done
    through a routed excursion that hands the session back as it found it. The
    whole excursion sits inside a savepoint: landing somewhere useful is a
    convenience, and it must never be the reason someone's guild join fails.
    """
    if role == GuildRole.admin:
        return
    from app.db.session import guild_schema_context
    from app.services.tenant import initiatives as initiatives_service

    try:
        async with session.begin_nested():
            async with guild_schema_context(session, guild_id=guild_id):
                # A second savepoint so a failure unwinds before the excursion
                # restores the caller's context, rather than during it.
                async with session.begin_nested():
                    await initiatives_service.enroll_in_auto_join_initiatives(
                        session, guild_id=guild_id, user_id=user_id
                    )
    except Exception:
        logger.exception(
            "auto-join: user %s joined guild %s but was enrolled in none of its "
            "auto-join initiatives",
            user_id,
            guild_id,
        )


async def align_admin_initiative_roles(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: GuildRole,
) -> None:
    """Bring a freshly promoted guild admin's initiative rows up to their standing.

    A guild admin's membership row carries a manager role, which every write
    path settles for itself. A promotion changes the guild role and nothing
    else, so the rows the person already held are reconciled here — the one
    moment their standing changes underneath rows that already exist.

    Only a promotion to admin does anything; a demotion leaves the manager role
    in place, which is an ordinary initiative role for an ordinary member to
    hold, and taking it away would be a second decision nobody asked for.

    The initiatives live in the guild's schema and this runs on the system
    engine with ``search_path = public``, so the work is done through a routed
    excursion that hands the session back as it found it. The whole excursion
    sits inside a savepoint: the role change is the thing being asked for, and
    reconciling rows underneath it must never be what makes it fail. Flush-only;
    the caller owns the transaction.
    """
    if role != GuildRole.admin:
        return
    from app.db.session import guild_schema_context
    from app.services.tenant import initiatives as initiatives_service

    try:
        async with session.begin_nested():
            async with guild_schema_context(session, guild_id=guild_id):
                # A second savepoint so a failure unwinds before the excursion
                # restores the caller's context, rather than during it.
                async with session.begin_nested():
                    await initiatives_service.align_guild_admin_membership_roles(
                        session, guild_id=guild_id, user_id=user_id
                    )
    except Exception:
        logger.exception(
            "admin promotion: user %s became an admin of guild %s but their "
            "existing initiative roles were not reconciled",
            user_id,
            guild_id,
        )


# Advisory-lock namespace for per-guild membership-cap admission. A fixed ASCII
# tag ("USER") so the two-int key (namespace, guild_id) can't collide with the
# storage-quota ("STOR") or (user_id, guild_id) advisory locks used elsewhere.
_MEMBER_CAP_LOCK_NAMESPACE = 0x55534552  # 1431193938


async def _assert_member_capacity(
    session: AsyncSession, *, guild_id: int, claiming_seat: bool = True
) -> None:
    """Raise ``GuildCapacityError`` if the guild is at its ``max_users`` cap.

    A ``NULL`` cap means unlimited and short-circuits before any lock or count.
    The caller's session must be able to see the guild's ``guild_memberships``
    rows (system engine, or an RLS context routed to this guild) — the same
    precondition ``count_members`` documents.

    ``claiming_seat`` (the default) is the join path: the call must run in the
    SAME transaction that then inserts the membership and commits, and when a
    cap is set it takes a transaction-scoped advisory lock keyed on the guild
    before counting, so the count check and the insert that follows cannot
    interleave with a concurrent join and collectively exceed the cap. The lock
    releases on commit/rollback and only serializes joins to the SAME guild
    (mirrors ``enforce_storage_quota``).

    Pass ``claiming_seat=False`` when the caller only reads the cap and takes no
    seat in the same transaction (minting an invite): the answer is a
    point-in-time reading either way, so serializing joins against it would buy
    nothing. The join path stays the authoritative gate.
    """
    administration = await get_administration(session, guild_id=guild_id)
    if administration.max_users is None:
        return
    if claiming_seat:
        await session.exec(
            text("SELECT pg_advisory_xact_lock(:ns, :gid)"),
            params={"ns": _MEMBER_CAP_LOCK_NAMESPACE, "gid": int(guild_id)},
        )
    if await count_members(session, guild_id=guild_id) >= administration.max_users:
        raise GuildCapacityError(GuildMessages.GUILD_USER_LIMIT_REACHED)


async def _next_membership_position(session: AsyncSession, *, user_id: int) -> int:
    result = await session.exec(
        select(func.max(GuildMembership.position)).where(
            GuildMembership.user_id == user_id
        )
    )
    max_value = result.one_or_none()
    highest = max_value if max_value is not None else -1
    return highest + 1


async def reorder_memberships(
    session: AsyncSession,
    *,
    user_id: int,
    ordered_guild_ids: list[int],
) -> None:
    if not ordered_guild_ids:
        return

    stmt = select(GuildMembership).where(GuildMembership.user_id == user_id)
    result = await session.exec(stmt)
    memberships = result.all()
    if not memberships:
        return

    membership_by_guild = {
        membership.guild_id: membership for membership in memberships
    }
    seen: set[int] = set()
    final_order: list[int] = []

    # Explicitly named guilds first, in the requested order — deduped, and only
    # ones the user actually belongs to.
    for guild_id in ordered_guild_ids:
        if guild_id in seen or guild_id not in membership_by_guild:
            continue
        final_order.append(guild_id)
        seen.add(guild_id)

    # Memberships the client didn't mention keep their relative order, appended
    # after — stable on current position, then join time.
    remaining = sorted(
        (m for m in memberships if m.guild_id not in seen),
        key=lambda m: (m.position if m.position is not None else 0, m.joined_at),
    )
    final_order.extend(m.guild_id for m in remaining)

    # Persist via the SECURITY DEFINER reorder function. This runs in PERSONAL
    # mode (no guild context) as a platform_<tier> role, which the
    # guild_memberships_update RLS policy rejects (it requires
    # guild_id = current_guild_id), so a direct ORM UPDATE would silently touch 0
    # rows. The function updates ONLY `position`, scoped to this user's own rows —
    # the same safe path for every platform tier.
    await session.exec(
        text("SELECT reorder_guild_memberships(:uid, :gids)").bindparams(
            bindparam("gids", type_=ARRAY(Integer))
        ),
        params={"uid": user_id, "gids": final_order},
    )


async def get_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    for_update: bool = False,
) -> GuildMembership | None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.exec(stmt)
    return result.one_or_none()


async def list_memberships(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[tuple[Guild, GuildMembership, int | None, int, GuildAdministration | None]]:
    """Return (guild, membership, retention_days, member_count, administration)
    for each guild the user belongs to.

    The guild + membership rows are shared (public). ``retention_days`` lives in
    each guild's own schema (``guild_settings``), so it's read per guild with the
    user's membership context — a single cross-guild join would hit the empty
    public table and report NULL for everyone. ``guild_settings.id`` is a
    per-schema serial that collides across schemas, so each settings row is
    detached after reading so a cached row can't shadow the next guild's. It is
    read only where the caller is that guild's admin: retention is one of the
    administration fields ``GuildRead`` withholds from ordinary members, so for
    them it comes back ``None`` and costs no query.

    ``member_count`` is the total number of members in the guild. It's read
    inside the same per-guild loop because the ``guild_memberships_select`` RLS
    policy only exposes sibling rows while that guild's context is active
    (``guild_id = current_guild_id``); under the caller's user-only context a
    cross-guild count would see just the user's own row.

    ``administration`` (caps + plan label + sign-in entitlement) is read on the
    same admin-only terms as retention, and for the same reason: ``GuildRead``
    serves those fields to guild admins alone, so a member's request never pays
    for the row."""
    from app.db.session import set_rls_context  # lazy: avoids a circular import

    await set_rls_context(session, user_id=user_id)
    pairs = (
        await session.exec(
            select(Guild, GuildMembership)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == user_id)
            .order_by(
                GuildMembership.position.asc(),
                GuildMembership.joined_at.asc(),
                Guild.id.asc(),
            )
        )
    ).all()

    out: list[
        tuple[Guild, GuildMembership, int | None, int, GuildAdministration | None]
    ] = []
    for guild, membership in pairs:
        # A suspended guild disappears from its members' guild list; guild
        # ADMINS keep the entry so they can still reach the settings surface
        # (billing / data ownership / danger zone stay theirs under any
        # status). No status is serialized either way — the row is simply
        # absent for members.
        if (
            guild.status == GuildStatus.suspended.value
            and membership.role != GuildRole.admin
        ):
            continue
        await set_rls_context(session, user_id=user_id, guild_id=guild.id)
        retention: int | None = None
        administration: GuildAdministration | None = None
        if membership.role == GuildRole.admin:
            row = (
                await session.exec(
                    select(GuildSetting).where(GuildSetting.guild_id == guild.id)
                )
            ).one_or_none()
            # No row yet → the 90-day default; an explicit NULL is the user's "never".
            retention = 90 if row is None else row.retention_days
            if row is not None:
                session.expunge(row)
            administration = (
                await session.exec(
                    select(GuildAdministration).where(
                        GuildAdministration.guild_id == guild.id
                    )
                )
            ).one_or_none()
        member_count = await count_members(session, guild_id=guild.id)
        out.append((guild, membership, retention, member_count, administration))

    # Restore the user-only context the caller (UserSessionDep) handed us.
    await set_rls_context(session, user_id=user_id)
    return out


async def count_members(session: AsyncSession, *, guild_id: int) -> int:
    """Total number of members in a guild.

    The caller must already hold a session that can see the guild's
    ``guild_memberships`` rows — a system-engine session, or one whose RLS
    context is set to this guild (``guild_id = current_guild_id``). Under a
    user-only context the ``guild_memberships_select`` policy would expose only
    the caller's own row."""
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildMembership)
            .where(GuildMembership.guild_id == guild_id)
        )
    ).one()


async def create_guild_settings(session: AsyncSession, guild_id: int) -> GuildSetting:
    """Seed a guild_settings row. guild_settings is guild-scoped (it holds
    private config like API keys), so under schema-per-guild this must run with
    the session already routed to the guild's schema."""
    settings_row = GuildSetting(guild_id=guild_id, retention_days=90)
    session.add(settings_row)
    await session.flush()
    return settings_row


async def create_guild(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    creator: User | None = None,
    owner: User | None = None,
) -> Guild:
    """Create a guild's *shared* rows only — the guild row (public) and its
    admin membership (public). The guild-scoped seed rows (settings + default
    initiative) live in the guild's schema, which doesn't exist yet, so the
    caller commits this, then calls :func:`seed_guild_content`.

    ``creator`` is who performed the creation and is recorded as such;
    ``owner`` is who gets the admin membership, defaulting to the creator. The
    row therefore says both who made the guild and who it is for.
    """
    now = datetime.now(timezone.utc)
    guild = Guild(
        name=name.strip(),
        description=description.strip()
        if description and description.strip()
        else None,
        created_by=creator.id if creator else None,
        created_at=now,
        updated_at=now,
    )
    await _persist_new_guild(session, guild)
    admin = owner or creator
    if admin:
        await ensure_membership(
            session,
            guild_id=guild.id,
            user_id=admin.id,
            role=GuildRole.admin,
        )
    return guild


async def seed_guild_content(
    session: AsyncSession,
    *,
    guild_id: int,
    owner: User,
) -> None:
    """Provision a new guild's schema and create its guild-scoped seed rows
    (settings + default initiative + the apps this deployment provides) *inside*
    it.

    ``owner`` is the user the guild is **for** — its admin, and the default
    initiative's manager. When someone creates a guild for another account,
    that account is the owner and the creator is left holding nothing in it.

    The shared guild row must already exist; this provisions the schema + role and
    seeds into it (the caller commits around the call). On failure the caller
    should ``deprovision_guild`` and remove the shared rows.

    Mandatory apps (§7.7) land here, beside the default initiative, because that
    is what "every guild has it" means. They are also the one part allowed to
    fail quietly: the install is a local row, and an app service whose listing
    has not arrived yet is no reason a guild cannot be created — the boot sweep
    installs what is missing.
    """
    from app.db.schema_provisioning import provision_guild
    from app.db.session import set_rls_context
    from app.services.tenant import initiatives as initiatives_service
    from app.services.tenant import mandatory_apps as mandatory_apps_service

    await provision_guild(guild_id)
    await set_rls_context(
        session,
        user_id=owner.id,
        guild_id=guild_id,
        guild_role=GuildRole.admin.value,
    )
    await create_guild_settings(session, guild_id)
    await initiatives_service.ensure_default_initiative(
        session, owner, guild_id=guild_id
    )
    try:
        # Inside a savepoint, so a failure here rolls back the app install and
        # nothing else: the guild being created must survive whatever an app's
        # listing or registration is doing.
        async with session.begin_nested():
            await mandatory_apps_service.install_mandatory_apps(
                session, guild_id=guild_id, created_by=owner.id
            )
    except Exception:
        logger.exception(
            "mandatory apps: guild %s was created without them; the boot sweep "
            "installs what is missing",
            guild_id,
        )


#: The characters a hex colour is made of, checked one at a time. An explicit
#: set rather than a pattern: the value ends up inside a style attribute, and
#: "which characters are allowed" should be readable as exactly that.
_HEX_DIGITS = frozenset("0123456789abcdef")


def normalize_banner_text_color(value: str | None) -> str:
    """One of :data:`BANNER_TEXT_COLORS`. Anything else raises.

    Banner text is not a free choice, here or in the UI that sets it: the fill
    behind it is the guild's to pick and its artwork can be anything, so the
    words stay readable only by sitting at one end of the scale or the other.
    """
    candidate = normalize_banner_color(value, fallback=DEFAULT_BANNER_TEXT_COLOR)
    if candidate not in BANNER_TEXT_COLORS:
        raise BannerColorError(GuildMessages.BANNER_TEXT_COLOR_INVALID)
    return candidate


def normalize_banner_color(value: str | None, *, fallback: str) -> str:
    """``#rrggbb`` lowercased. Never None — a banner always has its colours.

    ``None`` and an empty string both mean "back to the default", which is what
    a reset sends. A trailing alpha byte is dropped rather than refused: the
    shared colour picker can emit ``#rrggbbaa``, and a banner is a fill with
    nothing behind it for alpha to mean anything against.
    """
    if value is None:
        return fallback
    candidate = value.strip().lower()
    if not candidate:
        return fallback
    if len(candidate) == 9:
        candidate = candidate[:7]
    if (
        len(candidate) != 7
        or candidate[0] != "#"
        or any(character not in _HEX_DIGITS for character in candidate[1:])
    ):
        raise BannerColorError(GuildMessages.BANNER_COLOR_INVALID)
    return candidate


def normalize_banner(values: Mapping[str, str] | None) -> dict[str, str]:
    """The whole banner, canonical. ``None`` is a reset to the default.

    A banner is never colourless and never without a layout, so there is
    nothing here for "empty" to mean — every key comes back. The layout values
    arrive already inside their vocabularies (the request schema types them as
    the enums), leaving the colours to normalize.
    """
    if values is None:
        return dict(DEFAULT_BANNER)
    return {
        "color": normalize_banner_color(
            values.get("color"), fallback=DEFAULT_BANNER["color"]
        ),
        "text_color": normalize_banner_text_color(values.get("text_color")),
        "text_align": values.get("text_align") or DEFAULT_BANNER["text_align"],
        "fade": values.get("fade") or DEFAULT_BANNER["fade"],
    }


async def update_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str | None = None,
    description: str | None = None,
    retention_days: int | None = None,
    retention_days_provided: bool = False,
    is_community: bool | None = None,
    categories: Sequence[str] | None = None,
    categories_provided: bool = False,
    has_adult_content: bool | None = None,
    has_adult_content_provided: bool = False,
    banner: Mapping[str, str] | None = None,
    banner_provided: bool = False,
    show_member_names: bool | None = None,
    max_storage_bytes: int | None = None,
    max_storage_bytes_provided: bool = False,
    max_users: int | None = None,
    max_users_provided: bool = False,
    guild_auth_enabled: bool | None = None,
    banner_image_enabled: bool | None = None,
) -> Guild:
    guild = await get_guild(session, guild_id=guild_id)
    updated = False
    if name is not None and name.strip() and guild.name != name.strip():
        guild.name = name.strip()
        updated = True
    if description is not None:
        normalized_description = description.strip() or None
        if guild.description != normalized_description:
            guild.description = normalized_description
            updated = True
    if banner_provided:
        normalized_banner = normalize_banner(banner)
        if guild.banner != normalized_banner:
            guild.banner = normalized_banner
            updated = True
    # An explicit ``null`` is meaningless for a boolean opt-in (mirroring
    # ``guild_auth_enabled`` below), so null and omitted alike are a no-op.
    if is_community is not None and guild.is_community != is_community:
        # Only the way in is gated. Un-listing is always available — a guild
        # that opted in while the directory was running must still be able to
        # opt back out after an owner switches it off.
        if is_community:
            await assert_community_directory_enabled(session)
        guild.is_community = is_community
        updated = True
        # Listing a community — or taking it back off the shelf — changes what
        # is asked of everybody already in it, none of whom did anything. The
        # one fan-out this channel has, and it is addressed to the members who
        # are actually here rather than to the whole roster.
        await _signal_members_present(session, guild_id=guild.id)
    if categories_provided:
        normalized = normalize_categories(categories)
        if guild.categories != normalized:
            # Assigned, never mutated in place: SQLAlchemy does not track
            # in-place changes to an ARRAY column, so an ``.append()`` here
            # would flush nothing.
            guild.categories = normalized
            updated = True
    # The one field here where an explicit null is an answer (back to
    # undeclared) rather than "leave it alone", so it reads the provided flag.
    if has_adult_content_provided and guild.has_adult_content != has_adult_content:
        guild.has_adult_content = has_adult_content
        updated = True
    # Checked against the state the guild is ending up in, not against what this
    # PATCH happened to carry: a request that only clears the categories of an
    # already-listed guild has to fail for the same reason as one that lists a
    # guild with none. Two of the three rules are also database CHECKs; this is
    # what turns them into an error a person can read.
    if show_member_names is not None and guild.show_member_names != show_member_names:
        guild.show_member_names = show_member_names
        updated = True
    # Members of a listed guild are known by their handle. Listing one turns
    # names off in the same write rather than refusing the request, so an admin
    # never has to do it in two steps — ck_guilds_community_member_names is what
    # makes it impossible to end up with both.
    if guild.is_community and guild.show_member_names:
        guild.show_member_names = False
        updated = True
    if guild.is_community:
        await _assert_listable(session, guild)
    if updated:
        guild.updated_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.flush()

    # The operator-set fields live on their own row and are writable only on the
    # system engine, so they are applied separately from the identity edits
    # above — a guild admin's PATCH carries none of them, and skipping the whole
    # block spares that path a query it would never use.
    if (
        max_storage_bytes_provided
        or max_users_provided
        or guild_auth_enabled is not None
        or banner_image_enabled is not None
    ):
        administration_updated = False
        administration = await get_administration(session, guild_id=guild_id)
        if (
            max_storage_bytes_provided
            and administration.max_storage_bytes != max_storage_bytes
        ):
            administration.max_storage_bytes = max_storage_bytes
            administration_updated = True
        if max_users_provided and administration.max_users != max_users:
            administration.max_users = max_users
            administration_updated = True
        # An explicit ``null`` is meaningless for a boolean entitlement (unlike
        # the caps, where null resets to unlimited), so guard on ``is not None``
        # and treat null/omitted alike as a no-op — mirroring how the operator
        # endpoint guards ``status``. Pydantic keeps an explicit null in
        # ``model_fields_set``, so a plain "provided" flag would let
        # ``{"guild_auth_enabled": null}`` silently disable the entitlement.
        if (
            guild_auth_enabled is not None
            and administration.guild_auth_enabled != guild_auth_enabled
        ):
            administration.guild_auth_enabled = guild_auth_enabled
            administration_updated = True
        if (
            banner_image_enabled is not None
            and administration.banner_image_enabled != banner_image_enabled
        ):
            administration.banner_image_enabled = banner_image_enabled
            administration_updated = True
        if administration_updated:
            session.add(administration)
            await session.flush()
    if retention_days_provided:
        from app.services.platform.app_settings import get_or_create_guild_settings

        gs = await get_or_create_guild_settings(session, guild_id)
        if gs.retention_days != retention_days:
            gs.retention_days = retention_days
            session.add(gs)
            await session.flush()
    return guild


async def set_guild_status(
    session: AsyncSession,
    *,
    guild_id: int,
    status: GuildStatus,
) -> Guild:
    """Set a guild's lifecycle status (operator moderation action).

    Kept separate from ``update_guild`` so only the platform-operator endpoint
    reaches it — a guild's own admins must never flip their guild's status. On a
    real transition it stamps ``status_changed_at``; a no-op change is left
    untouched. Enforcement of the status lives in the request path
    (``_load_guild_context`` + session routing), not here.
    """
    guild = await get_guild(session, guild_id=guild_id)
    if guild.status != status.value:
        guild.status = status.value
        guild.status_changed_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.flush()
    return guild


async def get_guild_retention_days(session: AsyncSession, guild_id: int) -> int | None:
    """Return the per-guild trash retention period in days, or None for
    "never auto-purge".

    Selecting the full row (not the column) is intentional: NULL in
    ``retention_days`` is the user's explicit "never" choice, and we must
    distinguish it from "no guild_settings row yet" (which would be a
    setup gap, fall back to the 90-day default). A bare column select
    collapses both to None and silently re-enables auto-purge for guilds
    that opted out.
    """
    stmt = select(GuildSetting).where(GuildSetting.guild_id == guild_id)
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return 90
    return row.retention_days


async def _invite_code_exists(session: AsyncSession, code: str) -> bool:
    stmt = select(GuildInvite.id).where(GuildInvite.code == code)
    result = await session.exec(stmt)
    return result.first() is not None


async def _generate_unique_invite_code(session: AsyncSession) -> str:
    for _ in range(10):
        candidate = secrets.token_urlsafe(INVITE_CODE_BYTES)
        if not await _invite_code_exists(session, candidate):
            return candidate
    raise RuntimeError("Unable to generate unique invite code")


async def list_guild_invites(
    session: AsyncSession, *, guild_id: int
) -> Sequence[GuildInvite]:
    stmt = (
        select(GuildInvite)
        .where(GuildInvite.guild_id == guild_id)
        .order_by(GuildInvite.created_at.desc())
    )
    result = await session.exec(stmt)
    return result.all()


async def create_guild_invite(
    session: AsyncSession,
    *,
    guild_id: int,
    created_by: int | None,
    expires_at: datetime | None = None,
    max_uses: int | None = 1,
    invitee_email: str | None = None,
) -> GuildInvite:
    # A full guild mints no new invites: every seat is taken, so any code handed
    # out now could only fail at redemption. Raises ``GuildCapacityError``.
    await _assert_member_capacity(session, guild_id=guild_id, claiming_seat=False)
    code = await _generate_unique_invite_code(session)
    if expires_at is None:
        expiry = datetime.now(timezone.utc) + timedelta(
            days=DEFAULT_INVITE_EXPIRATION_DAYS
        )
    else:
        expiry = (
            expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        )
    invite = GuildInvite(
        code=code,
        guild_id=guild_id,
        created_by=created_by,
        expires_at=expiry,
        max_uses=max_uses,
        invitee_email_encrypted=encrypt_field(invitee_email, SALT_EMAIL)
        if invitee_email
        else None,
    )
    session.add(invite)
    await session.flush()
    return invite


async def delete_guild_invite(
    session: AsyncSession, *, guild_id: int, invite_id: int
) -> None:
    stmt = select(GuildInvite).where(
        GuildInvite.id == invite_id,
        GuildInvite.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    invite = result.one_or_none()
    if invite:
        await session.delete(invite)


async def delete_guild(session: AsyncSession, guild: Guild) -> None:
    """Delete a guild's shared rows.

    Under schema-per-guild the guild's content lives in its schema and is removed
    separately by ``deprovision_guild`` (``DROP SCHEMA … CASCADE``). Here we only
    delete the shared guild row; its ``ON DELETE CASCADE`` foreign keys clear the
    roster (memberships, invites, OIDC claim mappings, access grants).

    Order-independent w.r.t. the schema drop: guild-schema tables carry no FKs to
    ``public.guilds`` (provisioning omits cross-schema FKs), so this row delete is
    never blocked by the schema. Callers delete the row first (reliable, makes the
    guild gone) and drop the schema as best-effort cleanup afterwards.

    Uses a bulk DELETE (not ``session.delete``) so the row goes via the DB-level
    ON DELETE CASCADE FKs — ``session.delete`` would walk ORM relationships and
    attempt sync loads in the async context (MissingGreenlet).
    """
    await session.exec(delete(Guild).where(Guild.id == guild.id))


async def get_invite_by_code(session: AsyncSession, *, code: str) -> GuildInvite | None:
    stmt = select(GuildInvite).where(GuildInvite.code == code)
    result = await session.exec(stmt)
    return result.one_or_none()


def invite_is_active(invite: GuildInvite) -> bool:
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return False
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return False
    return True


async def redeem_invite_for_user(
    session: AsyncSession,
    *,
    code: str,
    user: User,
) -> Guild:
    invite = await get_invite_by_code(session, code=code)
    if not invite:
        raise GuildInviteError(GuildMessages.INVITE_NOT_FOUND)
    if not invite_is_active(invite):
        raise GuildInviteError(GuildMessages.INVITE_EXPIRED_OR_USED)
    # A non-active guild is frozen: no new members while read_only or
    # suspended. Reported as an ordinary expired invite — the guild's
    # lifecycle status is deliberately not disclosed.
    target_guild = await get_guild(session, guild_id=invite.guild_id)
    if target_guild.status != GuildStatus.active.value:
        raise GuildInviteError(GuildMessages.INVITE_EXPIRED_OR_USED)

    # Email binding. ``invitee_email`` is advisory-when-absent: an invite with no
    # bound address (``invitee_email_encrypted`` is NULL) is a shareable link and
    # any authenticated user may redeem it. When it *is* set, the invite is bound
    # to that address and only the matching user may redeem it — otherwise the
    # binding is decorative and gives a false sense of security (SEC-15). We
    # compare via ``hash_email`` so normalization (lowercase/strip) matches the
    # users.email_hash unique-constraint exactly; ``user.email_hash`` is already
    # populated in both the register and accept-invite flows.
    bound_email = invite.invitee_email
    if bound_email and user.email_hash != hash_email(bound_email):
        raise GuildInviteError(GuildMessages.INVITE_EMAIL_MISMATCH)

    await ensure_membership(
        session,
        guild_id=invite.guild_id,
        user_id=user.id,
        role=GuildRole.member,
    )
    invite.uses += 1
    session.add(invite)
    guild = await get_guild(session, guild_id=invite.guild_id)
    return guild


async def _signal_members_present(session: AsyncSession, *, guild_id: int) -> None:
    """Poke this guild's members whose tabs this worker is holding.

    A guild may have thousands of members and almost none of them are at a
    keyboard right now, so the roster is narrowed to the sockets this process
    has before anything is queued: the cost is the people who are here, not the
    people who exist. Everyone else re-reads their account when they next
    arrive, which is the same moment they would have seen the change anyway.

    Other workers' members are reached by their own listeners off the bus, so
    what looks process-local here is not.
    """
    from app.services.platform.user_stream import stream as user_sockets

    here = user_sockets.connected_users()
    if not here:
        return
    rows = await session.exec(
        select(GuildMembership.user_id).where(
            GuildMembership.guild_id == guild_id,
            col(GuildMembership.user_id).in_(here),
        )
    )
    account_stream.queue_for_members(session, rows.all(), "community")


async def assert_community_directory_enabled(session: AsyncSession) -> None:
    """Raise unless the platform owner has switched the directory on.

    Read here rather than at each call site so the three surfaces the directory
    consists of — browsing, joining, and a guild listing itself — cannot drift
    apart. Imported lazily because the app-settings service reads guilds.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_directory_enabled(session):
        raise CommunityDirectoryDisabledError(
            GuildMessages.COMMUNITY_DIRECTORY_DISABLED
        )


async def _assert_listable(session: AsyncSession, guild: Guild) -> None:
    """Raise ``CommunityListingError`` unless this guild may be listed.

    Three conditions, each with its own message so the reply says which one:

    - it is on at least one shelf,
    - it has declared itself free of adult content (an unanswered NULL is not a
      declaration and is refused separately from an 18+ guild), and
    - its seat cap leaves room for somebody to join.
    """
    if not guild.categories:
        raise CommunityListingError(GuildMessages.GUILD_COMMUNITY_REQUIRES_CATEGORY)
    if guild.has_adult_content is None:
        raise CommunityListingError(GuildMessages.GUILD_COMMUNITY_CONTENT_NOT_DECLARED)
    if guild.has_adult_content:
        raise CommunityListingError(GuildMessages.GUILD_COMMUNITY_ADULT_CONTENT)
    administration = await get_administration(session, guild_id=guild.id)
    if (
        administration.max_users is not None
        and administration.max_users < MIN_COMMUNITY_SEATS
    ):
        raise CommunityListingError(GuildMessages.GUILD_COMMUNITY_REQUIRES_CAPACITY)


def community_listing_filters() -> list:
    """The conditions a guild must meet to be showing a card in the directory.

    One list, because three paths ask the same question and must agree: the
    directory that lists a guild, the join that its listing authorizes, and the
    images that listing publishes. A guild that has dropped out of the first
    must drop out of the other two in the same instant.

    Two of the three are CHECK constraints on ``guilds`` as well (a listed
    guild is on a shelf and has declared itself free of adult content), so a
    row that reaches this query already satisfies them. The seat cap is not: it
    lives on ``guild_administration``, only an operator sets it, and it can be
    lowered long after the listing was made.
    """
    return [
        Guild.is_community.is_(True),
        Guild.status == GuildStatus.active.value,
        # NULL is unlimited, hence the explicit null leg.
        or_(
            GuildAdministration.max_users.is_(None),
            GuildAdministration.max_users >= MIN_COMMUNITY_SEATS,
        ),
    ]


async def is_listed_in_directory(session: AsyncSession, *, guild_id: int) -> bool:
    """Whether this guild is showing a card in the directory right now.

    Asked per request rather than inherited from whatever produced a link, so a
    guild that un-lists itself — or that an operator drops below the seat floor
    — stops being reachable through it immediately.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_directory_enabled(session):
        return False
    statement = (
        select(func.count())
        .select_from(Guild)
        .join(GuildAdministration, GuildAdministration.guild_id == Guild.id)
        .where(Guild.id == guild_id)
    )
    for condition in community_listing_filters():
        statement = statement.where(condition)
    return bool((await session.exec(statement)).one())


async def age_confirmation_outstanding(
    session: AsyncSession,
    *,
    user: User,
) -> bool:
    """Whether this account owes the deployment an age confirmation.

    True when the deployment asks for one, the account has not given one, and
    it belongs to at least one guild that is listed right now. That last clause
    is why this is asked rather than stored: a guild lists itself long after
    its members joined, and every member it already had owes the confirmation
    from that moment — as does anyone a group sync or an admin put there, who
    was never shown a form to tick.

    Which guilds count is ``community_listing_filters()``, the same list the
    directory and the join it authorizes ask, so a guild that leaves the shelf
    stops holding anybody to this in the same instant.

    Reads another shape of the caller's own membership rows, so it wants a
    session that can see ``guilds`` unfiltered (the system engine) or the
    caller's own platform-tier session, which is scoped to exactly these rows.
    """
    from app.services.platform import app_settings as app_settings_service

    if user.age_confirmed_at is not None:
        return False
    settings_row = await app_settings_service.get_app_settings(session)
    # Two switches, both off-ramps: a deployment with no directory lists no
    # guild for anyone to be in, and an owner may have asserted that every
    # account here belongs to an adult.
    if not (
        settings_row.community_directory_enabled
        and settings_row.community_age_gate_enabled
    ):
        return False
    # One row is the whole answer — this is asked on every read of the caller's
    # own account until they answer, so it stops at the first listed guild
    # rather than counting them.
    statement = (
        select(GuildMembership.guild_id)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .join(
            GuildAdministration, GuildAdministration.guild_id == Guild.id, isouter=True
        )
        .where(GuildMembership.user_id == user.id, *community_listing_filters())
        .limit(1)
    )
    return (await session.exec(statement)).first() is not None


async def assert_age_confirmed(session: AsyncSession, *, user: User) -> None:
    """Raise unless this account may take a place in a listed guild.

    The directory's Join button asks first and this backs it, so ticking the
    box is what joins rather than what is checked afterwards. Every other way
    into a listed guild — an invite, a group sync, an admin adding somebody —
    lands the membership and is caught by
    :func:`age_confirmation_outstanding` instead, which is the enforcement:
    there is nobody at a keyboard on those paths to answer a question.
    """
    from app.services.platform import app_settings as app_settings_service

    if user.age_confirmed_at is not None:
        return
    if not await app_settings_service.community_age_gate_enabled(session):
        return
    raise AgeConfirmationRequiredError(GuildMessages.AGE_CONFIRMATION_REQUIRED)


async def list_profile_communities(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[Guild]:
    """The listed communities one account belongs to, for their profile.

    Which guilds may appear is ``community_listing_filters()`` — the same list
    the directory, the join it authorizes and the images it publishes all ask,
    so a guild that leaves the shelf leaves every profile in the same instant.
    A guild someone is in that never opted in is nobody else's business and is
    not here.

    Needs a session that can see another account's ``guild_memberships`` (the
    system engine): the request path is scoped to the caller's own rows, and
    the question is about somebody else. Nothing from inside a guild's schema
    is read — only the identity it published by opting in.
    """
    from app.services.platform import app_settings as app_settings_service

    # A deployment with the directory off publishes no communities at all, so
    # there is nothing a profile could name.
    if not await app_settings_service.community_directory_enabled(session):
        return []
    stmt = (
        select(Guild)
        .join(GuildMembership, GuildMembership.guild_id == Guild.id)
        .join(
            GuildAdministration, GuildAdministration.guild_id == Guild.id, isouter=True
        )
        .where(GuildMembership.user_id == user_id, *community_listing_filters())
        .order_by(Guild.name.asc())
    )
    return list((await session.exec(stmt)).unique().all())


async def list_community_guilds(
    session: AsyncSession,
    *,
    user_id: int,
    query: str | None = None,
    category: str | None = None,
    offset: int = 0,
    limit: int = 24,
) -> tuple[list[tuple[Guild, int, bool]], int]:
    """The community directory: (guild, member_count, already_member) + total.

    Which guilds appear is not this function's decision — it is
    ``community_listing_filters()``, so the directory, the join it authorizes,
    and the images it publishes cannot drift apart.

    Ordered by member count, busiest first, since that is what someone with no
    guild yet is choosing between; ``query`` narrows on name or description
    across the whole directory rather than within a page, so a search reaches
    guilds no amount of scrolling had loaded.

    Needs a session that can see every guild's ``guild_memberships`` rows to
    count them (the system engine), the same precondition ``count_members``
    documents. Nothing about a guild's *content* is read — only the identity it
    published by opting in, plus how many people are already there.
    """
    await assert_community_directory_enabled(session)
    member_count = (
        select(func.count())
        .select_from(GuildMembership)
        .where(GuildMembership.guild_id == Guild.id)
        .correlate(Guild)
        .scalar_subquery()
    )
    already_member = (
        select(func.count())
        .select_from(GuildMembership)
        .where(
            GuildMembership.guild_id == Guild.id,
            GuildMembership.user_id == user_id,
        )
        .correlate(Guild)
        .scalar_subquery()
    )

    filters = community_listing_filters()
    if category:
        filters.append(Guild.categories.contains([category]))
    if query and query.strip():
        # Case-insensitive across the two fields a card actually shows.
        needle = f"%{query.strip()}%"
        filters.append(or_(Guild.name.ilike(needle), Guild.description.ilike(needle)))

    # Every guild has exactly one administration row, created with it, so this
    # is an inner join by construction.
    administration_join = (
        GuildAdministration,
        GuildAdministration.guild_id == Guild.id,
    )
    count_statement = select(func.count()).select_from(Guild).join(*administration_join)
    statement = select(Guild, member_count, already_member > 0).join(
        *administration_join
    )
    for condition in filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = (await session.exec(count_statement)).one()
    # Busiest first: someone browsing for a community to join is best served by
    # the ones with people already in them. Name and id break ties, so a guild
    # never swaps pages between two requests that saw the same counts.
    statement = statement.order_by(
        member_count.desc(), Guild.name.asc(), Guild.id.asc()
    )
    rows = (await session.exec(statement.offset(offset).limit(limit))).all()
    return [(guild, int(count), bool(joined)) for guild, count, joined in rows], int(
        total
    )


async def join_community_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
) -> Guild:
    """Join a listed community guild — the invite-free half of the directory.

    The opt-in is the authorization, so this asks the directory's own question
    (``is_listed_in_directory``) rather than a version of it. A guild that is
    not listed is reported as not found rather than as forbidden — an unlisted
    guild has published nothing, and its existence at a given id is part of
    that.

    Runs on the system engine for the same reason ``accept_invite`` does: the
    caller is not a member yet, so no guild-scoped role exists to write the
    membership under.
    """
    await assert_community_directory_enabled(session)
    try:
        guild = await get_guild(session, guild_id=guild_id)
    except ValueError as exc:
        raise CommunityJoinError(GuildMessages.GUILD_NOT_FOUND) from exc
    # Exactly what the directory shows, so a guild it does not list cannot be
    # joined by asking for it directly either.
    if not await is_listed_in_directory(session, guild_id=guild_id):
        raise CommunityJoinError(GuildMessages.GUILD_NOT_A_COMMUNITY)
    # Asked before the seat is taken, so the box is what joins rather than
    # something checked once they are already in.
    await assert_age_confirmed(session, user=user)
    # Capacity is enforced inside ensure_membership, which is also where a
    # repeat join short-circuits to the existing membership.
    await ensure_membership(
        session,
        guild_id=guild_id,
        user_id=user.id,
        role=GuildRole.member,
    )
    return guild


async def describe_invite_code(
    session: AsyncSession,
    *,
    code: str,
) -> tuple[GuildInvite | None, Guild | None, bool, str | None]:
    invite = await get_invite_by_code(session, code=code)
    if not invite:
        return None, None, False, GuildMessages.INVITE_NOT_FOUND
    guild = await get_guild(session, guild_id=invite.guild_id)
    # A non-active guild accepts no new members; report the invite as plain
    # expired (never the guild's lifecycle status).
    if guild.status != GuildStatus.active.value:
        return invite, guild, False, GuildMessages.INVITE_EXPIRED
    if invite_is_active(invite):
        return invite, guild, True, None

    reason = GuildMessages.INVITE_INVALID
    now = datetime.now(timezone.utc)
    if invite.expires_at and invite.expires_at < now:
        reason = GuildMessages.INVITE_EXPIRED
    elif invite.max_uses is not None and invite.uses >= invite.max_uses:
        reason = GuildMessages.INVITE_USED
    return invite, guild, False, reason


async def remove_user_from_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Remove a user from a guild, its initiatives, and its apps.

    Leaving a guild ends what that guild's apps let this person reach at an
    outside vendor: the credentials they connected under this guild's authority
    are deleted and the apps holding them are told to let go. Their connections
    in other guilds are untouched — those relationships have not ended.

    The session must already be routed into the guild. Revocations are queued on
    it and delivered by the caller after the commit.
    """
    from app.services.tenant import app_connections as app_connections_service
    from app.services.tenant import app_delegations as app_delegations_service
    from app.services.tenant import initiatives as initiatives_service

    # Remove from all initiatives in this guild
    await initiatives_service.remove_user_from_guild_initiatives(
        session,
        guild_id=guild_id,
        user_id=user_id,
    )

    await app_connections_service.delete_member_connections(
        session, user_id=user_id, reason="left_guild"
    )
    # Leaving ends what this guild's apps may do as this person, the same way it
    # ends what they reach at a vendor.
    await app_delegations_service.delete_member_delegations(session, user_id=user_id)

    # Remove guild membership
    stmt = delete(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    # Only a real removal is a membership change — mirror the insert side,
    # which pings only on a genuine insert (a no-op remove of a non-member
    # must not nudge billing).
    if result.rowcount:
        # Same reason as the insert side: what is asked of this account can
        # change with where it belongs, and leaving is not always their doing.
        account_stream.queue_account_signal(session, user_id, "membership")
        billing_ping.notify_membership_changed(guild_id)
        # This community was a leg of can_ask for everyone they shared it with,
        # so every open channel that rested on it is re-tested. One survives if
        # the pair connected, which is what a connection is for. The sweep
        # commits on its own, so a caller that rolls back after this leaves the
        # channels closed rather than open — the safe direction, and a new
        # request reopens one.
        await contact_grants_service.revoke_stale_message_grants(
            session, user_id=user_id
        )


async def adopt_guild_name_display(session: AsyncSession, *, guild_id: int) -> None:
    """Render this request the way ``guild_id`` renders its members.

    The guild path sets this with the rest of the guild context. The two
    endpoints that route into a guild by hand — the platform and self-service
    initiative-member pickers — have no guild context to carry it, so they take
    the setting here instead. Reading a guild's roster and showing names it
    does not show, or hiding names it does, would both be wrong.
    """
    shows = (
        await session.exec(select(Guild.show_member_names).where(Guild.id == guild_id))
    ).one_or_none()
    set_guild_shows_member_names(bool(shows))
