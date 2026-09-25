"""What an installed app sends to call another app through Initiative."""

from typing import Any, Dict

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel

__all__ = ["AppHubCall"]


class AppHubCall(SanitizedBaseModel):
    """One call's parameters, checked against the ones the endpoint declares
    and passed on as they are."""

    model_config = ConfigDict(extra="forbid")

    params: Dict[str, Any] = {}
