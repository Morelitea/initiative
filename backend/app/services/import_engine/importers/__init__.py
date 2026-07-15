"""Per-type importer registry: envelope ``type`` → importer instance.

The single dispatch point for both the envelope endpoint and (later) the
backup orchestrator — an unknown discriminator is rejected centrally by
``engine.get_importer``.
"""

from app.services.import_engine.importers.calendar_events import (
    CalendarEventsImporter,
)
from app.services.import_engine.importers.counter_group import CounterGroupImporter
from app.services.import_engine.importers.document import DocumentImporter
from app.services.import_engine.importers.project import ProjectImporter
from app.services.import_engine.importers.queue import QueueImporter

IMPORTERS = {
    importer.envelope_type: importer
    for importer in (
        ProjectImporter(),
        DocumentImporter(),
        QueueImporter(),
        CounterGroupImporter(),
        CalendarEventsImporter(),
    )
}

__all__ = ["IMPORTERS"]
