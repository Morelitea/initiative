from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class ApiKeyMetadata(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    token_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ApiKeyListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    keys: list[ApiKeyMetadata] = Field(default_factory=list)


class ApiKeyCreateRequest(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: Optional[datetime] = None


class ApiKeyCreateResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    api_key: ApiKeyMetadata
    secret: RawTextStr
