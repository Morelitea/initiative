"""Service for importing tasks from external platforms."""

import csv
import io
import json
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskPriority, Subtask
from app.schemas.import_data import (
    ImportResult,
    TodoistSection,
    TodoistParseResult,
    VikunjaBucket,
    VikunjaProject,
    VikunjaParseResult,
)


# Todoist priority mapping (Todoist uses 1=highest, 4=lowest)
TODOIST_PRIORITY_MAP: Dict[int, TaskPriority] = {
    1: TaskPriority.urgent,
    2: TaskPriority.high,
    3: TaskPriority.medium,
    4: TaskPriority.low,
}

# Vikunja priority mapping (Vikunja uses 0=none, 1=low, 5=urgent)
VIKUNJA_PRIORITY_MAP: Dict[int, TaskPriority] = {
    0: TaskPriority.low,
    1: TaskPriority.low,
    2: TaskPriority.medium,
    3: TaskPriority.medium,
    4: TaskPriority.high,
    5: TaskPriority.urgent,
}


def extract_task_list_items(html: str) -> tuple[list[dict], str]:
    """
    Extract task list items from HTML and return them separately.

    Returns:
        Tuple of (list of task items with 'content' and 'is_completed', remaining HTML)
    """
    if not html:
        return [], ""

    items: list[dict] = []

    # Match task list items: <li data-checked="true/false" data-type="taskItem">...<p>content</p>...</li>
    pattern = r'<li[^>]*data-checked="(true|false)"[^>]*data-type="taskItem"[^>]*>.*?<p>(.*?)</p>.*?</li>'

    for match in re.finditer(pattern, html, flags=re.DOTALL):
        is_completed = match.group(1) == "true"
        content = match.group(2).strip()
        # Clean any nested HTML from content
        content = re.sub(r"<[^>]+>", "", content).strip()
        if content:
            items.append({"content": content, "is_completed": is_completed})

    # Remove task lists from HTML
    remaining = re.sub(r'<ul[^>]*data-type="taskList"[^>]*>.*?</ul>', "", html, flags=re.DOTALL)

    return items, remaining


def html_to_markdown(html: str) -> str:
    """Convert simple HTML to markdown."""
    if not html:
        return ""

    text = html

    # Block elements - handle before inline
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h4[^>]*>(.*?)</h4>", r"#### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h5[^>]*>(.*?)</h5>", r"##### \1\n", text, flags=re.DOTALL)
    text = re.sub(r"<h6[^>]*>(.*?)</h6>", r"###### \1\n", text, flags=re.DOTALL)

    # Lists
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"</?[ou]l[^>]*>", "", text)

    # Paragraphs and line breaks
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<div[^>]*>(.*?)</div>", r"\1\n", text, flags=re.DOTALL)

    # Inline formatting
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<s[^>]*>(.*?)</s>", r"~~\1~~", text, flags=re.DOTALL)
    text = re.sub(r"<strike[^>]*>(.*?)</strike>", r"~~\1~~", text, flags=re.DOTALL)

    # Links and images
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*/?>',r"![\2](\1)", text)
    text = re.sub(r'<img[^>]*src="([^"]*)"[^>]*/?>',r"![](\1)", text)

    # Code blocks
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```\n", text, flags=re.DOTALL)

    # Blockquotes
    text = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", r"> \1\n", text, flags=re.DOTALL)

    # Horizontal rules
    text = re.sub(r"<hr\s*/?>", "\n---\n", text)

    # Remove any remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def parse_todoist_csv(csv_content: str) -> Tuple[TodoistParseResult, List[dict]]:
    """
    Parse Todoist CSV export and extract sections and tasks.

    Returns:
        Tuple of (parse_result with metadata, list of task dicts)
    """
    # Handle BOM if present
    if csv_content.startswith("\ufeff"):
        csv_content = csv_content[1:]

    reader = csv.DictReader(io.StringIO(csv_content))

    sections: Dict[str, int] = {}  # section_name -> task_count
    tasks: List[dict] = []
    current_section: Optional[str] = None
    has_subtasks = False

    for row in reader:
        row_type = row.get("TYPE", "").strip().lower()

        if row_type == "meta":
            # Skip metadata rows
            continue
        elif row_type == "section":
            # New section
            section_name = row.get("CONTENT", "").strip()
            if section_name:
                current_section = section_name
                if section_name not in sections:
                    sections[section_name] = 0
        elif row_type == "task":
            # Task row
            content = row.get("CONTENT", "").strip()
            if not content:
                continue

            indent = int(row.get("INDENT", "1") or "1")
            if indent > 1:
                has_subtasks = True

            # Get priority (Todoist uses 1-4, where 1 is highest)
            try:
                todoist_priority = int(row.get("PRIORITY", "4") or "4")
            except ValueError:
                todoist_priority = 4

            task_data = {
                "title": content,
                "description": row.get("DESCRIPTION", "").strip() or None,
                "priority": todoist_priority,
                "indent": indent,
                "section": current_section,
                "responsible": row.get("RESPONSIBLE", "").strip() or None,
                "date": row.get("DATE", "").strip() or None,
            }
            tasks.append(task_data)

            # Count tasks per section
            if current_section and current_section in sections:
                sections[current_section] += 1

    # Build result
    section_list = [
        TodoistSection(name=name, task_count=count) for name, count in sections.items()
    ]

    parse_result = TodoistParseResult(
        sections=section_list,
        task_count=len([t for t in tasks if t["indent"] == 1]),  # Only top-level tasks
        has_subtasks=has_subtasks,
    )

    return parse_result, tasks


async def import_todoist_tasks(
    session: AsyncSession,
    project_id: int,
    csv_content: str,
    section_mapping: Dict[str, int],
) -> ImportResult:
    """
    Import tasks from Todoist CSV into a project.

    Args:
        session: Database session
        project_id: Target project ID
        csv_content: Raw CSV content
        section_mapping: Mapping of section names to task_status_id

    Returns:
        ImportResult with counts and errors
    """
    result = ImportResult()

    try:
        _, tasks = parse_todoist_csv(csv_content)
    except Exception as e:
        result.errors.append(f"Failed to parse CSV: {str(e)}")
        return result

    if not tasks:
        result.errors.append("No tasks found in CSV")
        return result

    # Get the next sort_order for the project
    max_order_result = await session.execute(
        select(func.coalesce(func.max(Task.sort_order), 0)).where(
            Task.project_id == project_id
        )
    )
    next_sort_order = float(max_order_result.scalar() or 0) + 1

    # Track parent tasks for subtask creation
    last_parent_task: Optional[Task] = None
    subtask_position = 0

    for task_data in tasks:
        try:
            section = task_data.get("section")
            indent = task_data.get("indent", 1)

            # Get status from mapping
            status_id = section_mapping.get(section) if section else None
            if status_id is None:
                # Use first mapped status as default
                status_id = next(iter(section_mapping.values()), None)

            if status_id is None:
                result.errors.append(
                    f"No status mapping for section '{section}', skipping task: {task_data['title']}"
                )
                result.tasks_failed += 1
                continue

            # Map priority
            todoist_priority = task_data.get("priority", 4)
            priority = TODOIST_PRIORITY_MAP.get(todoist_priority, TaskPriority.low)

            if indent == 1:
                # Top-level task
                task = Task(
                    project_id=project_id,
                    task_status_id=status_id,
                    title=task_data["title"],
                    description=task_data.get("description"),
                    priority=priority,
                    sort_order=next_sort_order,
                )
                session.add(task)
                await session.flush()

                last_parent_task = task
                subtask_position = 0
                next_sort_order += 1
                result.tasks_created += 1
            else:
                # Subtask (indent > 1)
                if last_parent_task is None:
                    result.errors.append(
                        f"Subtask without parent task, skipping: {task_data['title']}"
                    )
                    result.tasks_failed += 1
                    continue

                subtask = Subtask(
                    task_id=last_parent_task.id,
                    content=task_data["title"],
                    is_completed=False,
                    position=subtask_position,
                )
                session.add(subtask)
                subtask_position += 1
                result.subtasks_created += 1

        except Exception as e:
            result.errors.append(f"Failed to import task '{task_data.get('title', 'unknown')}': {str(e)}")
            result.tasks_failed += 1

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        result.tasks_created = 0
        result.subtasks_created = 0
        result.tasks_failed = len(tasks)
        result.errors = [f"Failed to commit import: {str(e)}"]

    return result


def parse_vikunja_json(json_content: str) -> VikunjaParseResult:
    """
    Parse Vikunja JSON export and extract projects with their buckets and task counts.

    Returns:
        VikunjaParseResult with project metadata
    """
    data = json.loads(json_content)

    if not isinstance(data, list):
        raise ValueError("Invalid Vikunja export format: expected array of projects")

    projects: List[VikunjaProject] = []
    total_tasks = 0

    for project_data in data:
        tasks = project_data.get("tasks") or []
        task_count = len(tasks)
        total_tasks += task_count

        # Count tasks per bucket
        bucket_task_counts: Dict[int, int] = {}
        for task in tasks:
            bucket_id = task.get("bucket_id", 0)
            bucket_task_counts[bucket_id] = bucket_task_counts.get(bucket_id, 0) + 1

        # Build bucket list
        buckets: List[VikunjaBucket] = []
        for bucket_data in project_data.get("buckets") or []:
            bucket_id = bucket_data.get("id", 0)
            buckets.append(
                VikunjaBucket(
                    id=bucket_id,
                    name=bucket_data.get("title", "Unknown"),
                    task_count=bucket_task_counts.get(bucket_id, 0),
                )
            )

        # Add "No Bucket" if there are tasks without a bucket
        no_bucket_count = bucket_task_counts.get(0, 0)
        if no_bucket_count > 0:
            buckets.insert(
                0,
                VikunjaBucket(id=0, name="No Bucket", task_count=no_bucket_count),
            )

        projects.append(
            VikunjaProject(
                id=project_data.get("id", 0),
                name=project_data.get("title", "Unknown Project"),
                task_count=task_count,
                buckets=buckets,
            )
        )

    # Sort projects by task count (most tasks first), filter out empty
    projects = sorted(
        [p for p in projects if p.task_count > 0], key=lambda p: -p.task_count
    )

    return VikunjaParseResult(projects=projects, total_tasks=total_tasks)


async def import_vikunja_tasks(
    session: AsyncSession,
    project_id: int,
    json_content: str,
    source_project_id: int,
    bucket_mapping: Dict[int, int],
) -> ImportResult:
    """
    Import tasks from a Vikunja project into an Initiative project.

    Args:
        session: Database session
        project_id: Target Initiative project ID
        json_content: Raw JSON content from Vikunja export
        source_project_id: Vikunja project ID to import from
        bucket_mapping: Mapping of Vikunja bucket IDs to task_status_id

    Returns:
        ImportResult with counts and errors
    """
    result = ImportResult()

    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        result.errors.append(f"Invalid JSON: {str(e)}")
        return result

    # Find the source project
    source_project = None
    for p in data:
        if p.get("id") == source_project_id:
            source_project = p
            break

    if source_project is None:
        result.errors.append(f"Project with ID {source_project_id} not found in export")
        return result

    tasks = source_project.get("tasks") or []
    if not tasks:
        result.errors.append("No tasks found in the selected project")
        return result

    # Get the next sort_order for the project
    max_order_result = await session.execute(
        select(func.coalesce(func.max(Task.sort_order), 0)).where(
            Task.project_id == project_id
        )
    )
    next_sort_order = float(max_order_result.scalar() or 0) + 1

    for task_data in tasks:
        try:
            bucket_id = task_data.get("bucket_id", 0)

            # Get status from mapping
            status_id = bucket_mapping.get(bucket_id)
            if status_id is None:
                # Try bucket 0 (no bucket) as fallback
                status_id = bucket_mapping.get(0)
            if status_id is None:
                # Use first mapped status as default
                status_id = next(iter(bucket_mapping.values()), None)

            if status_id is None:
                result.errors.append(
                    f"No status mapping for bucket {bucket_id}, skipping: {task_data.get('title')}"
                )
                result.tasks_failed += 1
                continue

            # Map priority
            vikunja_priority = task_data.get("priority", 0)
            priority = VIKUNJA_PRIORITY_MAP.get(vikunja_priority, TaskPriority.low)

            # Extract task list items and convert remaining HTML to markdown
            description_html = task_data.get("description", "")
            subtask_items: list[dict] = []
            description: Optional[str] = None
            if description_html:
                subtask_items, remaining_html = extract_task_list_items(description_html)
                description = html_to_markdown(remaining_html) or None

            task = Task(
                project_id=project_id,
                task_status_id=status_id,
                title=task_data.get("title", "Untitled"),
                description=description,
                priority=priority,
                sort_order=next_sort_order,
            )
            session.add(task)
            await session.flush()  # Get task ID for subtasks

            # Create subtasks from extracted task list items
            for position, item in enumerate(subtask_items):
                subtask = Subtask(
                    task_id=task.id,
                    content=item["content"],
                    is_completed=item["is_completed"],
                    position=position,
                )
                session.add(subtask)
                result.subtasks_created += 1

            next_sort_order += 1
            result.tasks_created += 1

        except Exception as e:
            result.errors.append(
                f"Failed to import task '{task_data.get('title', 'unknown')}': {str(e)}"
            )
            result.tasks_failed += 1

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        result.tasks_created = 0
        result.subtasks_created = 0
        result.tasks_failed = len(tasks)
        result.errors = [f"Failed to commit import: {str(e)}"]

    return result
