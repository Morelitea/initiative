"""Reading and writing what an account wants to be told about.

Everything here is about the signed-in account and nobody else, so both routes
resolve their subject from the credential rather than a path parameter.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import UserSessionDep, get_current_active_user
from app.db.session import set_rls_context
from app.core.notification_categories import (
    CATEGORY_SPECS,
    ALL_CHANNELS,
    NotificationCategory,
)
from app.models.platform.guild import Guild, GuildMembership
from app.models.platform.user import User
from app.models.platform.user_notification_prefs import NotificationLevel
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.schemas.platform.notification_prefs import (
    GuildNotificationSettings,
    NotificationCategoryRead,
    NotificationPreferencesRead,
    NotificationPreferencesUpdate,
    QuietHours,
)
from app.services import notifications as notifications_service
from app.services.platform import notification_prefs as prefs_service

me_router = APIRouter()


#: The digest queues an opt-out can leave nobody wanting. One entry per digest,
#: so a new digest is cleaned up on opt-out by being listed here.
_DIGEST_QUEUES: tuple[tuple[NotificationCategory, type], ...] = (
    (NotificationCategory.assignments, TaskAssignmentDigestItem),
    (NotificationCategory.reactions, ReactionDigestItem),
)


def _registry() -> list[NotificationCategoryRead]:
    return [
        NotificationCategoryRead(
            category=category,
            group=spec.group,
            personal=spec.personal,
            guild_scoped=spec.guild_scoped,
            mutable_channels=[c for c in ALL_CHANNELS if c in spec.mutable_channels],
            defaults={channel: spec.defaults[channel] for channel in ALL_CHANNELS},
        )
        for category, spec in CATEGORY_SPECS.items()
    ]


def _section(doc: dict[str, Any], key: str) -> dict[str, Any]:
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


def _prune(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop empty branches so the document stays sparse.

    Sparseness is what makes "everything on by default" true by construction,
    so a switch turned off and back on must leave no trace behind.
    """

    def _walk(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        out = {k: _walk(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in ({}, None)}

    return _walk(doc)


@me_router.get("/notification-preferences", response_model=NotificationPreferencesRead)
async def read_my_notification_preferences(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationPreferencesRead:
    """The registry, this account's overrides, and each community's level.

    The registry travels with the response so the settings page renders the
    categories this build has rather than a copy of the list.
    """
    doc = await prefs_service.load_prefs(session, current_user.id)
    rows = (
        await session.exec(
            select(Guild, GuildMembership)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == current_user.id)
            .order_by(GuildMembership.position, Guild.name)
        )
    ).all()
    guild_docs = _section(doc, "guilds")
    guilds = [
        GuildNotificationSettings(
            guild_id=guild.id,
            guild_name=guild.name,
            level=prefs_service.level_for(doc, guild.id),
            categories=_section(guild_docs.get(str(guild.id)) or {}, "categories"),
        )
        for guild, _membership in rows
    ]
    window = prefs_service.quiet_hours(doc)
    return NotificationPreferencesRead(
        categories=_registry(),
        settings=_section(doc, "categories"),
        quiet_hours=(
            QuietHours(
                start=window[0].strftime("%H:%M"), end=window[1].strftime("%H:%M")
            )
            if window
            else None
        ),
        guilds=guilds,
    )


@me_router.put("/notification-preferences", response_model=NotificationPreferencesRead)
async def update_my_notification_preferences(
    payload: NotificationPreferencesUpdate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NotificationPreferencesRead:
    """Move some switches.

    A partial write, because that is what a settings page sends and because two
    open tabs must not overwrite each other's unrelated rows.
    """
    doc = await prefs_service.load_prefs(session, current_user.id)

    for change in payload.channels:
        spec = CATEGORY_SPECS[change.category]
        if not spec.is_mutable(change.channel):
            # A channel that cannot be switched off is not an error to ask
            # about — it simply does not move.
            continue
        if change.guild_id is not None and not spec.guild_scoped:
            continue
        branch = doc
        if change.guild_id is not None:
            branch = doc.setdefault("guilds", {}).setdefault(str(change.guild_id), {})
        categories = branch.setdefault("categories", {})
        row = categories.setdefault(change.category.value, {})
        if change.enabled == spec.defaults[change.channel]:
            # Back to the default: forget it rather than storing the default,
            # so the document only ever holds real exceptions.
            row.pop(change.channel.value, None)
        else:
            row[change.channel.value] = change.enabled

    for level_change in payload.levels:
        branch = doc.setdefault("guilds", {}).setdefault(str(level_change.guild_id), {})
        if level_change.level is NotificationLevel.everything:
            branch.pop("level", None)
        else:
            branch["level"] = level_change.level.value

    if payload.clear_quiet_hours:
        doc.pop("quiet_hours", None)
    elif payload.quiet_hours is not None:
        doc["quiet_hours"] = {
            "start": payload.quiet_hours.start,
            "end": payload.quiet_hours.end,
        }

    doc = _prune(doc)
    await prefs_service.save_prefs(session, current_user.id, doc)

    # A queue nobody will ever be sent is discarded, not kept: it is guild
    # scoped, so this reaches into each of the account's guild schemas.
    emptied = [
        model
        for category, model in _DIGEST_QUEUES
        if not notifications_service.wants_digest(doc, category)
    ]
    if emptied:
        user_id = current_user.id
        await notifications_service.clear_digest_queue_across_guilds(
            session, user_id, emptied
        )
        # The cross-guild fan-out leaves the session routed; put it back on
        # the platform context this request runs in.
        await set_rls_context(session, user_id=user_id)

    await session.commit()
    return await read_my_notification_preferences(session, current_user)
