"""Which communities have installed which plug-in, in one place.

An install is a row in its community's own schema (``guild_plugins``). This is
the index of them across communities: the listing an install came from, the
community and install, whether the install is switched on, and the value a
vendor webhook is routed to it by. It holds no content.

It answers two questions without visiting a guild schema: which installs an
plug-in has (``GET /plugin-platform/installations``), and which installs a vendor
delivery belongs to (``POST /plugin-hooks/{public_id}``). ``hook_route`` is the
stored value of the field the plug-in's ``webhooks.route`` names, written when a
connect stores it and cleared when it is removed.

Kept in step by :mod:`app.services.marketplace.plugin_installs`. Reached only by
the system engine.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String
from sqlmodel import Field, SQLModel

__all__ = ["PluginInstall", "HOOK_ROUTE_MAX_LENGTH"]

#: The widest route value kept.
HOOK_ROUTE_MAX_LENGTH = 200


class PluginInstall(SQLModel, table=True):
    __tablename__ = "plugin_installs"
    __table_args__ = (
        Index("ix_plugin_installs_hook_route", "listing_uid", "hook_route"),
        Index("ix_plugin_installs_listing", "listing_uid", "guild_id", "install_id"),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    #: ``guild_plugins.id`` in that community's schema.
    install_id: int = Field(sa_column=Column(Integer, primary_key=True))
    #: The listing the install came from, which names its registration.
    listing_uid: str = Field(sa_column=Column(String(length=14), nullable=False))
    enabled: bool = Field(sa_column=Column(Boolean, nullable=False))
    hook_route: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=HOOK_ROUTE_MAX_LENGTH), nullable=True),
    )
