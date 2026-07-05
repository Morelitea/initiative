"""The autogenerate object filter shared by Alembic and the drift test.

``alembic/env.py`` builds its ``include_object`` hook from here, and
``app/db/model_drift_test.py`` runs ``compare_metadata`` through the same
filter — one source of truth for what each autogenerate mode manages, so the
drift test proves exactly what ``alembic revision --autogenerate`` would see.
"""

from __future__ import annotations

from typing import Callable

from app.db.tenancy import GUILD_SCOPED_TABLES

IncludeObject = Callable[[object, str, str, bool, object], bool]


def make_include_object(guild_autogen: bool) -> IncludeObject:
    """Build the ``include_object`` hook for one autogenerate mode.

    Keeps each mode on its own tables — and, in guild mode, on its own OBJECT
    KINDS.

    Default mode compares shared/public tables only: guild-content tables live
    in the per-guild schemas, so without the filter autogenerate would try to
    CREATE them in ``public`` on a fresh database (the model metadata still
    declares them for the ORM) or DROP/ALTER the frozen legacy copies on a
    pre-squash database.

    Guild mode (``-x guild``) inverts the table filter (guild-content tables
    only, compared against ``guild_template``) and additionally scopes WHAT
    autogenerate manages, mirroring the established division of labor:

    * models own **tables + columns** — that's what guild autogen diffs;
    * the artifacts own the dressing — FKs keep their PG-authored names and
      deliberately omit cross-schema references, partial/GIN indexes carry
      opclasses reflection loses (preserving them is WHY provisioning
      reflects pg catalogs — see app.db.guild_ddl), and CHECKs come from
      pg_get_constraintdef — so
      constraint/index objects that exist only on one side are not diffs to
      emit. Metadata-declared indexes/uniques missing from the template are
      still created (a real model change); reflected-only ones are never
      dropped.
    * ``guild_id`` columns are trigger-populated and DDL-owned (NOT NULL in
      the schema, Optional in models) — their nullability is not a diff.
    """

    def include_object(obj, name, type_, reflected, compare_to) -> bool:
        if type_ == "table":
            return (name in GUILD_SCOPED_TABLES) == guild_autogen

        table = getattr(obj, "table", None)  # indexes/constraints/columns
        in_guild_tables = table is not None and table.name in GUILD_SCOPED_TABLES
        if not guild_autogen:
            return not in_guild_tables
        if table is not None and not in_guild_tables:
            return False

        if type_ == "foreign_key_constraint":
            return False  # wholly artifact-owned (names + cross-schema omissions)
        if type_ in ("index", "unique_constraint", "check_constraint"):
            return not reflected or compare_to is not None  # never drop artifact-owned
        if type_ == "column" and name == "guild_id":
            return False  # trigger-populated; DDL owns its NOT NULL
        return True

    return include_object
