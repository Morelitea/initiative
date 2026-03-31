from pydantic import BaseModel, ConfigDict


class AutomationsConfigResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
