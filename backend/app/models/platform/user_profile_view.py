"""The public projection of ``public.users``, as the request path reads it.

``public.user_profiles`` is a view — created in migration 0214, owned by the
``app_profile_reader`` role, carrying the eight columns that are public about
an account. Which columns those are is decided in the catalog rather than here;
this is the handle the ORM needs to select from it.

Its own ``MetaData``, deliberately: a view is not a table, and putting it in
``SQLModel.metadata`` would make the table classification and drift checks
treat it as one and try to keep it in step with a model.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB

from app.models.platform.user import UserStatus

#: Not ``SQLModel.metadata`` — see the module docstring.
metadata = MetaData()

user_profiles = Table(
    "user_profiles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32)),
    Column("discriminator", SmallInteger),
    Column("avatar_url", String),
    # The real enum type, so a comparison against ``UserStatus`` binds as
    # ``user_status`` rather than text.
    Column("status", ENUM(UserStatus, name="user_status", create_type=False)),
    Column("custom_status", JSONB),
    Column("profile_decorations", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="public",
)
