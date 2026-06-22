"""Router-level resource authorization — one load-and-check choke point.

`authorize` is the single access decision (feature gate + manage block + DAC);
`load_authorized` and `resource_dependency` add loading on top for fetch-then-act
handlers and FastAPI-injected routes. `RESOURCE_ACCESS` is the enforcement-side
registry; `dac_kind` keys into `permissions.DAC_RESOURCES` (`None` = no per-row
DAC, e.g. calendar events — feature gate only).
"""

# NOT `from __future__ import annotations`: resource_dependency builds a signature
# with Annotated[int, Path(alias=cfg.path_param)] closing over a local; stringized
# annotations re-evaluate it where cfg is out of scope → FastAPI drops the path
# param and 422s.

from dataclasses import dataclass
from typing import Annotated, Any, Awaitable, Callable, Optional

from fastapi import Depends, HTTPException, Path, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import (
    CalendarEventMessages,
    CounterMessages,
    DocumentMessages,
    ProjectMessages,
    QueueMessages,
)
from app.core.pam_context import has_active_grant
from app.models.platform.guild import GuildRole
from app.models.platform.user import User
from app.services.tenant import counters as counters_service
from app.services import permissions as permissions_service
from app.services.tenant import queues as queues_service

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@dataclass(frozen=True)
class ResourceAccessConfig:
    dac_kind: Optional[str] = None  # key into DAC_RESOURCES; None = feature gate only
    feature_attr: Optional[str] = None  # initiative flag gating the feature
    feature_disabled_msg: Optional[str] = None
    grant_cannot_manage_msg: Optional[str] = None
    loader: Optional[Callable[..., Awaitable[Any]]] = (
        None  # async (session, id) -> row|None
    )
    path_param: Optional[str] = None
    not_found_msg: Optional[str] = None


RESOURCE_ACCESS: dict[str, ResourceAccessConfig] = {
    "project": ResourceAccessConfig(
        dac_kind="project",
        grant_cannot_manage_msg=ProjectMessages.GRANT_CANNOT_MANAGE_MEMBERS,
    ),
    "document": ResourceAccessConfig(
        dac_kind="document",
        grant_cannot_manage_msg=DocumentMessages.GRANT_CANNOT_MANAGE_MEMBERS,
    ),
    "queue": ResourceAccessConfig(
        dac_kind="queue",
        feature_attr="queues_enabled",
        feature_disabled_msg=QueueMessages.FEATURE_DISABLED,
        loader=queues_service.get_queue,
        path_param="queue_id",
        not_found_msg=QueueMessages.NOT_FOUND,
    ),
    "counter_group": ResourceAccessConfig(
        dac_kind="counter_group",
        feature_attr="counters_enabled",
        feature_disabled_msg=CounterMessages.FEATURE_DISABLED,
        grant_cannot_manage_msg=CounterMessages.GRANT_CANNOT_MANAGE,
        loader=counters_service.get_counter_group,
        path_param="group_id",
        not_found_msg=CounterMessages.GROUP_NOT_FOUND,
    ),
    "calendar_event": ResourceAccessConfig(
        dac_kind="calendar_event",
        feature_attr="events_enabled",
        feature_disabled_msg=CalendarEventMessages.FEATURE_DISABLED,
        grant_cannot_manage_msg=CalendarEventMessages.GRANT_CANNOT_MANAGE_MEMBERS,
    ),
}


def authorize(
    kind: str,
    row: Any,
    user: Optional[User] = None,
    *,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Feature gate → manage-via-grant block → DAC decision. Reads request-scoped
    role/PAM context, so callers don't thread it."""
    cfg = RESOURCE_ACCESS[kind]
    initiative = getattr(row, "initiative", None)
    if (
        cfg.feature_attr
        and initiative is not None
        and not getattr(initiative, cfg.feature_attr)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.feature_disabled_msg
        )
    if (
        manage_access
        and cfg.grant_cannot_manage_msg
        and has_active_grant(getattr(row, "guild_id", None))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.grant_cannot_manage_msg
        )
    if cfg.dac_kind is not None:
        permissions_service.require_access(
            permissions_service.DAC_RESOURCES[cfg.dac_kind],
            row,
            user,
            access=access,
            require_owner=require_owner,
            guild_role=guild_role,
        )


async def load_authorized(
    session: Any,
    kind: str,
    resource_id: int,
    user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
) -> Any:
    """Load by id (RLS scopes to the guild) → 404 if absent, then authorize."""
    cfg = RESOURCE_ACCESS[kind]
    row = await cfg.loader(session, resource_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_msg
        )
    authorize(
        kind,
        row,
        user,
        access=access,
        require_owner=require_owner,
        manage_access=manage_access,
        guild_role=guild_context.role,
    )
    return row


def resource_dependency(
    kind: str, access: str = "read", *, require_owner: bool = False
) -> Callable[..., Awaitable[Any]]:
    """FastAPI dependency injecting a pre-authorized resource (check before body)."""
    cfg = RESOURCE_ACCESS[kind]

    async def dependency(
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
        resource_id: Annotated[int, Path(alias=cfg.path_param)],
    ) -> Any:
        return await load_authorized(
            session,
            kind,
            resource_id,
            current_user,
            guild_context,
            access=access,
            require_owner=require_owner,
        )

    return dependency


def my_permission_level(
    row: Any, kind: str, user: User, guild_context: GuildContext
) -> str | None:
    """`my_permission_level` for the client: guild admin → owner, else DAC."""
    cfg = RESOURCE_ACCESS[kind]
    if guild_context.role == GuildRole.admin:
        return "owner"
    return permissions_service.compute_permission(
        permissions_service.DAC_RESOURCES[cfg.dac_kind], row, user.id
    )
