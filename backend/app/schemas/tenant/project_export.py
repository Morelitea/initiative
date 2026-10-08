"""Pydantic schemas for the project export/import envelope.

The envelope is a self-contained JSON document that can be moved between
Initiative instances. All cross-row references are encoded as strings
(name / email) instead of integer IDs because IDs don't survive a
cross-database move.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import AliasChoices, Field

from app.schemas.base import SanitizedBaseModel

from app.core.relationships import RelationshipType
from app.models.tenant.property import PropertyType
from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.schemas.tenant.import_envelopes import EnvelopePropertyValue, _EnvelopeBase


#: Where a row's property values are read from. ``property_values`` is what
#: project exports called them before every envelope said ``properties``.
_PROPERTIES = AliasChoices("properties", "property_values")


class ProjectExportProject(SanitizedBaseModel):
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None
    is_template: bool = False
    archived_at: Optional[datetime] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # The project's own values, encoded as every envelope's are. Empty in an
    # export taken before projects carried them.
    properties: List[EnvelopePropertyValue] = Field(
        default=[], validation_alias=_PROPERTIES
    )


class ProjectExportTag(SanitizedBaseModel):
    name: str
    color: str


class ProjectExportTaskStatus(SanitizedBaseModel):
    name: str
    category: TaskStatusCategory
    position: int = 0
    # Absent from what another tool's export is mapped into: the importer
    # then gives the column its category's own look.
    color: Optional[str] = None
    icon: Optional[str] = None
    is_default: bool = False


class ProjectExportPropertyDefinition(SanitizedBaseModel):
    name: str
    type: PropertyType
    position: float = 0.0
    color: Optional[str] = None
    options: Optional[List[dict]] = None


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
    # What this comment was called where it came from, and the comment it
    # answers, so a thread arrives as a thread. Refs for the reason a task's
    # are; they live for the length of one job.
    external_ref: Optional[str] = None
    reply_to_ref: Optional[str] = None
    # The handles the body mentions as ``@<handle>``. Each one the people step
    # places becomes a mention of that account; the rest stay a name.
    mention_handles: List[str] = []


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
    # RRULE lines; an export taken before RRULE carries the older JSON shape.
    recurrence: Optional[str | dict] = None
    recurrence_shift: int = 0
    recurrence_strategy: str = "fixed"
    recurrence_occurrence_count: int = 0
    #: The repeating series the task is in, as a number the tasks of one series
    #: share in this export; the import gives each series a new one.
    series: Optional[int] = None
    #: What an edit of just this task changed from (``Task.recurrence_carry``),
    #: its tags as ``{"name", "color"}`` under ``tags`` and its assignees under
    #: ``assignee_handles``, as the rest of the envelope names them.
    recurrence_carry: Optional[dict[str, Any]] = None
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
    # Required, as the envelope's lists are: every export writes them, so one
    # missing is a file cut short, where an empty list is a real "none".
    tags: List[ProjectExportTag]
    assignee_handles: List[str]
    checklist: List[ProjectExportChecklistItem]
    properties: List[EnvelopePropertyValue] = Field(validation_alias=_PROPERTIES)
    # Both default to empty: an envelope written before they existed is a
    # task with nothing said on it and nothing pointing anywhere, which is
    # exactly what an absent field means here.
    links: List[ProjectExportTaskLink] = []
    comments: List[ProjectExportComment] = []
    # What the community called each assignee, beside ``assignee_handles``
    # (which an import matches on), for a reader of the file.
    assignee_names: List[str] = []
    # The handles the description mentions, as a comment's are.
    mention_handles: List[str] = []


class ProjectExportEnvelope(_EnvelopeBase):
    """A project with its statuses, tags, property definitions and tasks.

    The project's own fields sit under ``project`` rather than at the top
    level as other envelopes' do; exported files and published listings
    already carry this shape.
    """

    # Defaulted so files exported before the field existed still validate.
    type: Literal["initiative-project"] = "initiative-project"
    app_version: str
    exported_at: datetime
    exported_by_handle: Optional[str] = None

    project: ProjectExportProject
    # Required: every export writes these, so a missing one is a truncated or
    # hand-assembled file, which is refused rather than imported as a project
    # with nothing in it. An empty list is a real "none" and is accepted.
    tags: List[ProjectExportTag]
    task_statuses: List[ProjectExportTaskStatus]
    property_definitions: List[ProjectExportPropertyDefinition]
    tasks: List[ProjectExportTask]
