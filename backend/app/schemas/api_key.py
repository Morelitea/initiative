from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ApiKeyMetadata(BaseModel):
    id: int
    name: str
    token_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyMetadata] = Field(default_factory=list)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: Optional[datetime] = None


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyMetadata
    secret: str
