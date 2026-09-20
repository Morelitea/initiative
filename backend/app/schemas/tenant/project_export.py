"""Pydantic schemas for the project export/import envelope.

The envelope is a self-contained JSON document that can be moved between
Initiative instances. All cross-row references are encoded as strings
(name / email) instead of integer IDs because IDs don't survive a
cross-database move.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import Field

from app.schemas.base import SanitizedBaseModel

from app.core.relationships import RelationshipType
from app.models.tenant.property import PropertyType
from app.models.tenant.task import TaskPriority, TaskStatusCategory


SCHEMA_VERSION = 1
"""Bump on breaking changes to the envelope shape. Independent of app VERSION."""

MIN_SUPPORTED_IMPORT_VERSION = 1
"""Imports below this version are rejected. Future migrations may bridge older versions."""


class ProjectExportProject(SanitizedBaseModel):
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None
    is_template: bool = False
    archived_at: Optional[datetime] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectExportTag(SanitizedBaseModel):
    name: str
    color: str


class ProjectExportTaskStatus(SanitizedBaseModel):
    name: str
    category: TaskStatusCategory
    position: int = 0
    color: str = "#94A3B8"
    icon: str = "circle-dashed"
    is_default: bool = False


class ProjectExportPropertyDefinition(SanitizedBaseModel):
    name: str
    type: PropertyType
    position: float = 0.0
    color: Optional[str] = None
    options: Optional[List[dict]] = None


class ProjectExportPropertyValue(SanitizedBaseModel):
    """Typed property value snapshot.

    ``property_type`` is repeated alongside the value so the importer can
    validate against the target initiative's property *without* re-reading
    the definitions array, and so a property type collision rename can be
    routed to the correct renamed definition.

    Encoding per type (writes to one of these fields, others ``None``):
    - text/url/select       → ``value_text``
    - number                → ``value_number``
    - checkbox              → ``value_boolean``
    - date                  → ``value_text`` (ISO 8601 date)
    - datetime              → ``value_text`` (ISO 8601 datetime)
    - multi_select          → ``value_json`` (list[str])
    - user_reference        → ``value_handle``
    """

    property_name: str
    property_type: PropertyType
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_handle: Optional[str] = None
    value_json: Optional[Any] = None


class ProjectExportChecklistItem(SanitizedBaseModel):
    text: str
    done: bool = False


class ProjectExportComment(SanitizedBaseModel):
    """One thing somebody said on a task.

    The author crosses as a **handle and a display name, never an id** — the
    rule every envelope follows for people. Both are carried because they
    answer different questions on the far side: the handle is what an importer
    can match against the target initiative's roster, and the name is what a
    reader sees when nothing matched.

    Matching the handle does **not** transfer authorship. A comment is
    first-person speech, and an envelope is text the importer supplies, so an
    imported comment is attributed to the person doing the import with the
    original author named in it. See ``project_import._comment_body``.
    """

    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    body: str
    created_at: Optional[datetime] = None


class ProjectExportTaskLink(SanitizedBaseModel):
    """An edge this task asserts, named by the far end's ``external_ref``.

    Refs rather than ids because the far end may not exist yet — it can be in
    a later entry of the same backup, or in a different envelope entirely. The
    job's deferred pass resolves every ref once the last entry has flushed
    (``import_engine.links``), so the order entries apply in does not matter.
    """

    type: RelationshipType
    target_external_ref: str


class ProjectExportTask(SanitizedBaseModel):
    title: str
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.medium
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[dict] = None
    recurrence_strategy: str = "fixed"
    recurrence_occurrence_count: int = 0
    position: float = 0.0
    archived_at: Optional[datetime] = None
    # Absent in exports taken before completion timestamps existed; the
    # importer derives it from the restored status in that case.
    completed_at: Optional[datetime] = None
    status_name: str
    # When the work was written down, and when it was last touched. Optional
    # because an export taken before these existed carries neither; the
    # importer falls back to the moment of the import, which is the only
    # honest answer it has.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # What this task was called where it came from — ``"jira:ACME-123"``, or a
    # backup's own ``"task:41"``. It is the name ``links`` point at, and it is
    # never written to a column: it lives for the length of one job.
    external_ref: Optional[str] = None
    # Lists are required (no default_factory): pydantic 2.x splits the
    # OpenAPI schema into ``-Input``/``-Output`` whenever a field has a
    # different presence in validation vs serialization, and
    # default_factory=list is the canonical trigger. The exporter always
    # emits these, so the field is always present anyway.
    tags: List[ProjectExportTag]
    assignee_handles: List[str]
    checklist: List[ProjectExportChecklistItem]
    property_values: List[ProjectExportPropertyValue]
    # Both default to empty: an envelope written before they existed is a
    # task with nothing said on it and nothing pointing anywhere, which is
    # exactly what an absent field means here.
    links: List[ProjectExportTaskLink] = []
    comments: List[ProjectExportComment] = []


class ProjectExportEnvelope(SanitizedBaseModel):
    """Top-level export document. Versioned so the importer can refuse
    or migrate older / unknown formats.

    All list fields are required (no ``default_factory``) so Pydantic
    doesn't split the OpenAPI schema into ``-Input``/``-Output`` shapes
    when this model is used as both a response (GET /export) and a
    nested request body (POST /import). The exporter always writes
    every list, so requiring them costs nothing at runtime.
    """

    # File-type discriminator, matching the other tool envelopes — a future
    # import dispatches on it. Defaulted so files exported before the field
    # existed still validate.
    type: str = "initiative-project"
    schema_version: int = SCHEMA_VERSION
    app_version: str
    exported_at: datetime
    exported_by_handle: Optional[str] = None
    source_instance_url: Optional[str] = None

    project: ProjectExportProject
    tags: List[ProjectExportTag]
    task_statuses: List[ProjectExportTaskStatus]
    property_definitions: List[ProjectExportPropertyDefinition]
    tasks: List[ProjectExportTask]


class ProjectImportResult(SanitizedBaseModel):
    """Summary of what happened during an import. Surfaced in the UI so
    the user can see how many references were dropped or remapped."""

    project_id: int
    project_name: str
    task_count: int
    tag_create_count: int = 0
    tag_match_count: int = 0
    property_create_count: int = 0
    property_match_count: int = 0
    property_rename_count: int = 0
    assignee_match_count: int = 0
    assignee_unmatched_handles: List[str] = Field(default_factory=list)
    comment_count: int = 0
