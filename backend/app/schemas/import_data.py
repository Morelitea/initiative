from typing import Dict, List

from pydantic import Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class TodoistImportRequest(SanitizedBaseModel):
    """Request body for importing tasks from Todoist CSV export."""

    project_id: int = Field(..., description="Target project to import tasks into")
    csv_content: RawTextStr = Field(
        ..., description="Raw CSV content from Todoist export"
    )
    section_mapping: Dict[str, int] = Field(
        ..., description="Mapping of Todoist section names to task_status_id"
    )


class ImportResult(SanitizedBaseModel):
    """Result of an import operation."""

    tasks_created: int = Field(
        default=0, description="Number of tasks successfully created"
    )
    subtasks_created: int = Field(
        default=0, description="Number of subtasks successfully created"
    )
    tasks_failed: int = Field(
        default=0, description="Number of tasks that failed to import"
    )
    errors: List[str] = Field(
        default_factory=list, description="List of error messages"
    )


class TodoistSection(SanitizedBaseModel):
    """A section detected in the Todoist CSV."""

    name: str
    task_count: int


class TodoistParseResult(SanitizedBaseModel):
    """Result of parsing a Todoist CSV file."""

    sections: List[TodoistSection] = Field(
        default_factory=list, description="Sections found in the CSV"
    )
    task_count: int = Field(default=0, description="Total number of tasks found")
    has_subtasks: bool = Field(
        default=False, description="Whether any tasks have subtasks"
    )


# Vikunja import schemas


class VikunjaImportRequest(SanitizedBaseModel):
    """Request body for importing tasks from Vikunja JSON export."""

    project_id: int = Field(..., description="Target Initiative project to import into")
    json_content: RawTextStr = Field(
        ..., description="Raw JSON content from Vikunja export"
    )
    source_project_id: int = Field(..., description="Vikunja project ID to import from")
    bucket_mapping: Dict[int, int] = Field(
        ..., description="Mapping of Vikunja bucket IDs to task_status_id"
    )


class VikunjaBucket(SanitizedBaseModel):
    """A bucket (status column) from a Vikunja project."""

    id: int
    name: str
    task_count: int


class VikunjaProject(SanitizedBaseModel):
    """A project detected in the Vikunja export."""

    id: int
    name: str
    task_count: int
    buckets: List[VikunjaBucket] = Field(default_factory=list)


class VikunjaParseResult(SanitizedBaseModel):
    """Result of parsing a Vikunja JSON export."""

    projects: List[VikunjaProject] = Field(
        default_factory=list, description="Projects found in the export"
    )
    total_tasks: int = Field(
        default=0, description="Total number of tasks across all projects"
    )


# TickTick import schemas


class TickTickImportRequest(SanitizedBaseModel):
    """Request body for importing tasks from TickTick CSV export."""

    project_id: int = Field(..., description="Target Initiative project to import into")
    csv_content: RawTextStr = Field(
        ..., description="Raw CSV content from TickTick export"
    )
    source_list_name: str = Field(..., description="TickTick list name to import from")
    column_mapping: Dict[str, int] = Field(
        ..., description="Mapping of TickTick column names to task_status_id"
    )


class TickTickColumn(SanitizedBaseModel):
    """A column (status) from a TickTick list."""

    name: str
    task_count: int


class TickTickList(SanitizedBaseModel):
    """A list detected in the TickTick export."""

    name: str
    task_count: int
    columns: List[TickTickColumn] = Field(default_factory=list)


class TickTickParseResult(SanitizedBaseModel):
    """Result of parsing a TickTick CSV export."""

    lists: List[TickTickList] = Field(
        default_factory=list, description="Lists found in the export"
    )
    total_tasks: int = Field(
        default=0, description="Total number of tasks across all lists"
    )
