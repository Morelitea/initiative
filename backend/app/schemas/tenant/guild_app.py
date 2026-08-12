"""What an installed app looks like over the wire."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel
from app.services.tenant.guild_apps import requires_guild_admin


class GuildAppInstall(SanitizedBaseModel):
    """Install a listing into this guild.

    Names a listing and nothing else that matters: the definition comes from the
    catalog, and the content the install creates is made server-side.
    """

    listing_uid: str = Field(max_length=14)
    #: Overrides the listing's own default for the content this creates.
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class GuildAppUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    #: Turning an app off hides it without touching what it created.
    enabled: Optional[bool] = None


class GuildAppRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    listing_uid: str
    listing_version: str
    app_kind: str
    name: str
    enabled: bool
    #: What the app needs to reach its own content — for a tool instance, the id
    #: of the row it created, so the sidebar can link straight to it.
    config: Dict[str, Any] = {}
    #: Which tool this app mounts, when it mounts one. Read off the pinned
    #: definition so the client need not fetch the catalog to render an entry.
    tool: Optional[str] = None
    #: Which configured surface this app opens, when it is an embed. Same
    #: reasoning as ``tool``, for the kind that has no content of its own.
    embed_target: Optional[str] = None
    #: Whether opening this app is a guild-admin action. Decided here, not by
    #: the client reading the kind: an entry a member cannot use should not be
    #: offered to them, and which apps those are is the server's call.
    admin_only: bool = False
    installed_by_id: int
    created_at: datetime
    updated_at: datetime


class GuildAppListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[GuildAppRead]


def serialize_guild_app(app: Any) -> GuildAppRead:
    definition = app.definition or {}
    return GuildAppRead(
        id=app.id,
        guild_id=app.guild_id,
        listing_uid=app.listing_uid,
        listing_version=app.listing_version,
        app_kind=app.app_kind,
        name=app.name,
        enabled=app.enabled,
        config=dict(app.config or {}),
        tool=definition.get("tool"),
        embed_target=definition.get("embed_target"),
        admin_only=requires_guild_admin(definition),
        installed_by_id=app.installed_by_id,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )
