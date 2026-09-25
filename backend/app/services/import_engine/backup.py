"""Backup-zip import: plan (pre-flight summary from ``manifest.json``) and
apply (the worker-side restore).

A backup is the export engine's zip: per-tool JSON envelopes under
``initiatives/{id}-{slug}/…`` indexed by a root manifest, plus optional
upload blobs under ``assets/``. Import creates **new initiatives** (names
suffixed on collision, tool switches from the manifest, the importer becomes
manager) — never merges — and dispatches every entry to the per-type
importer registry, so an envelope imports identically whether it arrives
alone or inside a backup.

How it runs:
* the zip is opened and each member read through ``zip_bounds``: the central
  directory is checked (member count, total declared size, relative names)
  before any member is read, and every member is read up to its cap;
* the plan step reads ONLY ``manifest.json`` — milliseconds, so it runs in
  the upload request (off the event loop);
* apply re-verifies the creator is a REAL guild admin (fail closed on
  revocation), restores assets under their original storage keys (embedded
  editor-state references resolve without rewriting) through
  ``archive_assets`` — each file checked for what it is, per-key dedup,
  storage-quota enforcement — and applies entries in per-entry savepoints —
  one corrupt entry fails alone, the job still completes with a report;
* long applies commit per chunk and refresh ``establish_guild_access``
  (RLS context is valid for at most RLS_CONTEXT_MAX_AGE_SECONDS).
"""

from __future__ import annotations

import asyncio
import logging
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.references import format_ref
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import BULK_EXPORT_TOOLS, Tool
from app.core.messages import ImportEngineMessages
from app.db.session import SYSTEM_SATISFIED
from app.models.platform.user import User
from app.schemas.tenant.backup_export import (
    BACKUP_SCHEMA_VERSION,
    MIN_SUPPORTED_IMPORT_VERSION,
    BackupManifest,
    ManifestEntry,
)
from app.schemas.tenant.import_job import (
    BackupImportPlan,
    BackupImportResult,
    BackupPlanInitiative,
    BackupPlanPerson,
    EntryResult,
)
from app.services.import_engine import engine as import_engine
from app.services.import_engine.archive_assets import (
    ArchiveAsset,
    remove_written,
    restore_assets,
)
from app.services.import_engine.common import handle_key, unique_name
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.context import (
    ImportContext,
    excluded_property_names,
    exported_from_here,
)
from app.services.import_engine.links import resolve_page_links
from app.services.import_engine.references import resolve_references
from app.services.import_engine.zip_bounds import json_cap, open_zip, read_json_member
from app.services.tenant import tags as tags_service

# Apply order within an initiative — convention, not correctness (cross-tool
# references in envelopes are display text only).
# Derived from the same set the export side writes, so a tool cannot be
# exported into an envelope this refuses to read back.
_TOOL_ORDER = tuple(t.value for t in BULK_EXPORT_TOOLS)

# An initiative's own files: what it is shaped like, rather than anything made
# inside it. They carry no Tool and no registry importer — like ``file``
# entries, they are applied here — and they go FIRST, because the content
# behind them refers to what they establish: a value binds to a property
# definition, and a member holds a role.
_STRUCTURAL_TOOL = "initiative"
_STRUCTURAL_TYPES = frozenset({"initiative-structure", "initiative-properties"})

# Refresh the routed session's authorization context this often (see the
# export backup adapter's identical constant).
_REFRESH_EVERY = 25

_MANIFEST_NAME = "manifest.json"

#: What "filed in" means, per kind of far end. A document in a wiki is a
#: ``part_of`` — the wiki is a place, and the document is one of the things
#: in it, which is exactly the edge ``wikis.linked_documents`` reads.
#:
#: One kind, because ``attach_to`` names another manifest ENTRY, and a wiki is
#: the only place a file can be filed that is an entry of its own. A task is
#: not: it lives inside its project's envelope, so a document attached to a
#: task is a link the envelope asserts by ref, not a placement recorded here.
#: A kind nothing here names is left alone rather than guessed at.
_ATTACH_RELATIONSHIPS: dict[str, RelationshipType] = {
    "wiki": RelationshipType.part_of,
}


def _entry_ref(path: str) -> str:
    """The name an entry answers to inside one job.

    Namespaced so it cannot collide with an external ref an envelope chose
    for itself (``"jira:ACME-123"``) — both live in the same map, because
    both are "a name that resolves to a row once the import has run"."""
    return f"entry:{path}"


def _entry_kind(entry: ManifestEntry) -> SearchEntityType | None:
    """What kind of thing this entry becomes. A file entry is a document
    whatever tool it was filed under; everything else is its own tool. A
    tool this build has no endpoint kind for cannot be an end of an edge,
    which is a reason to skip it rather than to fail the restore."""
    name = "document" if entry.type == "file" else entry.tool
    try:
        return SearchEntityType(name)
    except ValueError:
        return None


logger = logging.getLogger(__name__)


#: A backup is opened like any zip the engine reads; the name callers know.
open_backup_zip = open_zip


def read_manifest(archive: zipfile.ZipFile, *, fetched: bool = False) -> BackupManifest:
    """The backup's manifest, read up to the JSON cap and checked.

    ``fetched`` is as for :func:`zip_bounds.open_zip`."""
    try:
        raw = read_json_member(
            archive,
            _MANIFEST_NAME,
            max_bytes=json_cap(fetched=fetched),
            invalid=ImportEngineMessages.IMPORT_ZIP_INVALID,
        )
    except ImportEngineError:
        raise
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    try:
        manifest = BackupManifest.model_validate(raw)
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    if not (
        MIN_SUPPORTED_IMPORT_VERSION <= manifest.schema_version <= BACKUP_SCHEMA_VERSION
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED)
    _reject_non_flat_asset_keys(manifest)
    return manifest


def _reject_non_flat_asset_keys(manifest: BackupManifest) -> None:
    """A backup asset key is both the ``uploads`` row identity and the storage
    write target; the storage backends reduce it to ``Path(key).name``, so it
    must already be flat for the two to match. Legit exports only ever emit flat
    keys, so a key with path components is a malformed backup — reject it."""
    from app.services.storage import is_flat_storage_key

    for asset in manifest.assets:
        if not is_flat_storage_key(asset.storage_key):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
    for entry in manifest.entries:
        if entry.asset is not None and not is_flat_storage_key(
            entry.asset.removeprefix("assets/")
        ):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)


def plan_backup(
    payload: bytes | Path,
    *,
    existing_initiative_names: set[str],
    member_ids_by_handle: dict[str, int] | None = None,
    fetched: bool = False,
) -> BackupImportPlan:
    """The confirm-screen summary. Reads only the manifest — cheap enough to
    run inside the upload request.

    ``member_ids_by_handle`` is the guild's own roster, normalised, and it is
    what turns the archive's people into suggestions. It is passed in rather
    than read here because this function holds no session: the plan is a
    reading of one file, and the roster is a fact about the community it is
    being read into.

    ``fetched`` is as for :func:`zip_bounds.open_zip`. Blocking; run it in a
    thread from async code.
    """
    from app.services.import_engine.importers import IMPORTERS

    with open_zip(payload, fetched=fetched) as archive:
        manifest = read_manifest(archive, fetched=fetched)

    unknown_types = sorted(
        {
            entry.type
            for entry in manifest.entries
            if entry.type != "file"
            and entry.type not in _STRUCTURAL_TYPES
            and entry.type not in IMPORTERS
        }
    )
    # Suffix previews compound: two imported initiatives can collide with
    # each other, not just with existing ones.
    taken = set(existing_initiative_names)
    initiatives: list[BackupPlanInitiative] = []
    for mi in manifest.initiatives:
        if mi.target_initiative_id is not None:
            # Filed into one that exists: no name is claimed, so none is
            # proposed, and it cannot push a created one into a suffix.
            proposed = mi.name
        else:
            proposed = unique_name(taken, mi.name)
            taken.add(proposed)
        counts: dict[str, int] = {}
        for entry in manifest.entries:
            if entry.initiative_id == mi.id:
                counts[entry.tool] = counts.get(entry.tool, 0) + 1
        initiatives.append(
            BackupPlanInitiative(
                source_id=mi.id,
                name=mi.name,
                proposed_name=proposed,
                tools=mi.tools,
                entry_counts=counts,
                target_initiative_id=mi.target_initiative_id,
            )
        )
    roster = member_ids_by_handle or {}
    people = [
        BackupPlanPerson(
            handle=person.handle,
            name=person.name,
            comment_count=person.comment_count,
            suggested_user_id=roster.get(handle_key(person.handle)),
        )
        for person in manifest.people
    ]
    return BackupImportPlan(
        source_guild_name=manifest.guild.name,
        app_version=manifest.app_version,
        exported_at=manifest.exported_at.isoformat(),
        schema_version=manifest.schema_version,
        initiatives=initiatives,
        asset_count=len(manifest.assets),
        asset_bytes=sum(a.size_bytes for a in manifest.assets),
        skipped=[s.model_dump(mode="json") for s in manifest.skipped],
        unknown_types=unknown_types,
        people=people,
    )


def _manifest_tool_flags(tools: dict[str, str] | None) -> dict[str, bool]:
    """A manifest's per-tool states as initiative master-switch fields.

    "disabled" -> off; "included"/"excluded" -> on, because the switch records
    the source's configuration rather than what this import was asked to carry.

    Spelled through the enum rather than ``tool + "s"``, which is wrong for
    ``gallery``. A manifest also names things that are not tools — a backup
    written by a newer version, or a sub-resource like ``calendar_event`` — and
    those name no switch, so they are skipped rather than raising on an
    initiative that is otherwise importable.
    """
    flags: dict[str, bool] = {}
    for name, state in (tools or {}).items():
        try:
            tool = Tool(name)
        except ValueError:
            continue
        flags[tool.view_permission] = state != "disabled"
    return flags


async def apply_backup(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    payload: bytes | Path,
    include: dict[str, bool] | None,
    people_map: Any = None,
    exclude_properties: Any = None,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
    fetched: bool = False,
) -> BackupImportResult:
    """Restore a backup zip into new initiatives, as ``user``, on the
    worker's creator-routed session. Flushes and COMMITS per chunk (the
    always-create policy makes partial progress durable and never re-run).

    ``heartbeat`` is called after each asset and each entry, so the job can
    show it is still being applied. ``fetched`` is as for
    :func:`zip_bounds.open_zip`."""
    archive = await asyncio.to_thread(open_zip, payload, fetched=fetched)
    try:
        return await _apply_archive(
            session,
            archive=archive,
            user=user,
            guild_id=guild_id,
            include=include,
            people_map=people_map,
            exclude_properties=exclude_properties,
            heartbeat=heartbeat,
            fetched=fetched,
        )
    finally:
        archive.close()


async def _apply_archive(
    session: AsyncSession,
    *,
    archive: zipfile.ZipFile,
    user: User,
    guild_id: int,
    include: dict[str, bool] | None,
    people_map: Any,
    exclude_properties: Any,
    heartbeat: Callable[[], Awaitable[None]] | None,
    fetched: bool,
) -> BackupImportResult:
    from app.api.deps import establish_guild_access
    from app.services.import_engine.importers import IMPORTERS
    from app.models.platform.guild import GuildRole
    from app.services.platform import guilds as guilds_service
    from app.services.tenant import initiatives as initiatives_service

    manifest = await asyncio.to_thread(read_manifest, archive, fetched=fetched)
    max_json_bytes = json_cap(fetched=fetched)
    result = BackupImportResult()

    # Re-verify the seat, held outright, at apply time — enqueue-time
    # authority can be gone by now, and standing up a new initiative in the
    # community is the seat's act. It is asked for only when something here
    # actually creates one: a bundle that applies into initiatives somebody
    # already runs is gated by the per-tool create permission in those
    # initiatives instead (§8.2), which is the same gate a lone envelope
    # passes.
    if any(mi.target_initiative_id is None for mi in manifest.initiatives):
        membership = await guilds_service.get_membership(
            session, guild_id=guild_id, user_id=user.id
        )
        if membership is None or membership.role is not GuildRole.superadmin:
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_SUPERADMIN_REQUIRED, status_code=403
            )

    # Assets first, one chunk: written under their ORIGINAL storage keys so
    # embedded editor-state image references resolve without rewriting.
    if manifest.assets:
        written = await _restore_assets(
            session, archive, manifest, guild_id, user, result, heartbeat
        )
        try:
            await session.commit()
        except BaseException:
            remove_written(guild_id, written)
            raise

    assets_by_key = {a.storage_key: a for a in manifest.assets}
    entries_by_initiative: dict[int, list[ManifestEntry]] = {}
    for entry in manifest.entries:
        entries_by_initiative.setdefault(entry.initiative_id, []).append(entry)

    since_refresh = 0
    from app.models.tenant.initiative import Initiative

    # One context for the whole bundle. Its collector matters because an edge
    # routinely crosses two entries applied by two different importers, so
    # nothing resolves until the last of them has flushed; its people map is
    # what the confirm's mapping step recorded, re-checked against real
    # membership here rather than trusted from the job row.
    from app.services.import_engine.people import resolve_people_map

    context = ImportContext(
        people=await resolve_people_map(session, guild_id=guild_id, raw=people_map),
        excluded_properties=excluded_property_names(exclude_properties),
        source_url=manifest.source_instance_url,
        same_community=exported_from_here(
            manifest.source_instance_url, manifest.guild.id, guild_id=guild_id
        ),
    )

    for mi in manifest.initiatives:
        # System sentinel: user-attributed job, gate passed at enqueue.
        await establish_guild_access(
            session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
        )
        entries_here = entries_by_initiative.get(mi.id, [])
        if mi.target_initiative_id is not None:
            initiative = await _resolve_target_initiative(
                session,
                target_initiative_id=mi.target_initiative_id,
                entries=entries_here,
                user=user,
                guild_id=guild_id,
                include=include,
            )
        else:
            initiative = await initiatives_service.create_imported_initiative(
                session,
                guild_id=guild_id,
                name=mi.name,
                description=mi.description,
                color=mi.color,
                tool_flags=_manifest_tool_flags(mi.tools),
                manager_id=user.id,
            )
        result.initiatives.append(
            {
                "source_id": mi.id,
                "initiative_id": initiative.id,
                "name": initiative.name,
            }
        )

        entries = sorted(
            entries_here,
            key=lambda e: (
                -1
                if e.tool == _STRUCTURAL_TOOL
                else _TOOL_ORDER.index(e.tool)
                if e.tool in _TOOL_ORDER
                else len(_TOOL_ORDER)
            ),
        )
        for entry in entries:
            since_refresh += 1
            if since_refresh >= _REFRESH_EVERY:
                await session.commit()
                await establish_guild_access(
                    session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
                )
                # Re-load the initiative on the refreshed transaction.
                initiative = (
                    await session.exec(
                        select(Initiative).where(Initiative.id == initiative.id)
                    )
                ).one()
                since_refresh = 0
            outcome = await _apply_entry(
                session,
                archive=archive,
                entry=entry,
                initiative=initiative,
                user=user,
                include=include,
                importers=IMPORTERS,
                assets_by_key=assets_by_key,
                result=result,
                context=context,
                max_json_bytes=max_json_bytes,
            )
            result.entries.append(outcome)
            bucket = result.per_tool.setdefault(
                entry.tool, {"created": 0, "failed": 0, "skipped": 0}
            )
            bucket[outcome.status] += 1
            if heartbeat is not None:
                await heartbeat()
        await session.commit()

    # Everything is in the database; now the names can become edges.
    await establish_guild_access(
        session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
    )
    resolution = await context.links.resolve(session, created_by=user.id)
    result.links_created = resolution.created
    result.links_unresolved = resolution.unresolved
    # What a body names is placed on what it became here.
    await resolve_references(session, context, author_id=user.id)
    # And a link written in a task to a page that came over in the same
    # bundle becomes a mention of that page.
    await resolve_page_links(session, context.links, site_url=context.source_url)
    await _file_documents_under_pages(session, context)
    await session.commit()

    return result


async def _file_documents_under_pages(
    session: AsyncSession, context: ImportContext
) -> None:
    """File each document an entry placed under a page of its wiki, now that
    the document, the wiki and the page all exist. One whose page or wiki did
    not arrive stays at the top of the wiki, where joining it put it."""
    from app.models.tenant.wiki import Wiki
    from app.services.import_engine.links import wiki_page_slug_ref
    from app.services.tenant import wikis as wikis_service

    wikis: dict[int, Wiki] = {}
    for document_ref, wiki_ref, page_slug in context.placements:
        document = context.links.lookup(document_ref)
        wiki_end = context.links.lookup(wiki_ref)
        if document is None or wiki_end is None:
            continue
        page = context.links.lookup(wiki_page_slug_ref(wiki_end.id, page_slug))
        if page is None:
            continue
        wiki = wikis.get(wiki_end.id)
        if wiki is None:
            wiki = await session.get(Wiki, wiki_end.id)
            if wiki is None:
                continue
            wikis[wiki_end.id] = wiki
        wikis_service.file_document(wiki, document.id, parent_page_id=page.id)
        session.add(wiki)


async def _resolve_target_initiative(
    session: AsyncSession,
    *,
    target_initiative_id: int,
    entries: list[ManifestEntry],
    user: User,
    guild_id: int,
    include: dict[str, bool] | None,
):
    """Resolve an initiative the bundle wants to apply INTO, and prove the
    importer may write each kind of thing it is about to receive.

    The gate is the same one a lone envelope passes, run once per kind the
    bundle carries: ``load_target_initiative`` resolves the initiative under
    the caller's own RLS (unreachable reads as absent — 404), checks the
    tool's master switch, and checks the create permission. So a bundle
    naming four tools is refused unless its importer may create all four,
    and nothing is written before that is known.

    Only kinds this apply will actually reach are checked: an entry excluded
    by the include map is not going to be written, and demanding a permission
    for it would refuse an import that was never going to need it.
    """
    from app.services.import_engine.importers import IMPORTERS

    initiative = None
    seen: set[str] = set()
    for entry in entries:
        if include is not None and not include.get(entry.tool, True):
            continue
        # A file entry is a document whatever tool it was filed under, so it
        # is the document importer's permission that governs it.
        envelope_type = "initiative-document" if entry.type == "file" else entry.type
        if envelope_type in seen:
            continue
        seen.add(envelope_type)
        importer = IMPORTERS.get(envelope_type)
        if importer is None:
            # An unknown type is skipped at apply time with a code in the
            # report; it names no permission to check here.
            continue
        initiative = await import_engine.load_target_initiative(
            session,
            guild_id=guild_id,
            initiative_id=target_initiative_id,
            importer=importer,
            user=user,
        )
    if initiative is None:
        # Nothing to apply, or nothing whose type this build knows. Resolve
        # the initiative anyway so the rest of the pass has one to work with
        # and an unreachable id still fails here rather than later.
        initiative = await import_engine.load_target_initiative(
            session,
            guild_id=guild_id,
            initiative_id=target_initiative_id,
            importer=IMPORTERS["initiative-document"],
            user=user,
        )
    return initiative


async def _apply_entry(
    session: AsyncSession,
    *,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    include: dict[str, bool] | None,
    importers: dict,
    assets_by_key: dict[str, Any],
    result: BackupImportResult,
    context: ImportContext | None = None,
    max_json_bytes: int | None = None,
) -> EntryResult:
    """Apply one manifest entry in its own savepoint and report how it went.
    Its envelope is read up to ``max_json_bytes`` (the upload cap when not
    given)."""
    if max_json_bytes is None:
        max_json_bytes = json_cap()
    base = {
        "path": entry.path,
        "tool": entry.tool,
        "type": entry.type,
        "title": entry.title,
    }
    if include is not None and not include.get(entry.tool, True):
        return EntryResult(**base, status="skipped")
    if entry.type == "file":
        outcome = await _apply_file_entry(
            session, entry, initiative, user, assets_by_key, base, context=context
        )
        _record_entry(context, entry, outcome)
        return outcome
    if entry.type in _STRUCTURAL_TYPES:
        return await _apply_structural_entry(
            session, archive, entry, initiative, user, base, max_json_bytes
        )
    importer = importers.get(entry.type)
    if importer is None:
        return EntryResult(
            **base, status="skipped", error=ImportEngineMessages.IMPORT_UNKNOWN_TYPE
        )
    try:
        raw = await asyncio.to_thread(
            read_json_member, archive, entry.path, max_bytes=max_json_bytes
        )
        validated = importer.validate(raw)
        async with session.begin_nested():
            detail = await importer.apply(
                session,
                envelope=validated,
                target_initiative=initiative,
                importer=user,
                context=context,
            )
    except ImportEngineError as exc:
        logger.warning(
            "backup entry failed path=%s tool=%s code=%s",
            entry.path,
            entry.tool,
            exc.code,
        )
        return EntryResult(**base, status="failed", error=exc.code)
    except Exception:
        # Savepoint isolation stands, but the traceback must reach the logs —
        # the result JSON carries only a status code.
        logger.exception("backup entry failed path=%s tool=%s", entry.path, entry.tool)
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    result.unmatched_handles = sorted(
        set(result.unmatched_handles) | set(detail.unmatched_handles)
    )
    outcome = EntryResult(**base, status="created", detail=detail)
    _record_entry(context, entry, outcome)
    return outcome


def _record_entry(
    context: ImportContext | None, entry: ManifestEntry, outcome: EntryResult
) -> None:
    """Put a successfully applied entry into the job's ref map, and record
    what it said it is filed in.

    Both halves are names, not ids: the far end of an ``attach_to`` is
    another entry that may not have been applied yet, and resolving it is the
    deferred pass's job.
    """
    if context is None or outcome.status != "created":
        return
    kind = _entry_kind(entry)
    entity_id = outcome.detail.entity_id if outcome.detail is not None else None
    if kind is None or entity_id is None:
        return
    context.links.register(_entry_ref(entry.path), kind, entity_id)
    # And by what it was where it was exported, which is how a reference in
    # somebody else's body names it.
    context.links.register(format_ref(kind, entry.entity_id), kind, entity_id)
    if entry.attach_to is None:
        return
    relationship = _ATTACH_RELATIONSHIPS.get(entry.attach_to.kind)
    if relationship is None:
        return
    context.links.link(
        _entry_ref(entry.path), relationship, _entry_ref(entry.attach_to.ref)
    )
    if entry.attach_to.kind == "wiki" and entry.attach_to.page:
        context.placements.append(
            (
                _entry_ref(entry.path),
                _entry_ref(entry.attach_to.ref),
                entry.attach_to.page,
            )
        )


async def _apply_structural_entry(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    base: dict,
    max_json_bytes: int,
) -> EntryResult:
    """An initiative's own shape: its property definitions, or its roles and
    members.

    Both are **additive**. They create what the target does not have and leave
    what it does alone: a definition or role of the same name is the target's
    answer, not the archive's, and nobody is removed or demoted by an import.
    """
    invalid = EntryResult(
        **base, status="failed", error=ImportEngineMessages.IMPORT_INVALID_ENVELOPE
    )
    try:
        payload = await asyncio.to_thread(
            read_json_member, archive, entry.path, max_bytes=max_json_bytes
        )
    except ImportEngineError as exc:
        return EntryResult(**base, status="failed", error=exc.code)
    except Exception:
        return invalid
    if not isinstance(payload, dict):
        return invalid
    try:
        async with session.begin_nested():
            if entry.type == "initiative-properties":
                created = await _apply_property_definitions(
                    session, initiative, payload
                )
            else:
                created = await _apply_initiative_structure(
                    session, initiative, user, payload
                )
    except Exception:
        logger.exception("backup import: structural entry %s failed", entry.path)
        return invalid
    return EntryResult(
        **base,
        status="created",
        detail=EnvelopeImportResult(
            entity_id=initiative.id, entity_title=initiative.name, created=created
        ),
    )


async def _apply_property_definitions(session, initiative, payload: dict) -> dict:
    """Create the definitions the target does not already have, by name."""
    from sqlmodel import select

    from app.models.tenant.property import PropertyDefinition, PropertyType

    existing = {
        name
        for name in await session.exec(
            select(PropertyDefinition.name).where(
                PropertyDefinition.initiative_id == initiative.id
            )
        )
    }
    created = 0
    for raw in payload.get("properties") or []:
        name = str(raw.get("name") or "").strip()
        if not name or name in existing:
            continue
        try:
            prop_type = PropertyType(raw.get("type"))
        except ValueError:
            continue  # a type this build has no column for
        options = raw.get("options")
        session.add(
            PropertyDefinition(
                initiative_id=initiative.id,
                name=name,
                type=prop_type,
                position=float(raw.get("position") or 0),
                color=raw.get("color"),
                options=options if isinstance(options, list) else None,
            )
        )
        existing.add(name)
        created += 1
    await session.flush()
    return {"property_definitions": created}


async def _apply_initiative_structure(session, initiative, user: User, payload) -> dict:
    """Create the roles the target lacks, then place people it can name.

    A member is placed only where the handle resolves to somebody already in
    this community — an archive names people, it does not create accounts —
    and never over a membership that already exists.
    """
    from sqlmodel import select

    from app.models.tenant.initiative import (
        InitiativeMember,
        InitiativeRoleModel,
        InitiativeRolePermission,
        PermissionKey,
    )
    from app.services.import_engine.common import load_guild_member_handles

    roles = {
        role.name: role
        for role in await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id
            )
        )
    }
    roles_created = 0
    for raw in payload.get("roles") or []:
        name = str(raw.get("name") or "").strip()
        if not name or name in roles:
            continue
        role = InitiativeRoleModel(
            initiative_id=initiative.id,
            name=name,
            display_name=str(raw.get("display_name") or name),
            # Built-in-ness is this build's answer, not the archive's: a role
            # the target did not ship with is a custom one here.
            is_builtin=False,
            is_manager=bool(raw.get("is_manager")),
            override_share_restrictions=bool(raw.get("override_share_restrictions")),
            position=int(raw.get("position") or 0),
            created_by=user.id,
        )
        session.add(role)
        await session.flush()
        for key in raw.get("permissions") or []:
            try:
                permission_key = PermissionKey(key)
            except ValueError:
                continue  # a permission this build does not have
            session.add(
                InitiativeRolePermission(
                    initiative_role_id=role.id,
                    permission_key=permission_key,
                    enabled=True,
                )
            )
        roles[name] = role
        roles_created += 1

    placed = 0
    members = payload.get("members") or []
    if members:
        handles = await load_guild_member_handles(
            session, guild_id=routed_guild_id(session)
        )
        already = {
            row
            for row in await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative.id
                )
            )
        }
        for raw in members:
            handle = (raw.get("handle") or "").strip().lower()
            user_id = handles.get(handle)
            if user_id is None or user_id in already:
                continue
            role = roles.get(raw.get("role") or "")
            session.add(
                InitiativeMember(
                    initiative_id=initiative.id,
                    user_id=user_id,
                    role_id=role.id if role is not None else None,
                )
            )
            already.add(user_id)
            placed += 1
    await session.flush()
    return {"initiative_roles": roles_created, "initiative_members": placed}


async def _apply_file_entry(
    session: AsyncSession,
    entry: ManifestEntry,
    initiative,
    user: User,
    assets_by_key: dict[str, Any],
    base: dict,
    *,
    context: ImportContext | None = None,
) -> EntryResult:
    """A file document: its content is the restored ``assets/`` blob."""
    from app.models.tenant.document import Document, DocumentType
    from app.models.tenant.property import DocumentPropertyValue
    from app.models.tenant.upload import Upload
    from app.schemas.tenant.import_envelopes import EnvelopePropertyValue
    from app.services.import_engine.common import (
        ensure_tag,
        load_initiative_member_handles,
    )
    from app.services.import_engine.importers._base import (
        grant_ownership,
        resolve_property_values,
    )

    storage_key = (entry.asset or "").removeprefix("assets/")
    if not storage_key:
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_INVALID_ENVELOPE
        )
    asset = assets_by_key.get(storage_key)
    upload = (
        await session.exec(select(Upload).where(Upload.filename == storage_key))
    ).one_or_none()
    if upload is None:
        # Uploads were excluded from this backup (or the blob was not
        # restored) — recorded, not silently dropped.
        return EntryResult(
            **base, status="skipped", error=ImportEngineMessages.IMPORT_ASSET_MISSING
        )

    try:
        async with session.begin_nested():
            document = Document(
                name=entry.title,
                document_type=DocumentType.file,
                content={},
                initiative_id=initiative.id,
                created_by=user.id,
                file_url=f"/uploads/{routed_guild_id(session)}/{storage_key}",
                # The original name lives in the manifest's asset record —
                # the uploads row's filename IS the storage key.
                original_filename=(
                    asset.original_filename if asset is not None else storage_key
                ),
                file_content_type=upload.content_type,
                file_size=upload.size_bytes,
            )
            session.add(document)
            await session.flush()
            await grant_ownership(
                session,
                tool=Tool.document,
                entity_id=document.id,
                target_initiative=initiative,
                importer=user,
            )

            for tag_name in entry.tags:
                resolved = await ensure_tag(
                    session,
                    name=tag_name,
                    color="#6b7280",
                )
                session.add(
                    tags_service.tag_edge(
                        tags_service.TAG_LINKS["document"],
                        document.id,
                        resolved.id,
                    )
                )
            if entry.properties:
                values = [
                    EnvelopePropertyValue.model_validate(p) for p in entry.properties
                ]
                member_handles = await load_initiative_member_handles(
                    session, initiative_id=initiative.id
                )
                attached = await resolve_property_values(
                    session,
                    initiative_id=initiative.id,
                    values=values,
                    member_handles=member_handles,
                    people=context.people if context is not None else None,
                )
                for prop_id, column_kwargs in attached.column_kwargs_by_id.items():
                    session.add(
                        DocumentPropertyValue(
                            document_id=document.id,
                            property_id=prop_id,
                            **column_kwargs,
                        )
                    )
    except Exception:
        logger.exception(
            "backup file entry failed path=%s asset=%s", entry.path, entry.asset
        )
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    # The id is reported so the entry can be an end of an edge — a file
    # placed in a wiki is a ``document part_of wiki``, resolved by the
    # deferred pass once the wiki entry has been applied too.
    return EntryResult(
        **base,
        status="created",
        detail=EnvelopeImportResult(
            entity_id=document.id,
            entity_title=document.name,
            created={"documents": 1},
        ),
    )


async def _restore_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    manifest: BackupManifest,
    guild_id: int,
    user: User,
    result: BackupImportResult,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> list[str]:
    """Restore the manifest's ``assets/`` files through
    :func:`archive_assets.restore_assets`, each held to the rule for any
    upload, and count what happened on ``result``. Returns the keys written.

    A file named but not in the zip is reported as ``asset_missing``; one that
    is not a file this app holds is left out and reported as such. Either way
    an entry that needed it is skipped with ``IMPORT_ASSET_MISSING``.
    """
    assets: dict[str, ArchiveAsset] = {}
    for asset in manifest.assets:
        assets.setdefault(
            asset.storage_key,
            ArchiveAsset(
                key=asset.storage_key,
                member=asset.path,
                kind="upload",
                original_filename=asset.original_filename,
                content_type=asset.content_type,
            ),
        )
    restored = await restore_assets(
        session,
        archive,
        list(assets.values()),
        guild_id=guild_id,
        user=user,
        heartbeat=heartbeat,
    )
    result.assets_deduped += restored.deduped
    result.assets_restored += len(restored.written)
    result.asset_bytes += restored.restored_bytes
    result.warnings.extend(f"asset_missing:{key}" for key in restored.missing)
    result.warnings.extend(restored.warnings)
    return restored.written
