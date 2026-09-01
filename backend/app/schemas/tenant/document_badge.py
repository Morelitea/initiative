"""What a badge shows right now."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.document_badges import BadgeKind, BadgeTone


class BadgeState(BaseModel):
    """One chip's current reading.

    ``text`` is always set, so a client that understands nothing else can still
    render the chip. ``date`` and ``number`` are sent alongside it where the
    value is one of those, because a date and a number belong in the reader's
    own locale and only the client knows what that is.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The ``kind:id:aspect`` this answers, echoed back so a client can match
    #: it to the chip that asked without relying on order.
    ref: str
    #: Which badge this is — ``task:status``. Saves a client parsing ``ref``,
    #: and is the set the editor's insert menu is built from.
    kind: BadgeKind
    text: str
    tone: BadgeTone
    #: A colour the thing carries itself — a task status has one. Overrides the
    #: tone where present.
    color: Optional[str] = None
    date: Optional[datetime] = None
    number: Optional[Decimal] = None


class BadgeStateList(BaseModel):
    """The chips that could be read.

    A ref that names nothing, or something this caller cannot see, is simply
    absent: the two are the same answer, and the chip falls back to the label
    the document already stored.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[BadgeState]
