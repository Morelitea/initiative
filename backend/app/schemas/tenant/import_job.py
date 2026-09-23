"""API payloads for import jobs. ``params`` is the caller's own options
(target initiative, include map) echoed back; ``plan``/``result`` are the
pre-flight summary and terminal report — the row never carries envelope
content (large payloads are staged behind storage and deleted on terminal
states)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict

from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.schemas.base import RawTextStr, SanitizedBaseModel
from app.services.import_engine.contract import EnvelopeImportResult


class ImportJobRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    created_by: int
    source: str
    params: dict[str, Any]
    plan: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    status: ImportJobStatus
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def serialize_import_job(job: ImportJob, *, guild_id: int) -> ImportJobRead:
    """The wire shape of one job row.

    The row lives in its guild's schema and carries no guild column of its
    own, so the guild is handed in by whoever routed the session.
    """
    fields = {
        name: getattr(job, name)
        for name in ImportJobRead.model_fields
        if name != "guild_id"
    }
    return ImportJobRead(guild_id=guild_id, **fields)


class EnvelopeImportRequest(SanitizedBaseModel):
    """Body of ``POST /imports/envelope``. The envelope is a raw dict —
    its ``type`` field selects the importer, which validates the full shape
    (typing it as a union here would split the OpenAPI schema per type)."""

    initiative_id: int
    envelope: dict[str, Any]


class EnvelopeImportResponse(SanitizedBaseModel):
    """201 body for an inline (small) envelope import."""

    result: EnvelopeImportResult


class ForeignSourceOption(SanitizedBaseModel):
    """One importable thing inside an uploaded export."""

    key: str
    name: str
    task_count: int


class ForeignPreview(SanitizedBaseModel):
    """What an uploaded export holds, read without storing any of it.

    ``picks_one`` tells the wizard what its next step is for: choosing
    between the options, or naming the single project the file describes.
    """

    source: str
    picks_one: bool
    options: list[ForeignSourceOption]


class ForeignImportRequest(SanitizedBaseModel):
    """Body of ``POST /imports/foreign/{source}``.

    ``content`` is the export's own text — a CSV or a JSON document — sent
    back with the choice made about it, so nothing is held server-side
    between the preview and the import.
    """

    initiative_id: int
    selection: str = ""
    #: The file itself, verbatim. Raw rather than plain text: a plain string
    #: field is capped at a few kilobytes and has its markup stripped, and an
    #: export is neither short nor something to rewrite before it is parsed.
    #: Its size is bounded at the transport instead (``body_limit``), and the
    #: parser is what decides whether it reads.
    content: RawTextStr


class EntryResult(SanitizedBaseModel):
    """One manifest entry's apply outcome inside a backup import."""

    path: str
    tool: str
    type: str
    title: str
    status: str  # "created" | "failed" | "skipped"
    error: Optional[str] = None  # short code, never content
    detail: Optional[EnvelopeImportResult] = None


class BackupPlanInitiative(SanitizedBaseModel):
    """One initiative in the pre-flight plan: what would be created."""

    source_id: int
    name: str
    proposed_name: str
    tools: dict[str, str]  # tool -> "included" | "excluded" | "disabled"
    entry_counts: dict[str, int]  # tool -> entries in the zip
    # Set when the bundle files into an initiative that already exists rather
    # than creating one — every foreign-source import. ``proposed_name`` means
    # nothing then; this is where the content goes.
    target_initiative_id: Optional[int] = None


class BackupPlanPerson(SanitizedBaseModel):
    """One name the archive quotes, and our best guess at who that is here.

    ``suggested_user_id`` is filled only by an **exact** handle match against
    the guild's own roster. Anything looser is left empty on purpose: a
    display name that looks similar is how one person's words end up under
    another person's face, and the wizard is asking precisely so that nobody
    has to guess.
    """

    handle: str
    name: Optional[str] = None
    comment_count: int = 0
    suggested_user_id: Optional[int] = None


class AtlassianPlanProperty(SanitizedBaseModel):
    """One property the import would create, for the review step's list."""

    name: str
    type: str
    #: How many imported tasks carry a value for it.
    issue_count: int = 0


class AtlassianFetchSummary(SanitizedBaseModel):
    """What reading an Atlassian site found, for the review step.

    Counts only, never a title or a body. Written while the fetch runs, so the
    wizard can show it climbing, and final once the job is staged.
    """

    projects: int = 0
    tasks: int = 0
    #: Rich-text nodes the converter could not carry, summed over every body.
    #: Said before anybody commits, rather than discovered afterwards.
    dropped_nodes: int = 0
    #: Issues the site returned that were not usable as tasks.
    skipped_issues: int = 0
    #: Project keys that were ticked and could not be read with this token.
    unreadable_projects: list[str] = []
    #: Issue links and parents that will become connections between tasks.
    links: int = 0
    #: Those whose other end was not brought over, so will not.
    links_outside_selection: int = 0
    #: Every property the import would create — only fields some issue
    #: filled in (§6.5) — with how many tasks carry each.
    properties: list[AtlassianPlanProperty] = []
    #: Fields something filled that have no home here, so will not come over.
    dropped_fields: list[str] = []


class BackupImportPlan(SanitizedBaseModel):
    """The confirm-screen summary, persisted to ``import_jobs.plan`` —
    counts and names only, never envelope content."""

    source_guild_name: str = ""
    app_version: str = ""
    exported_at: Optional[str] = None
    schema_version: int = 0
    initiatives: list[BackupPlanInitiative] = []
    asset_count: int = 0
    asset_bytes: int = 0
    skipped: list[dict[str, Any]] = []
    unknown_types: list[str] = []
    # Everyone the archive quotes, most-quoted first — the rows the wizard's
    # people step asks about. Empty for a backup taken before people were
    # inventoried, and for one that quotes nobody.
    people: list[BackupPlanPerson] = []
    # Only on a bundle this server fetched from an Atlassian site.
    atlassian: Optional[AtlassianFetchSummary] = None


class EnvelopeImportPlan(SanitizedBaseModel):
    """The confirm-screen summary for a lone envelope, persisted to
    ``import_jobs.plan``.

    Only people. A backup's plan has initiatives to name and tools to narrow;
    one envelope is one thing going into one initiative the caller already
    picked, so the only question left is who the handles in it are — and it
    is only written when at least one of them has no obvious answer.
    """

    #: Everybody the envelope quotes, most-quoted first. The only thing in
    #: here: the browser already parsed the file it is about, so a title in
    #: the plan would be a second, guessable copy of something the step
    #: already has.
    people: list[BackupPlanPerson] = []


class BackupImportResult(SanitizedBaseModel):
    """Terminal report for a backup import, persisted to
    ``import_jobs.result``."""

    initiatives: list[dict[str, Any]] = []  # {source_id, initiative_id, name}
    per_tool: dict[str, dict[str, int]] = {}  # tool -> {created, failed, skipped}
    entries: list[EntryResult] = []
    assets_restored: int = 0
    assets_deduped: int = 0
    asset_bytes: int = 0
    # Edges the deferred pass wrote, and the ones whose far end was never
    # imported — a link out of the selection is ordinary, and counted rather
    # than treated as a failure.
    links_created: int = 0
    links_unresolved: int = 0
    unmatched_handles: list[str] = []
    warnings: list[str] = []
