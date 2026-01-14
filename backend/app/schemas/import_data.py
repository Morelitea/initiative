from typing import Dict, List

from pydantic import BaseModel, Field


class TodoistImportRequest(BaseModel):
    """Request body for importing tasks from Todoist CSV export."""

    project_id: int = Field(..., description="Target project to import tasks into")
    csv_content: str = Field(..., description="Raw CSV content from Todoist export")
    section_mapping: Dict[str, int] = Field(
        ..., description="Mapping of Todoist section names to task_status_id"
    )


class ImportResult(BaseModel):
    """Result of an import operation."""

    tasks_created: int = Field(default=0, description="Number of tasks successfully created")
    subtasks_created: int = Field(default=0, description="Number of subtasks successfully created")
    tasks_failed: int = Field(default=0, description="Number of tasks that failed to import")
    errors: List[str] = Field(default_factory=list, description="List of error messages")


class TodoistSection(BaseModel):
    """A section detected in the Todoist CSV."""

    name: str
    task_count: int


class TodoistParseResult(BaseModel):
    """Result of parsing a Todoist CSV file."""

    sections: List[TodoistSection] = Field(
        default_factory=list, description="Sections found in the CSV"
    )
    task_count: int = Field(default=0, description="Total number of tasks found")
    has_subtasks: bool = Field(default=False, description="Whether any tasks have subtasks")


# Vikunja import schemas


class VikunjaImportRequest(BaseModel):
    """Request body for importing tasks from Vikunja JSON export."""

    project_id: int = Field(..., description="Target Initiative project to import into")
    json_content: str = Field(..., description="Raw JSON content from Vikunja export")
    source_project_id: int = Field(..., description="Vikunja project ID to import from")
    bucket_mapping: Dict[int, int] = Field(
        ..., description="Mapping of Vikunja bucket IDs to task_status_id"
    )


class VikunjaBucket(BaseModel):
    """A bucket (status column) from a Vikunja project."""

    id: int
    name: str
    task_count: int


class VikunjaProject(BaseModel):
    """A project detected in the Vikunja export."""

    id: int
    name: str
    task_count: int
    buckets: List[VikunjaBucket] = Field(default_factory=list)


class VikunjaParseResult(BaseModel):
    """Result of parsing a Vikunja JSON export."""

    projects: List[VikunjaProject] = Field(
        default_factory=list, description="Projects found in the export"
    )
    total_tasks: int = Field(default=0, description="Total number of tasks across all projects")
