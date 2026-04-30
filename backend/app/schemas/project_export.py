"""Pydantic schemas for the project export/import envelope.

The envelope is a self-contained JSON document that can be moved between
Initiative instances. All cross-row references are encoded as strings
(name / email) instead of integer IDs because IDs don't survive a
cross-database move.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.property import PropertyType
from app.models.task import TaskPriority, TaskStatusCategory


SCHEMA_VERSION = 1
"""Bump on breaking changes to the envelope shape. Independent of app VERSION."""

MIN_SUPPORTED_IMPORT_VERSION = 1
"""Imports below this version are rejected. Future migrations may bridge older versions."""


class ProjectExportProject(BaseModel):
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None
    is_template: bool = False
    is_archived: bool = False


class ProjectExportTag(BaseModel):
    name: str
    color: str


class ProjectExportTaskStatus(BaseModel):
    name: str
    category: TaskStatusCategory
    position: int = 0
    color: str = "#94A3B8"
    icon: str = "circle-dashed"
    is_default: bool = False


class ProjectExportPropertyDefinition(BaseModel):
    name: str
    type: PropertyType
    position: float = 0.0
    color: Optional[str] = None
    options: Optional[List[dict]] = None


class ProjectExportPropertyValue(BaseModel):
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
    - user_reference        → ``value_email``
    """

    property_name: str
    property_type: PropertyType
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_email: Optional[str] = None
    value_json: Optional[Any] = None


class ProjectExportSubtask(BaseModel):
    content: str
    is_completed: bool = False
    position: int = 0


class ProjectExportTask(BaseModel):
    title: str
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.medium
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[dict] = None
    recurrence_strategy: str = "fixed"
    recurrence_occurrence_count: int = 0
    sort_order: float = 0.0
    is_archived: bool = False
    status_name: str
    tag_names: List[str] = Field(default_factory=list)
    assignee_emails: List[str] = Field(default_factory=list)
    subtasks: List[ProjectExportSubtask] = Field(default_factory=list)
    property_values: List[ProjectExportPropertyValue] = Field(default_factory=list)


class ProjectExportEnvelope(BaseModel):
    """Top-level export document. Versioned so the importer can refuse
    or migrate older / unknown formats."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    schema_version: int = SCHEMA_VERSION
    app_version: str
    exported_at: datetime
    exported_by_email: Optional[str] = None
    source_instance_url: Optional[str] = None

    project: ProjectExportProject
    tags: List[ProjectExportTag] = Field(default_factory=list)
    task_statuses: List[ProjectExportTaskStatus] = Field(default_factory=list)
    property_definitions: List[ProjectExportPropertyDefinition] = Field(default_factory=list)
    tasks: List[ProjectExportTask] = Field(default_factory=list)


class ProjectImportRequest(BaseModel):
    """Body for ``POST /api/v1/projects/import``.

    The envelope is included inline rather than as multipart so the API
    stays JSON-only. The frontend reads the user's selected file and
    posts the parsed JSON back here.
    """

    initiative_id: int
    envelope: ProjectExportEnvelope


class ProjectImportResult(BaseModel):
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
    assignee_unmatched_emails: List[str] = Field(default_factory=list)
