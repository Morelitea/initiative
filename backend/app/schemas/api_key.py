from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    token_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ApiKeyListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    keys: list[ApiKeyMetadata] = Field(default_factory=list)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: Optional[datetime] = None


class ApiKeyCreateResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    api_key: ApiKeyMetadata
    secret: str
