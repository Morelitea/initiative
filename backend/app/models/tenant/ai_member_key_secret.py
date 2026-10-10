"""The key a member gave for one AI connection, beside the row that says they
gave one.

One row per ``guild_ai_member_keys`` row. Read and written by the member it
belongs to and the system engine alone (the ``member_secret_*`` policies,
``app.db.tenancy.MEMBER_SECRET_TABLES``): the community's seat sees and revokes
the row it hangs off, never the key.
"""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_AI_API_KEY


class AIMemberKeySecret(SQLModel, table=True):
    __tablename__ = "ai_member_key_secrets"

    key_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_ai_member_keys.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        )
    )
    api_key_encrypted: str = Field(
        sa_column=Column(
            String(2000), nullable=False, info={FERNET_SALT: SALT_AI_API_KEY}
        )
    )
