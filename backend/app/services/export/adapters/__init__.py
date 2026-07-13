"""Source-adapter registry: which sources exist and which formats each
supports. Unsupported source×format combos are rejected centrally by
``engine.get_adapter``."""

from app.services.export.adapters.counter_group import CounterGroupAdapter
from app.services.export.adapters.document import DocumentAdapter
from app.services.export.adapters.project import ProjectAdapter
from app.services.export.adapters.queue import QueueAdapter
from app.services.export.adapters.tasks_table import TasksTableAdapter

ADAPTERS = {
    adapter.source: adapter
    for adapter in (
        TasksTableAdapter(),
        ProjectAdapter(),
        DocumentAdapter(),
        QueueAdapter(),
        CounterGroupAdapter(),
    )
}

__all__ = ["ADAPTERS"]
