"""Parser for extracting mention syntax from comment content.

Mention patterns:
- Users: @[Display Name](id) - e.g., @[John Doe](42)
- Tasks: #task[Title](id) - e.g., #task[Fix bug](123)
- Documents: #doc[Title](id) - e.g., #doc[Meeting Notes](456)
- Projects: #project[Name](id) - e.g., #project[Alpha](789)
"""

import re
from typing import Set

USER_PATTERN = re.compile(r"@\[[^\]]+\]\((\d+)\)")
TASK_PATTERN = re.compile(r"#task\[[^\]]+\]\((\d+)\)")
DOC_PATTERN = re.compile(r"#doc\[[^\]]+\]\((\d+)\)")
PROJECT_PATTERN = re.compile(r"#project\[[^\]]+\]\((\d+)\)")


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(match) for match in USER_PATTERN.findall(content)}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content."""
    return {int(match) for match in TASK_PATTERN.findall(content)}


def extract_mentioned_doc_ids(content: str) -> Set[int]:
    """Extract all document IDs mentioned in the content."""
    return {int(match) for match in DOC_PATTERN.findall(content)}


def extract_mentioned_project_ids(content: str) -> Set[int]:
    """Extract all project IDs mentioned in the content."""
    return {int(match) for match in PROJECT_PATTERN.findall(content)}
