"""The values a community's seat typed into an installed app's connections.

One row per install, beside the ``guild_apps`` row it belongs to. It holds what
``guild_apps`` reports only as present: one Fernet ciphertext per secret field,
keyed by connection id then field key, with the tokens a vendor flow stored
under the reserved token keys.

Read and written by the seat and the system engine alone (the ``seat_*``
policies, ``app.db.tenancy.SEAT_READ_TABLES``). A trigger keeps
``guild_apps.secret_fields`` in step with it, so what a member reads is which
keys hold a value and nothing more.

No row reads the same as an empty map.
"""

from typing import Any

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class GuildAppSecret(SQLModel, table=True):
    __tablename__ = "guild_app_secrets"

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_apps.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        )
    )
    # ``{"admin_read": {"api_key": "<ciphertext>"}}``.
    secrets: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
