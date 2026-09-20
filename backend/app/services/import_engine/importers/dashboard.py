"""``initiative-dashboard`` importer: the presentation spec and its canvas.

A dashboard owns no child content — the data it shows is fetched per viewer
through the tools it points at — so applying one is creating a single row.
What it does need is the definition put back through
``normalize_dashboard_definition``: an envelope is a file, and a file is not a
trusted source. That is the same validator the create endpoint runs, so an
imported dashboard cannot describe a widget the app has no renderer for.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import DashboardEnvelope
from app.services.import_engine.common import unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    grant_ownership,
    parse_envelope,
)


class DashboardImporter:
    envelope_type = "initiative-dashboard"
    permission = PermissionKey(Tool.dashboard.create_permission)

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(DashboardEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: DashboardEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        widgets = (envelope.definition or {}).get("widgets")
        return 1 + (len(widgets) if isinstance(widgets, list) else 0)

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: DashboardEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id

        existing_names = set(
            (
                await session.exec(
                    select(Dashboard.name).where(
                        Dashboard.initiative_id == target_initiative.id
                    )
                )
            ).all()
        )

        definition = await _normalized_definition(env.definition)
        listing_uid, listing_version = await _resolved_listing(
            session, env.listing_uid, env.listing_version
        )

        dashboard = Dashboard(
            name=unique_name(existing_names, env.name),
            description=env.description,
            initiative_id=target_initiative.id,
            guild_id=guild_id,
            created_by=importer.id,
            definition=definition,
            config=dict(env.config or {}),
            listing_uid=listing_uid,
            listing_version=listing_version,
        )
        session.add(dashboard)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.dashboard,
            entity_id=dashboard.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        await session.flush()
        return EnvelopeImportResult(
            entity_id=dashboard.id,
            entity_title=dashboard.name,
            created={"dashboards": 1},
        )


async def _normalized_definition(raw: dict[str, Any] | None) -> dict[str, Any]:
    """The envelope's definition, through the app's own validator.

    A definition naming a widget or binding this build has no renderer for —
    an archive from a newer version, or one that referenced an app that is not
    installed here — yields an empty canvas rather than failing the whole
    import: the dashboard arrives, empty, for somebody to rebuild, which is
    more use than losing it and everything queued behind it.
    """
    from app.services.tenant.dashboard_definition import (
        DashboardDefinitionError,
        normalize_dashboard_definition,
    )

    try:
        return normalize_dashboard_definition(raw or {})
    except DashboardDefinitionError:
        return normalize_dashboard_definition({})


async def _resolved_listing(
    session: AsyncSession, listing_uid: str | None, listing_version: str | None
) -> tuple[str | None, str | None]:
    """Keep the app reference only when this deployment ships that listing;
    otherwise the dashboard arrives as an ordinary one rather than pointing at
    a listing that is not here."""
    if not listing_uid:
        return None, None
    from app.services.export.provenance import builtin_listing_uids

    if listing_uid in await builtin_listing_uids(session, [listing_uid]):
        return listing_uid, listing_version
    return None, None
