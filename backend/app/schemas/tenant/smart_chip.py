"""What a smart chip shows right now."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.smart_chips import SmartChipAspect, SmartChipTone
from app.core.search import SearchEntityType


class SmartChipState(BaseModel):
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
    #: What the reference names.
    entity_type: SearchEntityType
    #: Which fact about it, or absent where this is simply what it is called.
    aspect: Optional[SmartChipAspect] = None
    text: str
    tone: SmartChipTone
    #: A colour the thing carries itself — a task status has one. Overrides the
    #: tone where present.
    color: Optional[str] = None
    date: Optional[datetime] = None
    number: Optional[Decimal] = None


class SmartChipStateList(BaseModel):
    """The chips that could be read.

    A ref that names nothing, or something this caller cannot see, is simply
    absent: the two are the same answer, and the chip falls back to the label
    the document already stored.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[SmartChipState]
