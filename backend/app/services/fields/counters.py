"""The counter datasets — the groups, and the counters inside them.

Two declarations rather than one, because they are two things a reader asks
about: how a group is doing, and what one counter reads. Both are read off their
models; a counter's own numbers are its columns, so there is nothing to add.
"""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.counter import Counter, CounterGroup
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build_groups() -> Dataset:
    return Dataset(
        model=CounterGroup,
        tool=Tool.counter_group,
        fields=derive_fields(CounterGroup),
    )


def build_counters() -> Dataset:
    return Dataset(
        model=Counter,
        # Sharing is the group's, the way a task's is its project's.
        tool=Tool.counter_group,
        name_override="counters",
        fields=derive_fields(Counter),
    )
