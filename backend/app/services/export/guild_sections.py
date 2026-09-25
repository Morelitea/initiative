"""Guild-level export sections — what a community owns outside its initiatives.

The per-tool envelopes in ``adapters/`` cover the work done *inside* an
initiative. They do not cover the community itself: its configuration, its tag
vocabulary, its roster, or the apps it installed. Those live in guild-level
tables (``db.tenancy.GUILD_LEVEL_TABLES``) and had no representation in a
backup at all, so a guild that exported and re-imported got its content back
and lost everything that made it that community.

Declared as a registry rather than as a list of calls inside the adapter, for
the reason ``NON_EXPORTABLE_TOOLS`` is an exclusion list: the default is
"a guild-level table is exported", and ``guild_sections_test`` fails until a
new one is either carried by a section here or named in ``EXEMPT`` with a
reason. Remembering to come back to this file is not the mechanism.

Two rules the builders hold to:

* **Secrets never leave.** A row that holds a credential is exempt, and a
  section over a table that holds one selects columns rather than dumping the
  row (``guild_apps.config_secrets`` is the live example).
* **People are named the way the rest of the app names them.** The roster goes
  through ``GuildMember``/``handle_of``, the same shape every other
  server-generated text uses, so a name reads here exactly as it does
  everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User

# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionContext:
    """What a builder is given: a guild-routed session, who is asking, and the
    manifest's ``skipped`` list to record anything it leaves out.

    A builder that drops something the caller can see appends to ``skipped``
    rather than staying quiet, so the archive states what it does not hold.
    """

    session: AsyncSession
    user: User
    guild_id: int
    skipped: list = field(default_factory=list)


@dataclass(frozen=True)
class GuildSection:
    """One guild-level file in the archive.

    ``build`` returns the payload and the record count, or ``None`` when the
    community has nothing of this kind — an absent section reads as "none",
    which is why an empty one is not written.

    ``scopes`` decides which exports carry the section. A section describing
    the COMMUNITY — its configuration, its roster, what it installed — belongs
    to the community-scoped export. ``tags`` is in both, because the
    vocabulary is part of the content an initiative archive carries: without
    it every tag in that archive arrives with its colour missing.
    """

    key: str
    path: str
    build: Callable[[SectionContext], Awaitable[tuple[dict[str, Any], int] | None]]
    scopes: frozenset[str] = frozenset({"guild"})


async def _build_settings(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """The community's own configuration: the row people edit under Settings,
    plus the guild-level flags that live on the ``guilds`` row itself."""
    from sqlmodel import select

    from app.models.platform.guild import Guild
    from app.models.tenant.guild_setting import GuildSetting

    guild = await ctx.session.get(Guild, ctx.guild_id)
    if guild is None:
        return None
    setting = (await ctx.session.exec(select(GuildSetting).limit(1))).first()
    payload: dict[str, Any] = {
        "type": "guild-settings",
        "schema_version": 1,
        "name": guild.name,
        "description": guild.description,
        "is_community": guild.is_community,
        "show_member_names": guild.show_member_names,
        "categories": list(guild.categories or []),
        "has_adult_content": guild.has_adult_content,
        "allow_api_keys": guild.allow_api_keys,
        "enforce_compliance_session": guild.enforce_compliance_session,
        "allow_push_notifications": guild.allow_push_notifications,
        "allow_email_notifications": guild.allow_email_notifications,
        "redact_notification_content": guild.redact_notification_content,
        "banner": dict(guild.banner or {}),
        "retention_days": setting.retention_days if setting else None,
    }
    return payload, 1


async def _build_tags(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """The tag vocabulary. Envelopes reference tags by NAME, so without this
    the definitions — colour, and the fact that a tag existed at all before
    anything was tagged with it — do not survive a round trip."""
    from sqlmodel import select

    from app.models.tenant.tag import Tag

    rows = list(await ctx.session.exec(select(Tag).order_by(Tag.name.asc())))
    if not rows:
        return None
    payload = {
        "type": "guild-tags",
        "schema_version": 1,
        "tags": [
            {"name": tag.name, "color": tag.color, "created_at": _iso(tag.created_at)}
            for tag in rows
        ],
    }
    return payload, len(rows)


async def _build_members(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """Who was in the community, and at what guild role.

    Named by handle rather than by id: an id means nothing in the instance the
    archive is restored into, while a handle is the identifier that reads the
    same everywhere (it is how ``ManifestPerson`` already inventories comment
    authors). The numeric id rides along as the same-instance fast path.

    People come from ``GuildMember``, the projection already narrowed to the
    routed guild's members, rather than from the unnarrowed one filtered by a
    list of ids — so the roster is this community's by construction.
    """
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.models.platform.guild import GuildMembership
    from app.models.platform.user_profile_view import GuildMember

    memberships = list(
        await ctx.session.exec(
            select(GuildMembership)
            .where(GuildMembership.guild_id == ctx.guild_id)
            .order_by(GuildMembership.user_id.asc())
        )
    )
    if not memberships:
        return None
    profiles = {
        profile.id: profile for profile in await ctx.session.exec(select(GuildMember))
    }
    members = []
    for membership in memberships:
        profile = profiles.get(membership.user_id)
        members.append(
            {
                "user_id": membership.user_id,
                "handle": handle_of(profile) if profile else None,
                "name": getattr(profile, "full_name", None),
                "role": _enum_value(membership.role),
                "joined_at": _iso(getattr(membership, "created_at", None)),
            }
        )
    payload = {"type": "guild-members", "schema_version": 1, "members": members}
    return payload, len(members)


async def _build_apps(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """Apps the community installed — built-in ones only.

    An app published by anybody but this build is not ours to put in a file:
    its definition belongs to its publisher, and restoring it elsewhere means
    installing it there from the catalog, not unpacking a copy. Third-party
    installs are recorded in the manifest's ``skipped`` list instead, so the
    archive says they existed.

    Secrets are selected out rather than filtered: ``config_secrets`` and
    ``connection_refs`` never appear.
    """
    from sqlmodel import select

    from app.models.tenant.guild_app import GuildApp
    from app.services.export.provenance import builtin_listing_uids

    from app.schemas.tenant.backup_export import ManifestSkipped
    from app.services.export.provenance import THIRD_PARTY_REASON

    rows = list(await ctx.session.exec(select(GuildApp).order_by(GuildApp.id.asc())))
    if not rows:
        return None
    builtin = await builtin_listing_uids(
        ctx.session, [row.listing_uid for row in rows if row.listing_uid]
    )
    kept = []
    for row in rows:
        if row.listing_uid in builtin:
            kept.append(row)
        else:
            ctx.skipped.append(
                ManifestSkipped(
                    tool="app",
                    entity_id=row.id,
                    title=row.name,
                    reason=THIRD_PARTY_REASON,
                )
            )
    if not kept:
        return None
    from app.services.tenant.guild_apps import placements_by_install

    placements = await placements_by_install(ctx.session, [row.id for row in kept])
    payload = {
        "type": "guild-apps",
        "schema_version": 2,
        "apps": [
            {
                "listing_uid": row.listing_uid,
                "listing_version": row.listing_version,
                "app_kind": row.app_kind,
                "name": row.name,
                "enabled": row.enabled,
                "auto_update": row.auto_update,
                "config": dict(row.config or {}),
                "placements": [
                    {
                        "initiative_id": placement.initiative_id,
                        "role_ids": list(placement.role_ids or []),
                    }
                    for placement in placements.get(row.id, [])
                ],
            }
            for row in kept
        ],
    }
    return payload, len(kept)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _enum_value(value) -> Any:
    return getattr(value, "value", value)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

GUILD_SECTIONS: tuple[GuildSection, ...] = (
    GuildSection("settings", "guild/settings.json", _build_settings),
    GuildSection(
        "tags",
        "guild/tags.json",
        _build_tags,
        scopes=frozenset({"guild", "initiative"}),
    ),
    GuildSection("members", "guild/members.json", _build_members),
    GuildSection("apps", "guild/apps.json", _build_apps),
)


def sections_for(scope_kind: str) -> tuple[GuildSection, ...]:
    """The sections an export at this scope may carry."""
    return tuple(s for s in GUILD_SECTIONS if scope_kind in s.scopes)


# Guild-level table -> the section key that carries it. Checked against
# ``db.tenancy.GUILD_LEVEL_TABLES`` (an independent source) by
# ``guild_sections_test``.
SECTION_TABLES: dict[str, str] = {
    "guild_settings": "settings",
    "tags": "tags",
    "guild_apps": "apps",
    # Each install's placements ride inside its entry in the apps section.
    "app_placements": "apps",
    # Carried per-initiative rather than at the guild root: an initiative's
    # roster and role set belong beside its content, not in one flat file.
    "initiatives": "initiatives",
    "initiative_members": "initiatives",
    "initiative_roles": "initiatives",
    "initiative_role_permissions": "initiatives",
    # The blob store. Referenced blobs ride with their document; a guild-scope
    # backup with uploads on takes the rest too, which is the only way a file
    # nothing currently points at survives.
    "uploads": "uploads",
}

# Guild-level tables deliberately NOT exported, and why. A reason is required:
# it is what a reviewer reads instead of guessing whether the omission was a
# decision or an oversight.
EXEMPT: dict[str, str] = {
    # Credentials. An archive is a file that leaves the deployment.
    "guild_ai_connections": "credentials",
    "guild_ai_member_keys": "credentials",
    "guild_app_user_connections": "credentials",
    "app_member_consents": "credentials",
    # Per-member personal preference, not community property — it belongs to
    # the member, and follows them rather than the guild.
    "guild_ai_member_prefs": "personal",
    # Operational ledgers about the app's own work. Restoring them would
    # describe a history that did not happen in the instance reading them.
    "export_jobs": "operational",
    "import_jobs": "operational",
    "webhook_deliveries": "operational",
    "app_hook_deliveries": "operational",
    # In-flight workflow rather than owned content: a request to join is a
    # question waiting on somebody in THIS instance.
    "initiative_join_requests": "in_flight",
}

__all__ = [
    "GUILD_SECTIONS",
    "sections_for",
    "GuildSection",
    "SectionContext",
    "SECTION_TABLES",
    "EXEMPT",
]
