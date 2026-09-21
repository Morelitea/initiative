"""What one import job knows that no single envelope does.

Two facts, and both exist for the same reason: an envelope is written without
knowing where it will land. It names the far end of a link by a string the
source chose, and it names people by the handles they had somewhere else.
Neither can be resolved by the importer reading that envelope — the far end is
usually in another entry, and who somebody is here was answered by a person in
the wizard, not by the file.

So both are held for the length of the job and handed to every importer. An
importer reads what it needs and ignores the rest; most ignore both.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.import_engine.links import LinkCollector
from app.services.import_engine.people import PeopleMap


@dataclass
class ImportContext:
    """The job's shared state, passed to every ``apply``.

    Defaults are the empty versions rather than ``None``, so an importer can
    always ask without checking first: a job with nothing mapped and nothing
    linked behaves exactly as one that was never given either.
    """

    links: LinkCollector = field(default_factory=LinkCollector)
    people: PeopleMap = field(default_factory=PeopleMap)
