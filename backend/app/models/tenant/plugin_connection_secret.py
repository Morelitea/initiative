"""The values a member's connection to a plug-in's vendor holds, beside the row
that says the connection exists.

One row per ``guild_plugin_user_connections`` row: one Fernet ciphertext per
secret field, and the tokens a vendor flow stored under the reserved token
keys. Read and written by the member it belongs to and the system engine alone
(the ``member_secret_*`` policies, ``app.db.tenancy.MEMBER_SECRET_TABLES``). A
trigger keeps ``guild_plugin_user_connections.secret_fields`` in step with it,
so the row everyone else reads says which keys hold a value and nothing more.

No row reads the same as an empty map.
"""

from typing import Any

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_PLUGIN_CONFIG


class PluginConnectionSecret(SQLModel, table=True):
    __tablename__ = "plugin_connection_secrets"

    connection_row_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugin_user_connections.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        )
    )
    # ``{"api_key": "<ciphertext>", "access_token": "<ciphertext>"}``.
    secrets: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default="{}",
            info={FERNET_SALT: SALT_PLUGIN_CONFIG},
        ),
    )
