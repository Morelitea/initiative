"""Every hand-written table that has to span a vocabulary, in one place.

Each row pairs a registry somebody maintains by hand with the canonical source
it answers for — an enum, or the list that declares the vocabulary. A member
added to the source without a matching entry in the table fails the row named
after it, which is all these assertions are for.

A table the source *generates* is not a row here: comparing a comprehension to
what it was built from passes whatever anybody does. Assertions that are not a
plain set equality — a subset, a per-entry shape check — stay beside the surface
they describe.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.resource_access import RESOURCE_ACCESS
from app.core.intake import (
    CASE_FIELD_TYPES,
    STREAM_FIELDS,
    STREAMS,
    CaseField,
    IntakeStream,
)
from app.core.moderation import PLATFORM_TARGET_RELATION, PlatformReportTarget
from app.core.reactions import ReactionTarget
from app.core.tools import Tool
from app.db.soft_delete_filter import SOFT_DELETE_MODELS
from app.services.marketplace.definitions import KIND_AUDIENCE, LISTING_KINDS
from app.services.tenant.reactions import TARGET_RESOLVERS
from app.services.tenant.trash_purge import _PURGE_TOP_DOWN

pytestmark = pytest.mark.unit

#: (what it is, the hand-written table, the canonical source it answers for)
REGISTRIES: list[tuple[str, Any, Any]] = [
    (
        "every tool is reachable through the resource-access registry",
        RESOURCE_ACCESS,
        Tool,
    ),
    (
        "every soft-deletable model is swept by the purge worker",
        _PURGE_TOP_DOWN,
        SOFT_DELETE_MODELS,
    ),
    ("every intake stream says what feeds it", STREAMS, IntakeStream),
    (
        "every intake stream declares the fields its cases carry",
        STREAM_FIELDS,
        IntakeStream,
    ),
    ("every case field has a property type", CASE_FIELD_TYPES, CaseField),
    (
        "every platform report target names a relation",
        PLATFORM_TARGET_RELATION,
        PlatformReportTarget,
    ),
    ("every reactable kind has a resolver", TARGET_RESOLVERS, ReactionTarget),
    ("every listing kind says who it installs to", KIND_AUDIENCE, LISTING_KINDS),
]


@pytest.mark.parametrize(
    ("what", "registry", "canonical"),
    REGISTRIES,
    ids=[what for what, _registry, _canonical in REGISTRIES],
)
def test_a_registry_covers_the_vocabulary_it_answers_for(
    what: str, registry: Any, canonical: Any
) -> None:
    assert set(registry) == set(canonical), what
