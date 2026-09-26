"""Guild-owned AI connections (guild config mode).

Used when ``ai_config_mode == "guild"``: a guild admin configures the
guild's AI providers here (guild schema). Members attach their own keys
referencing these by ``(scope="guild", id)``. Guild-level table (guild-wide
config, schema-boundary protected). ``base_url`` is validated public-only —
a guild admin can never persist a private/internal target.
"""

from pydantic import ConfigDict

from app.models.platform.ai_connection import AIConnectionColumns
from app.models.tenant._mixins import CreatedByMixin


class GuildAIConnection(AIConnectionColumns, CreatedByMixin, table=True):
    __tablename__ = "guild_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
