"""Parser for extracting mention syntax from comment content.

Mention patterns:
- Users: @{userId} - e.g., @{42}
- Tasks: #task:123
- Documents: #doc:456
- Projects: #project:789
"""

import re
from typing import Set

# Pattern for user mentions: @{id}
USER_PATTERN = re.compile(r"@\{(\d+)\}")

# Pattern for task mentions: #task:id
TASK_PATTERN = re.compile(r"#task:(\d+)")

# Pattern for document mentions: #doc:id
DOC_PATTERN = re.compile(r"#doc:(\d+)")

# Pattern for project mentions: #project:id
PROJECT_PATTERN = re.compile(r"#project:(\d+)")


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content via @{id} syntax."""
    matches = USER_PATTERN.findall(content)
    return {int(match) for match in matches}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content via #task:id syntax."""
    matches = TASK_PATTERN.findall(content)
    return {int(match) for match in matches}


def extract_mentioned_doc_ids(content: str) -> Set[int]:
    """Extract all document IDs mentioned in the content via #doc:id syntax."""
    matches = DOC_PATTERN.findall(content)
    return {int(match) for match in matches}


def extract_mentioned_project_ids(content: str) -> Set[int]:
    """Extract all project IDs mentioned in the content via #project:id syntax."""
    matches = PROJECT_PATTERN.findall(content)
    return {int(match) for match in matches}
