"""What the audit board is served.

Identity is resolved here, at read time, and only for accounts that still
exist: the row itself holds ids, so it survives an erasure that the names in it
would not.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class AuditActor(SanitizedBaseModel):
    """Who an id points at now, or nothing if the account is gone."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    username: Optional[str] = None
    discriminator: Optional[int] = None


class AuditEventRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    event_uuid: str
    event_type: str
    category: str
    tier: int
    occurred_at: datetime
    actor: AuditActor
    target_user: Optional[AuditActor] = None
    guild_id: Optional[int] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    detail: dict[str, Any] = {}


class AuditEventListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[AuditEventRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool
