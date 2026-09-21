"""The credential one import job needs, for as long as that job needs it.

Reading somebody else's site — a Jira instance, a Confluence space — takes a
secret the person who asked for the import typed into the connect step. The
fetch happens in a background worker, minutes later, on a different session
from the request that collected it, so the value has to survive the gap. This
table is that gap and nothing else.

**One-shot, deliberately not a feature.** There is no saved-connection
surface: no list, no edit screen, no rotation, no reuse across jobs. A row
carries the credential from the connect request to the worker that picks the
job up, and is deleted the moment that job reaches a terminal state, is
cancelled, or ages out (``app.services.import_engine.credentials``). A durable
"connections" entity would be schema to maintain forever for a thing people do
once.

Shared rather than guild-scoped because it is written before any guild schema
is routed into, and read by the worker on the system engine. It names a guild
and it is scoped to one, but it is not guild *content*.

Locked to ``app_admin``: RLS enabled and forced with no policies — the
strictest state a table has, and correct here, since nothing on the request
path ever reads a row back. ``secret_encrypted`` is Fernet-encrypted at rest
under ``SALT_IMPORT_CREDENTIAL`` and registered for SECRET_KEY rotation.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel


class ImportCredential(SQLModel, table=True):
    __tablename__ = "import_credentials"

    id: Optional[int] = Field(default=None, primary_key=True)

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    created_by: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    #: Which foreign system this reaches — "atlassian" today.
    provider: str = Field(sa_column=Column(Text, nullable=False))
    #: The site the credential is good for, e.g. "https://acme.atlassian.net".
    site_url: str = Field(sa_column=Column(Text, nullable=False))
    #: Who the secret authenticates as at the source (an account email for an
    #: Atlassian API token). Stored so the worker can present it; it is the
    #: source's identifier for a person, never this platform's.
    principal: str = Field(sa_column=Column(Text, nullable=False))
    secret_encrypted: str = Field(sa_column=Column(Text, nullable=False))

    #: The backstop on the lifecycle above: whatever happens to the job, the
    #: row stops being usable here and the sweep removes it.
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
