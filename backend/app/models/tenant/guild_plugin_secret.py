"""The values a community's seat typed into an installed plug-in's connections.

One row per install, beside the ``guild_plugins`` row it belongs to. It holds what
``guild_plugins`` reports only as present: one Fernet ciphertext per secret field,
keyed by connection id then field key, with the tokens a vendor flow stored
under the reserved token keys.

Read and written by the seat and the system engine alone (the ``seat_*``
policies, ``app.db.tenancy.SEAT_READ_TABLES``). A trigger keeps
``guild_plugins.secret_fields`` in step with it, so what a member reads is which
keys hold a value and nothing more.

No row reads the same as an empty map.
"""

from typing import Any

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_PLUGIN_CONFIG


class GuildPluginSecret(SQLModel, table=True):
    __tablename__ = "guild_plugin_secrets"

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        )
    )
    # ``{"admin_read": {"api_key": "<ciphertext>"}}``.
    secrets: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default="{}",
            info={FERNET_SALT: SALT_PLUGIN_CONFIG},
        ),
    )
