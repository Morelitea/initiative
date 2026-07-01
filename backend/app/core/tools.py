"""The app's tools — one canonical, app-wide enum.

A **tool** is a first-class thing an initiative offers: a project, a document, a
queue, a counter group, or a calendar event. This is the same set the six
authorization gates call "tools" (the shareable DAC resources), the set the
sharing engine keys on, and the set whose string values are persisted in
``resource_grants.resource_type``.

``Tool`` is the single source of truth for that set, app-wide — the sharing/DAC
registries, the bulk-grants API, and anywhere else that needs to name a tool kind
should reference it rather than repeating string literals. It is a ``str, Enum``
(like ``ResourceAccessLevel``), so a member *is* its string value and
interoperates transparently with the plain string column and any string-keyed
lookup.
"""

from enum import Enum


class Tool(str, Enum):
    project = "project"
    document = "document"
    queue = "queue"
    counter_group = "counter_group"
    calendar_event = "calendar_event"


# The tool string values as a set, derived from the enum (single source of truth).
TOOL_TYPES = frozenset(t.value for t in Tool)
