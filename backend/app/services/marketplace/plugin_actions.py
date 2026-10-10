"""A plug-in's actions on items: a reader runs one, and the plug-in does it.

An action is declared in the install's pinned definition, offered on some kinds
of item, and names one of the plug-in's write endpoints. Initiative only
connects, and checks, in order, that the connection may be made:

1. the pinned definition declares the action on this kind of item, the
   community's content is not frozen, and the community's connections the
   action requires hold a value;
2. the reader can read the item, through the ordinary resource path;
3. the install is placed in the item's initiative with a role the reader holds
   (:func:`~app.services.tenant.guild_plugins.surface_access`, as a page
   opened there is);
4. the install can read the item itself, routed as the install.

The write is then called as the installation, with the reader as ``viewer``
(by this install's reference for them) and the item as ``subject`` in the
call's token. What it changes, and whether this reader may, is the plug-in's
to decide; Initiative writes nothing for it. The answer is the values the
install shows on the item as they stand afterwards, and every other reader
hears that the item changed from its own values' change capture.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import exists
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.messages import GuildPluginMessages, PluginDataMessages
from app.core.tools import KINDS
from app.db import cohorts
from app.db.guild_standing import GuildContext
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_metadata import PluginMetadata
from app.services.marketplace import plugin_data
from app.services.marketplace.plugin_data import PluginDataError
from app.services.marketplace.plugin_refs import ensure_plugin_ref
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.service_plugins import is_admin_only
from app.services.tenant import guild_plugins, plugin_config
from app.services.tenant.guild_plugins import SurfaceAccess

__all__ = ["run_action"]


def _install_scopes(
    plugin: GuildPlugin, registration: RegistrationSnapshot
) -> frozenset[str]:
    """The scopes the install's tokens carry now: granted, still requested by
    the pinned version, and within the registration's ceiling."""
    requested = set(guild_plugins.requested_scopes(plugin.definition))
    ceiling = set(registration.scope_ceiling)
    return frozenset(
        scope
        for scope in plugin.granted_scopes or ()
        if scope in requested and scope in ceiling
    )


async def _install_reads(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    *,
    guild_id: int,
    kind: str,
    entity_id: int,
) -> bool:
    """Whether the install can read the item, asked of the database on a
    session of its own routed as the install, with the scopes its tokens
    carry: the answer its own reads get."""
    table = SQLModel.metadata.tables[KINDS[kind].table]
    async with cohorts.request_sessionmaker(guild_id)() as session:
        try:
            await establish_install_access(
                session,
                VerifiedInstall(
                    guild_id=guild_id,
                    install_id=int(plugin.id or 0),
                    client_id=registration.public_id,
                    scopes=_install_scopes(plugin, registration),
                ),
            )
        except InstallAccessError:
            return False
        return bool(
            await session.scalar(exists().where(table.c.id == entity_id).select())
        )


async def _item_initiative(
    session: AsyncSession, kind: str, entity_id: int, context: GuildContext
) -> int:
    """The item's initiative, once the reader is found to read it as its own
    routes would let them (404 or 403 otherwise)."""
    row = await resource_access.load_kind(session, kind, entity_id, None, context)
    tool = row if KINDS[kind].parent is None else resource_access.parent_of(row)
    return int(tool.initiative_id)


def _not_offered() -> PluginDataError:
    return PluginDataError(PluginDataMessages.ACTION_NOT_OFFERED, 403)


async def run_action(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    action_id: str,
    kind: str,
    entity_id: int,
    context: GuildContext,
    user_id: int,
    age_allows: bool,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Run one of the install's actions on one item for the reader, and return
    the values the install shows on it afterwards, by key.

    ``session`` is the reader's, routed into the community, and ``context``
    their standing there. ``age_allows`` is whether the reader is old enough
    for the plug-in.
    """
    declared = (plugin.definition or {}).get("actions")
    action = next(
        (
            entry
            for entry in (declared if isinstance(declared, list) else [])
            if isinstance(entry, dict)
            and entry.get("id") == action_id
            and kind in (entry.get("on") or ())
        ),
        {},
    )
    write = next(
        (
            endpoint
            for endpoint in plugin_data._endpoints(plugin.definition)
            if endpoint.get("id") == action.get("endpoint")
            and endpoint.get("direction") == "write"
        ),
        None,
    )
    if write is None:
        raise PluginDataError(PluginDataMessages.ACTION_NOT_FOUND, 404)
    if not plugin.enabled:
        raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409)
    # A frozen community's content changes through nothing, a plug-in's
    # write included.
    if context.content_read_only:
        raise _not_offered()
    if not plugin_config.installation_meets(plugin, action.get("requires")):
        raise PluginDataError(PluginDataMessages.NEEDS_CONFIGURATION, 409)
    registration = await plugin_data._load_registration(
        None, guild_id=context.guild_id, plugin=plugin
    )

    install_id = int(plugin.id or 0)
    initiative_id = await _item_initiative(session, kind, entity_id, context)
    offered = guild_plugins.surface_access(
        {**guild_plugins.ITEM_SURFACE, "admin_only": is_admin_only(write)},
        initiative_id=initiative_id,
        placement_role_ids=await guild_plugins.placement_role_ids(
            session, install_id, initiative_id
        ),
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
        age_allows=age_allows,
    )
    if offered is SurfaceAccess.too_young:
        raise PluginDataError(GuildPluginMessages.AGE_RESTRICTED, 403)
    if offered is not SurfaceAccess.open:
        raise _not_offered()
    if not await _install_reads(
        plugin,
        registration,
        guild_id=context.guild_id,
        kind=kind,
        entity_id=entity_id,
    ):
        raise _not_offered()

    params, _ = plugin_data.validate_params(write, None)
    refs, fields = await plugin_data._resolve_connections(
        session, plugin=plugin, endpoint=write, user_id=None, actor="installation"
    )
    viewer = await ensure_plugin_ref(
        guild_id=context.guild_id, plugin_install_id=install_id, user_id=user_id
    )
    # Nothing is held open while the plug-in works, and what was read stays
    # readable; the next statement routes the session again.
    session.expunge_all()
    await session.rollback()

    async def read(request: httpx.Request | plugin_data.Answered) -> None:
        await plugin_data._read_body(request, transport=transport)

    await plugin_data._call_plugin(
        registration=registration,
        plugin=plugin,
        guild_id=context.guild_id,
        endpoint_id=str(write["id"]),
        params=params,
        refs=refs,
        fields=fields,
        transport=transport,
        read=read,
        viewer=viewer,
        subject={"type": kind, "id": entity_id},
    )
    # The action may have changed what the install's reads answer.
    plugin_data.clear_plugin_data_cache(guild_id=context.guild_id, plugin_id=install_id)

    rows = await session.exec(
        select(PluginMetadata.key, PluginMetadata.value).where(
            PluginMetadata.install_id == install_id,
            PluginMetadata.entity_type == kind,
            PluginMetadata.entity_id == entity_id,
            PluginMetadata.shown.is_(True),
        )
    )
    return dict(rows.all())
