"""Aggregate export sources: a whole initiative or a whole guild, one zip.

Two modes ride one selector (persisted in the job row, replayed by the
worker):

* ``backup`` — every included tool in its importable format (the per-tool
  JSON envelopes the single-entity exports emit), plus optionally the upload
  blobs the exported documents reference, indexed by a root ``manifest.json``
  (see ``schemas/tenant/backup_export.py``). One archive a future import
  wizard consumes whole.
* ``report`` — the same enumeration rendered in per-tool report formats
  chosen by the caller (a project PDF beside a queue CSV beside a calendar
  ICS), zipped with the same folder layout, no manifest/assets.

Layout (identical for both scopes — an initiative backup is a guild backup
with one ``initiatives/`` entry, so ONE import path serves both)::

    manifest.json                                   (backup mode)
    initiatives/{id}-{slug}/projects/{id}-{slug}.initiative-project.json
    initiatives/{id}-{slug}/documents/{id}-{slug}.json
    initiatives/{id}-{slug}/queues/{id}-{slug}.initiative-queue.json
    initiatives/{id}-{slug}/counter-groups/{id}-{slug}.initiative-counter-group.json
    initiatives/{id}-{slug}/calendars/{id}-{slug}.initiative-calendar.json
    assets/{storage_key}                            (include_uploads only)

Authorization: the initiative source requires the creator to reach each
initiative (``initiative_access`` — member, guild admin, or live PAM grant);
the guild source additionally requires the creator to be a guild ADMIN,
re-checked here so the worker's render-time replay fails closed if adminship
was revoked between request and render. Within an initiative, enumeration is
DAC-visible-only per tool, and every entity still passes its own
fetch+authorize seam. Projects are included with READ access — the
deliberate aggregate-export relaxation of the standalone write rule.

Long builds: the worker's creator-routed session enforces
``RLS_CONTEXT_MAX_AGE_SECONDS``; ``build`` re-validates via
``establish_guild_access`` between tool chunks (which also fails closed on
mid-build access revocation).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant.ical_service import documents_for_events
from app.core.user_display import handle_of
from app.core.config import settings
from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.services.export.contract import RenderItem, RenderRequest
from app.core.tools import BULK_EXPORT_TOOLS, Tool
from app.services.export.engine import ExportError
from app.services.export import delivery
from app.services.export.i18n import localize_now
from app.services.platform.csv_export import safe_filename_component

# Tool keys as they appear in the selector's include/formats maps. Derived:
# a backup covers what the engine can export, so a ninth tool is carried by
# registering it rather than by remembering this line.
_TOOLS = tuple(t.value for t in BULK_EXPORT_TOOLS)

# Report-mode format sets per tool (documents are per-type, validated below).
_REPORT_FORMATS: dict[str, frozenset[str]] = {
    "project": frozenset({"pdf", "csv", "xlsx"}),
    "queue": frozenset({"pdf", "csv", "xlsx", "md"}),
    "counter_group": frozenset({"pdf", "csv", "xlsx", "md"}),
    "calendar": frozenset({"ics", "json"}),
}
_DOCUMENT_REPORT_FORMATS: dict[str, frozenset[str]] = {
    "native": frozenset({"pdf", "md", "docx"}),
    "spreadsheet": frozenset({"csv", "xlsx"}),
}

# Per-item template overrides for report-mode PDFs.
_REPORT_TEMPLATES = {
    "project": "project-report",
    "queue": "data-table",
    "counter_group": "data-table",
    "document": "document",
}

# The ``tool`` an initiative's own files carry. Not a Tool: they describe the
# initiative rather than anything made inside it, which is also why the import
# side applies them ahead of every real tool.
_STRUCTURAL_TOOL = "initiative"

_MIB = 1_048_576
# Refresh the routed session's authorization context this often during a long
# build (see module docstring).
_REFRESH_EVERY = 25


class InitiativeExportAdapter:
    source = "initiative"
    template_id = "data-table"  # protocol requirement; items override per se
    formats = frozenset({"zip"})
    always_job = True
    force_zip = True

    @property
    def max_rows(self) -> int:
        return settings.EXPORT_MAX_BACKUP_ROWS

    async def count(self, session, *, user, guild_id, params, format) -> int:
        scope = await _resolve_scope(
            session, user, guild_id, params, scope_kind=self.source
        )
        return await _count_scope(
            session, user, guild_id, params, scope, scope_kind=self.source
        )

    async def build(self, session, *, user, guild_id, params, format) -> RenderRequest:
        scope = await _resolve_scope(
            session, user, guild_id, params, scope_kind=self.source
        )
        return await _build_scope(session, user, guild_id, params, scope, self.source)


class GuildExportAdapter(InitiativeExportAdapter):
    source = "guild"


# ---------------------------------------------------------------------------
# Scope resolution + authorization
# ---------------------------------------------------------------------------


async def _resolve_scope(
    session: AsyncSession, user: User, guild_id: int, params: dict, *, scope_kind: str
):
    """The initiatives this export covers, authorization included: guild scope
    demands the community's seat (re-checked on worker replay); initiative
    scope demands the creator reach the requested initiative. Returns the
    Initiative rows (name/flags feed the manifest)."""
    from sqlmodel import select

    from app.models.tenant.initiative import Initiative
    from app.models.platform.guild import GuildRole
    from app.services.membership import initiative_scope_clause
    from app.services.platform import guilds as guilds_service

    _validate_params(params, scope_kind=scope_kind)

    if scope_kind == "guild":
        membership = await guilds_service.get_membership(
            session, guild_id=guild_id, user_id=user.id
        )
        # The seat itself, held outright: the same rule the create endpoint
        # applies, re-asked here so a job outlives the request under the
        # authority it was started with and no other.
        if membership is None or membership.role is not GuildRole.superadmin:
            raise ExportError(
                ExportMessages.EXPORT_SUPERADMIN_REQUIRED, status_code=403
            )
        statement = (
            select(Initiative)
            .where(
                initiative_scope_clause(user.id, Initiative.id),
            )
            .order_by(Initiative.id.asc())
        )
        return list(await session.exec(statement))

    initiative_id = params.get("initiative_id")
    try:
        initiative_id = int(initiative_id)
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    statement = select(Initiative).where(
        Initiative.id == initiative_id,
        initiative_scope_clause(user.id, Initiative.id),
    )
    initiative = (await session.exec(statement)).one_or_none()
    if initiative is None:
        # Unreachable initiative — indistinguishable from absent (no leak).
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS, status_code=404)
    return [initiative]


def _validate_params(params: dict, *, scope_kind: str) -> None:
    mode = params.get("mode") or "backup"
    if mode not in ("backup", "report"):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    include = params.get("include")
    if include is not None:
        if (
            not isinstance(include, dict)
            or not set(include) <= set(_TOOLS)
            or not all(isinstance(v, bool) for v in include.values())
        ):
            raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    if mode == "report":
        for tool, fmt in (params.get("formats") or {}).items():
            if tool == "document":
                if not isinstance(fmt, dict) or not all(
                    doc_type in _DOCUMENT_REPORT_FORMATS
                    and value in _DOCUMENT_REPORT_FORMATS[doc_type]
                    for doc_type, value in fmt.items()
                ):
                    raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
            elif tool not in _REPORT_FORMATS or fmt not in _REPORT_FORMATS[tool]:
                raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)


def _included(params: dict, tool: str) -> bool:
    include = params.get("include")
    if include is None:
        return True
    return bool(include.get(tool, False))


def _include_uploads(params: dict) -> bool:
    mode = params.get("mode") or "backup"
    if mode == "report":
        # Report mode has no uploads toggle: file documents ride as their
        # original blobs whenever documents are included.
        return True
    return bool(params.get("include_uploads", True))


# ---------------------------------------------------------------------------
# Enumeration (shared by count / estimate / build)
# ---------------------------------------------------------------------------


async def _enumerate(
    session: AsyncSession, user: User, guild_id: int, params: dict, initiatives
) -> dict[str, dict[int, list[int]]]:
    """Per tool, per initiative: the entity ids the creator may export."""
    from app.services.tenant.calendars import list_calendar_ids_for_export
    from app.services.tenant.counters import list_counter_group_ids_for_export
    from app.services.tenant.dashboards import list_dashboard_ids_for_export
    from app.services.tenant.documents import list_document_ids_for_export
    from app.services.tenant.posts import list_post_ids_for_export
    from app.services.tenant.project_export import list_project_ids_for_export
    from app.services.tenant.queues import list_queue_ids_for_export
    from app.services.tenant.galleries import list_gallery_ids_for_export
    from app.services.tenant.wikis import list_wiki_ids_for_export

    ids: dict[str, dict[int, list[int]]] = {tool: {} for tool in _TOOLS}
    per_initiative_tools = {
        "project": lambda iids: list_project_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "document": lambda iids: list_document_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "queue": lambda iids: list_queue_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "counter_group": lambda iids: list_counter_group_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "post": lambda iids: list_post_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "wiki": lambda iids: list_wiki_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "gallery": lambda iids: list_gallery_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
        "dashboard": lambda iids: list_dashboard_ids_for_export(
            session, user, guild_id, initiative_ids=iids
        ),
    }
    for initiative in initiatives:
        for tool, enumerate_ids in per_initiative_tools.items():
            if not _included(params, tool):
                continue
            ids[tool][initiative.id] = await enumerate_ids([initiative.id])
        if _included(params, "calendar") and initiative.calendars_enabled:
            ids["calendar"][initiative.id] = await list_calendar_ids_for_export(
                session, user, guild_id, initiative_id=initiative.id
            )
    return ids


async def _count_scope(
    session: AsyncSession,
    user: User,
    guild_id: int,
    params: dict,
    initiatives,
    *,
    scope_kind: str = "initiative",
) -> int:
    """Row proxy: entities + tasks + (uploads MiB when they ride). Also
    enforces the uploads byte cap up front so an oversized backup 400s before
    a job row exists.

    Guild scope measures the WHOLE blob store, because that is what it bundles
    — the blobs documents reference plus the ones nothing points at. Counting
    only the referenced ones here would let an over-cap export through to the
    worker and fail it there instead of answering now."""
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.task import Task

    ids = await _enumerate(session, user, guild_id, params, initiatives)
    total = sum(
        len(v) for per_initiative in ids.values() for v in per_initiative.values()
    )

    project_ids = [pid for per in ids["project"].values() for pid in per]
    if project_ids:
        total += (
            await session.exec(
                select(func.count())
                .select_from(Task)
                .where(Task.project_id.in_(project_ids))
            )
        ).one()

    if _include_uploads(params) and (
        scope_kind == "guild" or _included(params, "document")
    ):
        if scope_kind == "guild":
            from app.services.tenant.attachments import get_guild_storage_usage

            upload_bytes = await get_guild_storage_usage(session)
        else:
            upload_bytes = await _known_upload_bytes(session, ids["document"])
        if upload_bytes > settings.EXPORT_MAX_BACKUP_UPLOAD_BYTES:
            raise ExportError(ExportMessages.EXPORT_TOO_LARGE)
        total += upload_bytes // _MIB
    return total


async def _known_upload_bytes(
    session: AsyncSession, document_ids: dict[int, list[int]]
) -> int:
    """File-document blob bytes for the enumerated documents (the cheap,
    pre-build number — embedded document images resolve at build time)."""
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.document import Document, DocumentType

    all_ids = [d for per in document_ids.values() for d in per]
    if not all_ids:
        return 0
    total = (
        await session.exec(
            select(func.coalesce(func.sum(Document.file_size), 0)).where(
                Document.id.in_(all_ids),
                Document.document_type == DocumentType.file,
            )
        )
    ).one()
    return int(total or 0)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def _build_scope(
    session: AsyncSession,
    user: User,
    guild_id: int,
    params: dict,
    initiatives,
    scope_kind: str,
) -> RenderRequest:
    from app.core.version import get_version
    from app.models.platform.guild import Guild
    from app.schemas.tenant.backup_export import (
        BACKUP_SCHEMA_VERSION,
        BackupManifest,
        ManifestGuild,
        ManifestInitiative,
    )

    mode = params.get("mode") or "backup"
    now = localize_now(datetime.now(timezone.utc), params.get("tz"))
    builder = _ScopeBuilder(
        session=session,
        user=user,
        guild_id=guild_id,
        params=params,
        now=now,
        mode=mode,
    )
    for initiative in initiatives:
        await builder.add_initiative(initiative)
    # The community itself, after its initiatives: what it owns directly.
    await builder.add_guild_sections(scope_kind)
    if scope_kind == "guild":
        await builder.add_remaining_uploads()

    items = builder.items
    if mode == "backup":
        guild = await session.get(Guild, guild_id)
        manifest = BackupManifest(
            type=f"{scope_kind}-backup",
            schema_version=BACKUP_SCHEMA_VERSION,
            app_version=get_version(),
            exported_at=datetime.now(timezone.utc),
            exported_by_handle=handle_of(user),
            source_instance_url=settings.APP_URL,
            guild=ManifestGuild(
                id=guild_id,
                name=guild.name if guild else "",
                description=guild.description if guild else None,
                is_community=bool(guild.is_community) if guild else False,
            ),
            include_uploads=_include_uploads(params),
            initiatives=[
                ManifestInitiative(
                    id=i.id,
                    name=i.name,
                    description=i.description,
                    color=i.color,
                    tools=_initiative_tool_states(params, i),
                )
                for i in initiatives
            ],
            guild_sections=builder.guild_sections,
            entries=builder.entries,
            assets=builder.assets,
            skipped=builder.skipped,
            people=builder.people(),
        )
        items = [
            RenderItem(
                key="manifest",
                data=manifest.model_dump(mode="json"),
                filename="manifest.json",
                format="json",
            ),
            *items,
        ]
    return RenderRequest(
        guild_id=guild_id,
        template_id="data-table",
        format="zip",
        batch=tuple(items),
    )


def _initiative_tool_states(params: dict, initiative) -> dict[str, str]:
    states: dict[str, str] = {}
    for tool in _TOOLS:
        # The switch column via the enum, not `tool + "s"`: the naive spelling
        # is wrong for `gallery`, and every tool now carries a column, so a
        # missing-attribute default would hide a real mismatch rather than
        # cover for the two that used to have none.
        flag = getattr(initiative, Tool(tool).view_permission)
        if not flag:
            states[tool] = "disabled"
        elif _included(params, tool):
            states[tool] = "included"
        else:
            states[tool] = "excluded"
    return states


def _permission_key(permission) -> str:
    """The permission's name — the enum's value, not its repr."""
    key = permission.permission_key
    return str(getattr(key, "value", key))


def _slug(entity_id: int, title: str) -> str:
    return f"{entity_id}-{safe_filename_component(title).lower() or 'untitled'}"


class _ScopeBuilder:
    """Accumulates render items + manifest records, one initiative at a time,
    refreshing the routed session's authorization between chunks."""

    def __init__(self, *, session, user, guild_id, params, now, mode):
        self.session = session
        self.user = user
        self.guild_id = guild_id
        self.params = params
        self.now = now
        self.mode = mode
        self.items: list[RenderItem] = []
        self.entries: list = []
        self.assets: list = []
        self.skipped: list = []
        self.guild_sections: list = []
        # Handle -> (display name, comments seen). Accumulated as the project
        # envelopes are built, because that is where comment authors are, and
        # written into the manifest so the import plan can ask about them
        # without opening a single envelope.
        self._people: dict[str, tuple[str | None, int]] = {}
        self._asset_index: dict[str, Any] = {}
        self._asset_bytes = 0
        self._since_refresh = 0

    async def _refresh_access(self, force: bool = False) -> None:
        """Re-validate the creator's guild access mid-build — keeps a long
        build under RLS_CONTEXT_MAX_AGE_SECONDS and fails closed if access
        was revoked while the job ran. always_job guarantees this session is
        the worker's own, never a request session."""
        self._since_refresh += 1
        if not force and self._since_refresh < _REFRESH_EVERY:
            return
        from app.api.deps import establish_guild_access
        from app.db.session import SYSTEM_SATISFIED

        await establish_guild_access(
            self.session,
            self.user,
            self.guild_id,
            satisfied_providers=SYSTEM_SATISFIED,
        )
        self._since_refresh = 0

    async def add_initiative(self, initiative) -> None:
        await self._refresh_access(force=True)
        folder = f"initiatives/{_slug(initiative.id, initiative.name)}"
        await self._add_projects(initiative, folder)
        await self._add_documents(initiative, folder)
        await self._add_queues(initiative, folder)
        await self._add_counter_groups(initiative, folder)
        await self._add_calendars(initiative, folder)
        await self._add_posts(initiative, folder)
        await self._add_wikis(initiative, folder)
        await self._add_galleries(initiative, folder)
        await self._add_dashboards(initiative, folder)
        await self._add_initiative_structure(initiative, folder)
        await self._add_initiative_properties(initiative, folder)
        await self._link_wiki_documents(initiative)

    # -- per-tool chunks -----------------------------------------------------

    async def _add_projects(self, initiative, folder: str) -> None:
        if not _included(self.params, "project"):
            return
        from app.api.v1.tenant_endpoints.projects import build_project_export_for_user
        from app.services.export.adapters.project import build_project_item
        from app.services.tenant.project_export import list_project_ids_for_export

        fmt = self._tool_format("project", default="json")
        for project_id in await list_project_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            envelope = await build_project_export_for_user(
                self.session,
                self.user,
                self.guild_id,
                project_id=project_id,
                access="read",  # the aggregate-export relaxation
            )
            self._record_people(envelope)
            item = build_project_item(envelope, fmt, self.user, self.now)
            path_stem = f"{folder}/projects/{_slug(project_id, envelope.project.name)}"
            if fmt == "json":
                path = f"{path_stem}.initiative-project.json"
                self._append_backup(
                    item,
                    path=path,
                    tool="project",
                    type="initiative-project",
                    schema_version=envelope.schema_version,
                    entity_id=project_id,
                    title=envelope.project.name,
                    initiative_id=initiative.id,
                )
            else:
                self._append_report(item, f"{path_stem}.{fmt}", fmt, "project")

    async def _add_documents(self, initiative, folder: str) -> None:
        if not _included(self.params, "document"):
            return
        from app.models.tenant.document import DocumentType
        from app.schemas.tenant.backup_export import ManifestSkipped
        from app.services.export.adapters.document import build_document_item
        from app.services.export.i18n import export_locale
        from app.services.tenant.documents import (
            get_document_for_export,
            list_document_ids_for_export,
        )

        loc = export_locale(self.user)
        date = self.now.strftime("%Y-%m-%d")
        doc_formats = self._document_formats()
        for document_id in await list_document_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            document = await get_document_for_export(
                self.session, self.user, self.guild_id, document_id=document_id
            )
            doc_type = (
                document.document_type.value
                if hasattr(document.document_type, "value")
                else str(document.document_type)
            )
            path_stem = f"{folder}/documents/{_slug(document.id, document.name)}"

            if doc_type == DocumentType.file.value:
                if not _include_uploads(self.params):
                    self.skipped.append(
                        ManifestSkipped(
                            tool="document",
                            entity_id=document.id,
                            title=document.name,
                            initiative_id=initiative.id,
                            reason="uploads_excluded",
                        )
                    )
                    continue
                self._add_file_document(
                    document, initiative, path_stem, _document_metadata(document)
                )
                continue

            # Report mode offers per-type choices for native/spreadsheet;
            # everything else (whiteboards, smart links) rides as its
            # canonical json envelope in both modes.
            fmt = (
                "json"
                if self.mode == "backup" or doc_type not in doc_formats
                else doc_formats[doc_type]
            )
            item = build_document_item(
                document, fmt, guild_id=self.guild_id, date=date, loc=loc
            )
            if fmt == "json":
                path = f"{path_stem}.json"
                await self._collect_embedded_assets(document, doc_type, path)
                self._append_backup(
                    item,
                    path=path,
                    tool="document",
                    type="initiative-document",
                    schema_version=1,
                    entity_id=document.id,
                    title=document.name,
                    initiative_id=initiative.id,
                )
            else:
                self._append_report(item, f"{path_stem}.{fmt}", fmt, "document")

    def _add_file_document(
        self, document, initiative, path_stem: str, metadata
    ) -> None:
        from app.schemas.tenant.backup_export import ManifestEntry

        storage_key = (document.file_url or "").split("/")[-1]
        asset_path = self._register_asset(
            storage_key,
            original_filename=document.original_filename,
            content_type=document.file_content_type,
            size_bytes=int(document.file_size or 0),
            referenced_by=path_stem,
        )
        if self.mode == "backup":
            self.entries.append(
                ManifestEntry(
                    path=asset_path,
                    tool="document",
                    type="file",
                    schema_version=None,
                    entity_id=document.id,
                    title=document.name,
                    initiative_id=initiative.id,
                    tags=metadata["tags"],
                    properties=metadata["properties"],
                    asset=asset_path,
                )
            )

    async def _add_queues(self, initiative, folder: str) -> None:
        if not _included(self.params, "queue"):
            return
        from app.services.export.adapters.queue import build_queue_item
        from app.services.export.adapters.queue import queue_attachments_for
        from app.services.tenant.queues import (
            get_queue_for_export,
            list_queue_ids_for_export,
        )

        fmt = self._tool_format("queue", default="json")
        for queue_id in await list_queue_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            queue = await get_queue_for_export(
                self.session, self.user, self.guild_id, queue_id=queue_id
            )
            attachments = await queue_attachments_for(self.session, queue.items)
            item = build_queue_item(queue, fmt, self.user, self.now, attachments)
            path_stem = f"{folder}/queues/{_slug(queue.id, queue.name)}"
            if fmt == "json":
                self._append_backup(
                    item,
                    path=f"{path_stem}.initiative-queue.json",
                    tool="queue",
                    type="initiative-queue",
                    schema_version=1,
                    entity_id=queue.id,
                    title=queue.name,
                    initiative_id=initiative.id,
                )
            else:
                self._append_report(item, f"{path_stem}.{fmt}", fmt, "queue")

    async def _add_counter_groups(self, initiative, folder: str) -> None:
        if not _included(self.params, "counter_group"):
            return
        from app.services.export.adapters.counter_group import build_counter_group_item
        from app.services.tenant.counters import (
            get_counter_group_for_export,
            list_counter_group_ids_for_export,
        )

        fmt = self._tool_format("counter_group", default="json")
        for group_id in await list_counter_group_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            group = await get_counter_group_for_export(
                self.session, self.user, self.guild_id, group_id=group_id
            )
            item = build_counter_group_item(group, fmt, self.user, self.now)
            path_stem = f"{folder}/counter-groups/{_slug(group.id, group.name)}"
            if fmt == "json":
                self._append_backup(
                    item,
                    path=f"{path_stem}.initiative-counter-group.json",
                    tool="counter_group",
                    type="initiative-counter-group",
                    schema_version=1,
                    entity_id=group.id,
                    title=group.name,
                    initiative_id=initiative.id,
                )
            else:
                self._append_report(item, f"{path_stem}.{fmt}", fmt, "counter_group")

    async def _add_posts(self, initiative, folder: str) -> None:
        """Every notice on this initiative's board.

        JSON only — a post exports as its importable envelope, the way a
        whiteboard document does. There is no report shape for a notice, so a
        report-mode export leaves the board out entirely rather than dropping
        a lone JSON file into a zip of PDFs and spreadsheets. That is also why
        ``_REPORT_FORMATS`` has no ``post`` entry: nothing to offer.
        """
        if self.mode != "backup":
            return
        if not _included(self.params, "post"):
            return
        if not initiative.posts_enabled:
            return
        from app.services.export.adapters.post import build_post_item
        from app.services.tenant.posts import (
            get_post_for_export,
            list_post_ids_for_export,
        )

        for post_id in await list_post_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            post = await get_post_for_export(
                self.session, self.user, self.guild_id, post_id=post_id
            )
            item = build_post_item(post, "json", self.now)
            path_stem = f"{folder}/posts/{_slug(post.id, post.name)}"
            self._append_backup(
                item,
                path=f"{path_stem}.initiative-post.json",
                tool="post",
                type="initiative-post",
                schema_version=1,
                entity_id=post.id,
                title=post.name,
                initiative_id=initiative.id,
            )

    async def _add_wikis(self, initiative, folder: str) -> None:
        """Every wiki in this initiative, with its pages and their shape.

        JSON only, for the reason a notice is: a wiki's export is its
        importable envelope, and there is no report shape for one — so a
        report-mode export leaves wikis out rather than dropping a lone JSON
        file into a zip of PDFs.
        """
        if self.mode != "backup":
            return
        if not _included(self.params, "wiki"):
            return
        if not initiative.wikis_enabled:
            return
        from app.services.export.adapters.wiki import build_wiki_item
        from app.services.tenant.wikis import (
            get_wiki_for_export,
            list_wiki_ids_for_export,
        )

        for wiki_id in await list_wiki_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            wiki, pages = await get_wiki_for_export(
                self.session, self.user, self.guild_id, wiki_id=wiki_id
            )
            item = build_wiki_item(wiki, pages, self.now)
            path_stem = f"{folder}/wikis/{_slug(wiki.id, wiki.name)}"
            self._append_backup(
                item,
                path=f"{path_stem}.initiative-wiki.json",
                tool="wiki",
                type="initiative-wiki",
                schema_version=1,
                entity_id=wiki.id,
                title=wiki.name,
                initiative_id=initiative.id,
            )

    def _record_people(self, envelope) -> None:
        """Note everyone a project envelope names, and how often they are
        quoted.

        Counted per handle across the whole archive rather than per project:
        the importer answers "who is this" once, and one answer covers every
        comment and every assignment that name is on. An assignee who wrote
        nothing is listed with a count of none — the restore still has to be
        told who they are, or their tasks arrive unassigned.
        """
        for task in envelope.tasks:
            for comment in task.comments:
                handle = (comment.author_handle or "").strip()
                if not handle:
                    continue
                name, count = self._people.get(handle, (None, 0))
                self._people[handle] = (name or comment.author_name, count + 1)
            for raw in task.assignee_handles:
                handle = (raw or "").strip()
                if handle and handle not in self._people:
                    self._people[handle] = (None, 0)

    def _record_property_people(self, *payloads) -> None:
        """Note everyone a user-type property value names, in any entry.

        Every tool's properties pass through here — a task's, a document's,
        an event's, a file document's — because a restore places those values
        through the people step's answer, and the step only asks about the
        people the manifest lists. Counted as quoting nothing, like an
        assignee: the number is for comments.
        """
        from app.services.import_engine.people import user_reference_handles

        for payload in payloads:
            for handle in user_reference_handles(payload):
                if handle not in self._people:
                    self._people[handle] = (None, 0)

    def people(self) -> list:
        """The archive's people, most-quoted first — which is the order the
        wizard should ask about them in."""
        from app.schemas.tenant.backup_export import ManifestPerson

        return [
            ManifestPerson(handle=handle, name=name, comment_count=count)
            for handle, (name, count) in sorted(
                self._people.items(), key=lambda kv: (-kv[1][1], kv[0])
            )
        ]

    async def _link_wiki_documents(self, initiative) -> None:
        """Say which wiki each file document sits in, now that both entries
        exist.

        A document joins a wiki by an edge (``document part_of wiki``), not
        by a column, and the edge names rows this archive is about to stop
        being able to identify. So it crosses as ``attach_to`` on the
        document's own entry, naming the wiki by **entry path** — which is
        the one thing both sides agree on — and the importer rebuilds the
        edge once both ends have been applied.

        Runs after both tools have been written for this initiative, because
        documents are added before wikis and a path cannot be named before it
        exists. A document in more than one wiki keeps the first: one entry
        carries one placement, and a second copy of the file is not what the
        edge said. The page it is filed under in that wiki travels with it, by
        the page's slug.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.core.relationships import RelationshipType, node_id
        from app.core.search import SearchEntityType
        from app.models.tenant.relationship import EntityRelationship
        from app.schemas.tenant.backup_export import ManifestAttachTo

        wiki_paths = {
            entry.entity_id: entry.path
            for entry in self.entries
            if entry.tool == "wiki"
            and entry.type == "initiative-wiki"
            and entry.initiative_id == initiative.id
        }
        file_entries = {
            entry.entity_id: entry
            for entry in self.entries
            if entry.type == "file" and entry.initiative_id == initiative.id
        }
        if not wiki_paths or not file_entries:
            return

        edges = (
            await self.session.exec(
                select(EntityRelationship).where(
                    EntityRelationship.source_node.in_(
                        [
                            node_id(SearchEntityType.document, document_id)
                            for document_id in file_entries
                        ]
                    ),
                    EntityRelationship.target_node.in_(
                        [
                            node_id(SearchEntityType.wiki, wiki_id)
                            for wiki_id in wiki_paths
                        ]
                    ),
                    EntityRelationship.relationship_type
                    == RelationshipType.part_of.value,
                    EntityRelationship.removed_at.is_(None),
                )
            )
        ).all()
        # The page each document is filed under, by the slug its page is
        # written with in the wiki's envelope.
        from app.models.tenant.wiki import Wiki, WikiPage
        from app.services.tenant.wikis import document_parent

        wikis = {
            wiki.id: wiki
            for wiki in (
                await self.session.exec(
                    select(Wiki).where(Wiki.id.in_(list(wiki_paths)))
                )
            ).all()
        }
        page_slugs = dict(
            (
                await self.session.exec(
                    select(WikiPage.id, WikiPage.slug).where(
                        WikiPage.wiki_id.in_(list(wiki_paths))
                    )
                )
            ).all()
        )
        for edge in edges:
            entry = file_entries.get(edge.source_id)
            path = wiki_paths.get(edge.target_id)
            if entry is None or path is None or entry.attach_to is not None:
                continue
            wiki = wikis.get(edge.target_id)
            parent = document_parent(wiki, edge.source_id) if wiki else None
            entry.attach_to = ManifestAttachTo(
                kind="wiki", ref=path, page=page_slugs.get(parent) if parent else None
            )

    async def _add_galleries(self, initiative, folder: str) -> None:
        """Every gallery in this initiative: one envelope each, and its
        pictures' bytes registered as assets.

        A gallery is mostly blobs, so it obeys the uploads toggle the way a
        file document does — excluded uploads means the pictures do not
        travel, and a gallery of captions without them is not worth writing,
        so the whole gallery is recorded as skipped instead.
        """
        if self.mode != "backup":
            return
        if not _included(self.params, "gallery"):
            return
        if not initiative.galleries_enabled:
            return
        from app.schemas.tenant.backup_export import ManifestSkipped
        from app.services.export.adapters.gallery import (
            build_gallery_item,
            storage_key_of,
        )
        from app.services.tenant.galleries import (
            get_gallery_for_export,
            list_gallery_ids_for_export,
        )

        for gallery_id in await list_gallery_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        ):
            await self._refresh_access()
            gallery, images = await get_gallery_for_export(
                self.session, self.user, self.guild_id, gallery_id=gallery_id
            )
            if not _include_uploads(self.params):
                self.skipped.append(
                    ManifestSkipped(
                        tool="gallery",
                        entity_id=gallery.id,
                        title=gallery.name,
                        initiative_id=initiative.id,
                        reason="uploads_excluded",
                    )
                )
                continue
            item = build_gallery_item(gallery, images, self.now)
            path_stem = f"{folder}/galleries/{_slug(gallery.id, gallery.name)}"
            path = f"{path_stem}.initiative-gallery.json"
            for image in images:
                key = storage_key_of(image.file_url)
                if not key:
                    continue
                # The picture only; a thumbnail is a rendition the app makes
                # again from it.
                self._register_asset(
                    key,
                    original_filename=image.original_filename,
                    content_type=image.file_content_type,
                    size_bytes=int(image.file_size or 0),
                    referenced_by=path,
                )
            self._append_backup(
                item,
                path=path,
                tool="gallery",
                type="initiative-gallery",
                schema_version=1,
                entity_id=gallery.id,
                title=gallery.name,
                initiative_id=initiative.id,
            )

    async def _add_calendars(self, initiative, folder: str) -> None:
        if not _included(self.params, "calendar"):
            return
        if not initiative.calendars_enabled:
            return
        from app.services.export.adapters.calendar import build_calendar_item
        from app.services.tenant.calendars import (
            get_calendar_for_export,
            list_calendar_ids_for_export,
        )

        fmt = self._tool_format("calendar", default="json")
        date = self.now.strftime("%Y-%m-%d")
        for calendar_id in await list_calendar_ids_for_export(
            self.session, self.user, self.guild_id, initiative_id=initiative.id
        ):
            await self._refresh_access()
            calendar = await get_calendar_for_export(
                self.session, self.user, self.guild_id, calendar_id=calendar_id
            )
            documents_by_event = await documents_for_events(
                self.session, list(calendar.events)
            )
            item = build_calendar_item(calendar, fmt, date, documents_by_event)
            path_stem = f"{folder}/calendars/{_slug(calendar.id, calendar.name)}"
            if fmt == "json":
                self._append_backup(
                    item,
                    path=f"{path_stem}.initiative-calendar.json",
                    tool="calendar",
                    type="initiative-calendar",
                    schema_version=1,
                    entity_id=calendar.id,
                    title=calendar.name,
                    initiative_id=initiative.id,
                )
            else:  # ics
                self._append_report(item, f"{path_stem}.{fmt}", fmt, "calendar")

    # -- helpers ---------------------------------------------------------------

    def _tool_format(self, tool: str, *, default: str) -> str:
        if self.mode == "backup":
            return default
        formats = self.params.get("formats") or {}
        value = formats.get(tool)
        if tool == "document" or not isinstance(value, str):
            return default
        return value

    def _document_formats(self) -> dict[str, str]:
        if self.mode == "backup":
            return {}
        formats = self.params.get("formats") or {}
        value = formats.get("document")
        return dict(value) if isinstance(value, dict) else {}

    async def _add_dashboards(self, initiative, folder: str) -> None:
        """Dashboards, minus any built on an app this build does not ship.

        ``list_dashboard_ids_for_export`` applies the provenance filter, so
        the skipped ones are recovered here separately in order to record
        them: an archive that just omitted them would not say they existed.
        Report mode has no dashboard format — a dashboard is a live canvas,
        not a document — so it carries the envelope in both modes.
        """
        if not _included(self.params, "dashboard"):
            return
        if not getattr(initiative, "dashboards_enabled", False):
            return
        from sqlmodel import select

        from app.models.tenant.dashboard import Dashboard
        from app.schemas.tenant.backup_export import ManifestSkipped
        from app.services.export.adapters.dashboard import build_dashboard_item
        from app.services.export.provenance import THIRD_PARTY_REASON
        from app.services.tenant.dashboards import (
            get_dashboard_for_export,
            list_dashboard_ids_for_export,
        )

        exportable = await list_dashboard_ids_for_export(
            self.session, self.user, self.guild_id, initiative_ids=[initiative.id]
        )
        for dashboard_id in exportable:
            await self._refresh_access()
            dashboard = await get_dashboard_for_export(
                self.session, self.user, self.guild_id, dashboard_id=dashboard_id
            )
            item = build_dashboard_item(dashboard, self.now.strftime("%Y-%m-%d"))
            path = (
                f"{folder}/dashboards/"
                f"{_slug(dashboard_id, dashboard.name)}.initiative-dashboard.json"
            )
            self._append_backup(
                item,
                path=path,
                tool="dashboard",
                type="initiative-dashboard",
                schema_version=1,
                entity_id=dashboard_id,
                title=dashboard.name,
                initiative_id=initiative.id,
            )
        if self.mode != "backup":
            return
        kept = set(exportable)
        rows = await self.session.exec(
            select(Dashboard.id, Dashboard.name).where(
                Dashboard.initiative_id == initiative.id
            )
        )
        for dashboard_id, name in rows:
            if dashboard_id in kept:
                continue
            self.skipped.append(
                ManifestSkipped(
                    tool="dashboard",
                    entity_id=dashboard_id,
                    title=name,
                    initiative_id=initiative.id,
                    reason=THIRD_PARTY_REASON,
                )
            )

    async def _add_initiative_structure(self, initiative, folder: str) -> None:
        """The initiative itself: who was in it, the roles they held, and what
        each role could do.

        Tool envelopes carry content and name people by handle; none of them
        carries the access structure the content sat inside. Without it a
        restored initiative is a pile of work with nobody in it.

        Report mode skips this — it renders content for people to read, and a
        role matrix is not a report.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.core.user_display import handle_of
        from app.models.platform.user_profile_view import GuildMember
        from app.models.tenant.initiative import (
            InitiativeMember,
            InitiativeRoleModel,
            InitiativeRolePermission,
        )

        roles = list(
            await self.session.exec(
                select(InitiativeRoleModel)
                .where(InitiativeRoleModel.initiative_id == initiative.id)
                .order_by(InitiativeRoleModel.position.asc())
            )
        )
        permissions: dict[int, list] = {}
        if roles:
            rows = await self.session.exec(
                select(InitiativeRolePermission).where(
                    InitiativeRolePermission.initiative_role_id.in_(
                        [r.id for r in roles]
                    )
                )
            )
            for permission in rows:
                permissions.setdefault(permission.initiative_role_id, []).append(
                    permission
                )

        members = list(
            await self.session.exec(
                select(InitiativeMember)
                .where(InitiativeMember.initiative_id == initiative.id)
                .order_by(InitiativeMember.user_id.asc())
            )
        )
        profiles = {}
        if members:
            # The projection already narrowed to this guild's members; an
            # initiative's roster is a subset of it.
            profiles = {
                profile.id: profile
                for profile in await self.session.exec(select(GuildMember))
            }
        if not roles and not members:
            return

        role_names = {role.id: role.name for role in roles}
        payload = {
            "type": "initiative-structure",
            "schema_version": 1,
            "initiative_id": initiative.id,
            "name": initiative.name,
            "roles": [
                {
                    "name": role.name,
                    "display_name": role.display_name,
                    "is_builtin": role.is_builtin,
                    "is_manager": role.is_manager,
                    "override_share_restrictions": role.override_share_restrictions,
                    "position": role.position,
                    # Permission keys by name, enabled-only: a role is what it
                    # CAN do, and a disabled row is the default restated.
                    "permissions": sorted(
                        _permission_key(p)
                        for p in permissions.get(role.id, [])
                        if p.enabled
                    ),
                }
                for role in roles
            ],
            "members": [
                {
                    "user_id": member.user_id,
                    "handle": handle_of(profiles[member.user_id])
                    if member.user_id in profiles
                    else None,
                    "name": getattr(profiles.get(member.user_id), "full_name", None),
                    # By role NAME: role ids are per-initiative and mean
                    # nothing once the archive is opened somewhere else.
                    "role": role_names.get(member.role_id),
                    "joined_at": member.joined_at.isoformat()
                    if member.joined_at
                    else None,
                }
                for member in members
            ],
        }
        path = f"{folder}/structure.json"
        self._append_backup(
            RenderItem(key=path, data=payload, filename=path, format="json"),
            path=path,
            tool=_STRUCTURAL_TOOL,
            type="initiative-structure",
            schema_version=1,
            entity_id=initiative.id,
            title=initiative.name,
            initiative_id=initiative.id,
        )

    async def _add_initiative_properties(self, initiative, folder: str) -> None:
        """The initiative's property definitions.

        Envelopes carry property VALUES by name and type; the definitions are
        what say a property exists at all, what a select may be set to, and
        what order they read in. Without them an import rebuilds a definition
        from the first value it sees, so a select arrives holding only the
        options somebody happened to use.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.models.tenant.property import PropertyDefinition

        rows = list(
            await self.session.exec(
                select(PropertyDefinition)
                .where(PropertyDefinition.initiative_id == initiative.id)
                .order_by(PropertyDefinition.position.asc())
            )
        )
        if not rows:
            return
        payload = {
            "type": "initiative-properties",
            "schema_version": 1,
            "initiative_id": initiative.id,
            "properties": [
                {
                    "name": row.name,
                    "type": row.type.value,
                    "position": float(row.position),
                    "color": row.color,
                    "options": list(row.options or []),
                }
                for row in rows
            ],
        }
        path = f"{folder}/properties.json"
        self._append_backup(
            RenderItem(key=path, data=payload, filename=path, format="json"),
            path=path,
            tool=_STRUCTURAL_TOOL,
            type="initiative-properties",
            schema_version=1,
            entity_id=initiative.id,
            title=initiative.name,
            initiative_id=initiative.id,
        )

    async def add_guild_sections(self, scope_kind: str) -> None:
        """What the community owns outside any initiative.

        Backup mode only, and gated by each section's own scope — see
        ``guild_sections.GuildSection.scopes``.
        """
        if self.mode != "backup":
            return
        from app.schemas.tenant.backup_export import ManifestGuildSection
        from app.services.export.guild_sections import SectionContext, sections_for

        # The manifest's own list, so anything a section leaves out is
        # reported beside everything else that was.
        ctx = SectionContext(
            session=self.session,
            user=self.user,
            guild_id=self.guild_id,
            skipped=self.skipped,
        )
        for section in sections_for(scope_kind):
            await self._refresh_access()
            built = await section.build(ctx)
            if built is None:  # nothing of this kind — absent reads as none
                continue
            payload, count = built
            self.items.append(
                RenderItem(
                    key=section.path,
                    data=payload,
                    filename=section.path,
                    format="json",
                )
            )
            self.guild_sections.append(
                ManifestGuildSection(key=section.key, path=section.path, count=count)
            )

    async def add_remaining_uploads(self) -> None:
        """Every blob in the guild's store that nothing already pulled in.

        Assets otherwise ride with the entity that references them, so a file
        nobody currently points at — an image removed from a page, anything
        uploaded and not yet placed — would be the one thing a "full backup"
        silently dropped. Guild scope only: the store is guild-wide, and an
        initiative export has no claim on it.
        """
        if self.mode != "backup" or not _include_uploads(self.params):
            return
        from sqlmodel import select

        from app.models.tenant.upload import Upload

        rows = await self.session.exec(
            select(Upload.filename, Upload.size_bytes, Upload.content_type).order_by(
                Upload.id.asc()
            )
        )
        for storage_key, size_bytes, content_type in rows:
            if storage_key in self._asset_index:
                continue
            await self._refresh_access()
            self._register_asset(
                storage_key,
                original_filename=None,
                content_type=content_type,
                size_bytes=int(size_bytes or 0),
                referenced_by=None,
            )

    def _append_backup(self, item: RenderItem, *, path: str, **entry_kwargs) -> None:
        self._record_property_people(item.data, entry_kwargs.get("properties"))
        self.items.append(replace(item, filename=path, format="json"))
        if self.mode == "backup":
            from app.schemas.tenant.backup_export import ManifestEntry

            self.entries.append(ManifestEntry(path=path, **entry_kwargs))

    def _append_report(self, item: RenderItem, path: str, fmt: str, tool: str) -> None:
        self.items.append(
            replace(
                item,
                filename=path,
                format=fmt,
                template_id=_REPORT_TEMPLATES.get(tool),
            )
        )

    async def _collect_embedded_assets(
        self, document, doc_type: str, entry_path: str
    ) -> None:
        """Native documents can embed same-guild images; when uploads ride,
        those blobs join the archive too — at their REAL stored size, so they
        count against the byte cap exactly like file-document blobs (the
        pre-flight count only sees file documents, so build is where embedded
        bytes get bounded; an over-cap build fails the job closed)."""
        if doc_type != "native" or not _include_uploads(self.params):
            return
        from app.services.export.lexical import blocks_from_editor_state

        _, assets = blocks_from_editor_state(
            document.content or {}, guild_id=self.guild_id
        )
        if not assets:
            return
        uploads = await self._upload_rows(
            [a["key"] for a in assets if a["key"] not in self._asset_index]
        )
        for asset in assets:
            size_bytes, content_type = uploads.get(asset["key"], (0, None))
            self._register_asset(
                asset["key"],
                original_filename=asset.get("name"),
                content_type=content_type,
                size_bytes=size_bytes,
                referenced_by=entry_path,
            )

    async def _upload_rows(self, storage_keys: list) -> dict:
        """Stored size + content type per storage key (``uploads.filename`` IS
        the storage key). Legacy blobs without an uploads row contribute 0."""
        if not storage_keys:
            return {}
        from sqlmodel import select

        from app.models.tenant.upload import Upload

        rows = await self.session.exec(
            select(Upload.filename, Upload.size_bytes, Upload.content_type).where(
                Upload.filename.in_(storage_keys)
            )
        )
        return {
            filename: (int(size or 0), content_type)
            for filename, size, content_type in rows
        }

    def _register_asset(
        self,
        storage_key: str,
        *,
        original_filename,
        content_type,
        size_bytes: int,
        referenced_by: str | None,
    ) -> str:
        from app.schemas.tenant.backup_export import ManifestAsset

        path = f"assets/{storage_key}"
        existing = self._asset_index.get(storage_key)
        if existing is not None:
            if referenced_by and referenced_by not in existing.referenced_by:
                existing.referenced_by.append(referenced_by)
            return path
        self._asset_bytes += size_bytes
        if self._asset_bytes > settings.EXPORT_MAX_BACKUP_UPLOAD_BYTES:
            raise ExportError(ExportMessages.EXPORT_TOO_LARGE)
        record = ManifestAsset(
            path=path,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            referenced_by=[referenced_by] if referenced_by else [],
        )
        self._asset_index[storage_key] = record
        if self.mode == "backup":
            self.assets.append(record)
        self.items.append(
            RenderItem(
                key=path,
                data={
                    "storage_key": storage_key,
                    "filename": original_filename or storage_key,
                    "content_type": content_type,
                },
                filename=path,
                format="file",
            )
        )
        return path


def _document_metadata(document) -> dict:
    from app.services.export.property_values import property_export_dict

    return {
        "tags": sorted(tag.name for tag in document.tags or []),
        "properties": [
            property_export_dict(pv)
            for pv in document.property_values or []
            if pv.property_definition is not None
        ],
    }


# ---------------------------------------------------------------------------
# Estimate (the wizard's pre-flight numbers)
# ---------------------------------------------------------------------------


async def estimate_backup(
    session: AsyncSession,
    user: User,
    guild_id: int,
    *,
    scope: str,
    initiative_id: int | None,
    include_uploads: bool,
):
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.document import Document, DocumentType
    from app.models.tenant.task import Task
    from app.schemas.tenant.backup_export import BackupEstimate, BackupToolEstimate
    from app.services.tenant.attachments import get_guild_storage_usage

    params = {"initiative_id": initiative_id, "include_uploads": include_uploads}
    initiatives = await _resolve_scope(
        session, user, guild_id, params, scope_kind=scope
    )
    ids = await _enumerate(session, user, guild_id, params, initiatives)

    tools: dict[str, BackupToolEstimate] = {}
    estimated_rows = 0
    for tool in _TOOLS:
        count = sum(len(v) for v in ids[tool].values())
        # Core tools (project, document) have no flag column — getattr's
        # default keeps them permanently enabled.
        disabled = all(not getattr(i, f"{tool}s_enabled", True) for i in initiatives)
        tools[tool] = BackupToolEstimate(count=count, disabled=disabled)
        estimated_rows += count

    project_ids = [pid for per in ids["project"].values() for pid in per]
    if project_ids:
        estimated_rows += (
            await session.exec(
                select(func.count())
                .select_from(Task)
                .where(Task.project_id.in_(project_ids))
            )
        ).one()

    uploads_count = 0
    uploads_bytes = 0
    if include_uploads:
        document_ids = [d for per in ids["document"].values() for d in per]
        if document_ids:
            uploads_count = (
                await session.exec(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        Document.id.in_(document_ids),
                        Document.document_type == DocumentType.file,
                    )
                )
            ).one()
        if scope == "guild":
            # Exact total blob usage — an upper bound on what ships.
            uploads_bytes = await get_guild_storage_usage(session)
        else:
            uploads_bytes = await _known_upload_bytes(session, ids["document"])
        estimated_rows += uploads_bytes // _MIB

    return BackupEstimate(
        tools=tools,
        uploads_count=uploads_count,
        uploads_bytes=uploads_bytes,
        uploads_approximate=True,
        estimated_rows=estimated_rows,
        max_rows=settings.EXPORT_MAX_BACKUP_ROWS,
        max_upload_bytes=settings.EXPORT_MAX_BACKUP_UPLOAD_BYTES,
        max_download_bytes=settings.EXPORT_MAX_DOWNLOAD_BYTES,
        delivery_available=delivery.is_configured(),
    )
