"""Parser for extracting mention syntax from comment content.

Mention patterns:
- Users: @[Display Name](id) - e.g., @[John Doe](42)
- Tasks: #task[Title](id) - e.g., #task[Fix bug](123)
"""

import re
from typing import Set

USER_PATTERN = re.compile(r"@\[[^\]]+\]\((\d+)\)")
TASK_PATTERN = re.compile(r"#task\[[^\]]+\]\((\d+)\)")


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(match) for match in USER_PATTERN.findall(content)}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content."""
    return {int(match) for match in TASK_PATTERN.findall(content)}
