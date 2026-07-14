"""Tests for per-guild schema provisioning.

Use a synthetic, high guild id so the temporary ``guild_<id>`` schema can't
collide with real data, and drop it in teardown. Runs against the test DB as
the owning role (the ``engine`` fixture), which has DDL privileges.
"""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

import app.db.schema_provisioning as schema_provisioning
from app.db.schema_provisioning import (
    SUPPORT_WRITE_PROTECTED_TABLES,
    backfill_guild_schemas,
    drop_guild_schema,
    guild_readonly_role_name,
    guild_role_name,
    guild_schema_name,
    guild_support_role_name,
    provision_guild_schema,
)
from app.db.tenancy import GUILD_SCOPED_TABLES

pytestmark = pytest.mark.database

# Synthetic ids well above any real guild; each test uses its own.
_GID_COMPLETE = 990_101
_GID_ISOLATION = 990_102
_GID_IDEMPOTENT = 990_103
_GID_ROLE_A = 990_104
_GID_ROLE_B = 990_105
_GID_ROLE_DROP = 990_106
_GID_ROLE_WRITE = 990_107
_GID_BACKFILL = 990_108
_GID_REPROVISION = 990_109
_GID_DROP_ABSENT = 990_110
_GID_SUPPORT = 990_120
# Back-fill sweep (each pair: one provisioned, one only a public row).
_GID_BACKFILL_DONE = 990_111
_GID_BACKFILL_MISSING = 990_112
_GID_BACKFILL_DRIFT = 990_113
_GID_BACKFILL_OK_A = 990_114
_GID_BACKFILL_OK_B = 990_115
_GID_BACKFILL_FAIL = 990_116


async def _insert_public_guild(conn, gid: int, name: str) -> None:
    """Insert a public.guilds row so guild-scoped FKs (-> public.guilds) hold."""
    await conn.execute(
        text(
            "INSERT INTO public.guilds (id, name, created_at, updated_at) "
            "VALUES (:id, :n, now(), now())"
        ),
        {"id": gid, "n": name},
    )


async def test_provision_creates_every_guild_scoped_table(engine):
    schema = guild_schema_name(_GID_COMPLETE)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_COMPLETE)
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            )
            created = {row[0] for row in res}
        assert created == set(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_COMPLETE)


async def test_writes_route_to_guild_schema_not_public(engine):
    """A routed tenant write lands in the guild schema; an UNROUTED one fails.

    Post-squash there is no ``public`` copy of a tenant table, so isolation is the
    schema boundary itself: the row can only exist in ``guild_<id>``, and a write
    with the search_path still on ``public`` fails closed (relation does not
    exist) instead of silently leaking into a shared public copy."""
    gid = _GID_ISOLATION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "provision-iso-test")
            # Same unqualified INSERT, but routed via the guild search_path.
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            # 9-char alpha color also exercises the widened tags.color column.
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#abcdef80', now(), now())"
                ),
                {"g": gid, "n": "iso-tag"},
            )
            await conn.exec_driver_sql("SET search_path TO public")

            in_guild = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
        assert in_guild == 1, "row should be in the guild schema"

        # The tenant table has NO public copy since the v0.53.5 squash — an
        # unrouted (public search_path) tenant write fails closed rather than
        # landing in a shared public table.
        async with engine.connect() as conn:
            public_tags = await conn.scalar(text("SELECT to_regclass('public.tags')"))
        assert public_tags is None, "there must be NO public.tags copy post-squash"

        with pytest.raises(ProgrammingError):
            async with engine.begin() as conn:
                await conn.exec_driver_sql("SET search_path TO public")
                await conn.execute(
                    text(
                        "INSERT INTO tags (guild_id, name, color, created_at, "
                        "updated_at) VALUES (:g, :n, '#abcdef80', now(), now())"
                    ),
                    {"g": gid, "n": "unrouted-tag"},
                )
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_provision_is_idempotent(engine):
    """Calling provision twice is a no-op, not an error."""
    gid = _GID_IDEMPOTENT
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await provision_guild_schema(conn, gid)  # must not raise
        async with engine.connect() as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            )
        assert count == len(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_is_scoped_to_its_own_schema(engine):
    """The per-guild role can reach its own schema but is denied another's.

    This is the fail-closed boundary: Postgres denies a role access to any
    schema it lacks USAGE on, *before* any RLS evaluates.
    """
    a, b = _GID_ROLE_A, _GID_ROLE_B
    role_a = guild_role_name(a)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, a)
            await provision_guild_schema(conn, b)

        # Assuming guild A's role, its own schema is readable.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            own = await conn.scalar(
                text(f'SELECT count(*) FROM "{guild_schema_name(a)}".tags')
            )
            await conn.exec_driver_sql("RESET ROLE")
        assert own == 0

        # ...but guild B's schema is denied at the catalog layer.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            with pytest.raises(ProgrammingError) as exc:
                await conn.scalar(
                    text(f'SELECT count(*) FROM "{guild_schema_name(b)}".tags')
                )
            assert "permission denied" in str(exc.value).lower()
            await conn.rollback()  # clear the aborted txn before resetting role
            await conn.exec_driver_sql("RESET ROLE")
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, a)
            await drop_guild_schema(conn, b)


async def test_drop_guild_schema_removes_role(engine):
    """Tearing down a guild drops ALL its roles too, not just the schema."""
    gid = _GID_ROLE_DROP
    roles = (
        guild_role_name(gid),
        guild_readonly_role_name(gid),
        guild_support_role_name(gid),
    )
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            before = [
                await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": r}
                )
                for r in roles
            ]
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
        async with engine.connect() as conn:
            after = [
                await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": r}
                )
                for r in roles
            ]
        assert before == [1, 1, 1], "all three roles should exist after provisioning"
        assert after == [None, None, None], "all three roles should be gone after drop"
    finally:
        # Defensive: ensure no leftover role/schema if an assertion failed early.
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_support_role_write_capped_on_protected_tables(engine):
    """The restricted ``support`` role reads everything and writes content, but
    the structural / permission tables are SELECT-only — the DB-enforced
    'no member/permission management' line, checked via has_table_privilege."""
    gid = _GID_SUPPORT
    schema = guild_schema_name(gid)
    support = guild_support_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:

            async def priv(table: str, verb: str) -> bool:
                return await conn.scalar(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": support, "t": f"{schema}.{table}", "p": verb},
                )

            # Protected tables: readable, but no writes.
            for table in SUPPORT_WRITE_PROTECTED_TABLES:
                assert await priv(table, "SELECT") is True, f"{table} SELECT"
                for verb in ("INSERT", "UPDATE", "DELETE"):
                    assert await priv(table, verb) is False, f"{table} {verb}"

            # Content + guild settings: full DML (settings write is the carve-out).
            for table in ("tasks", "guild_settings"):
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert await priv(table, verb) is True, f"{table} {verb}"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_can_write_in_its_own_schema(engine):
    """The role's DML grant actually works — it can INSERT, not just SELECT."""
    gid = _GID_ROLE_WRITE
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "role-write")
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#112233', now(), now())"
                ),
                {"g": gid, "n": "written-by-role"},
            )
            written = await conn.scalar(text("SELECT count(*) FROM tags"))
            await conn.exec_driver_sql("SET search_path TO public")
            await conn.exec_driver_sql("RESET ROLE")
        assert written == 1
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_reprovision_backfills_missing_tables_with_grants(engine):
    """Re-provisioning recreates a table missing from the schema and grants it.

    Stands in for "a new guild-scoped table was added to the manifest": the
    table is absent from an existing schema, and a re-provision must create it
    *and* extend the role's access to it.
    """
    gid = _GID_BACKFILL
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            # Simulate a table that didn't exist when the schema was first made.
            await conn.exec_driver_sql(f'DROP TABLE "{schema}".subtasks CASCADE')

        async with engine.connect() as conn:
            gone = await conn.scalar(text(f"SELECT to_regclass('{schema}.subtasks')"))
        assert gone is None, "precondition: subtasks dropped"

        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # back-fill

        async with engine.connect() as conn:
            recreated = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.subtasks')")
            )
            # and the role's grant reaches the back-filled table. Route the
            # search_path into the guild schema first: subtasks' initiative-member
            # RLS policy references tasks/projects/initiative_members unqualified,
            # and post-squash those live only in the guild schema (no public copy).
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            readable = await conn.scalar(text("SELECT count(*) FROM subtasks"))
            await conn.exec_driver_sql("RESET ROLE")
            await conn.exec_driver_sql("SET search_path TO public")
        assert recreated is not None, "subtasks should be back-filled"
        assert readable == 0, "role should be able to read the back-filled table"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_reprovision_preserves_existing_rows(engine):
    """Idempotency must not wipe data: a second provision keeps existing rows."""
    gid = _GID_REPROVISION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "reprovision")
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#445566', now(), now())"
                ),
                {"g": gid, "n": "survivor"},
            )
            await conn.exec_driver_sql("SET search_path TO public")
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # second time
        async with engine.connect() as conn:
            count = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
        assert count == 1, "existing row must survive a re-provision"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_drop_guild_schema_is_safe_when_absent(engine):
    """Dropping a guild that was never provisioned is a no-op, not an error."""
    async with engine.begin() as conn:
        await drop_guild_schema(conn, _GID_DROP_ABSENT)  # must not raise


# --- drift guard: the provisioned guild schema must equal guild_template --------

_GID_DRIFT = 990_120

# The Alembic-maintained canonical guild schema (created by migration
# 20260701_0126 by running guild_schema.sql + guild_rls.sql). Post-squash there
# are no tenant tables in ``public``, so the drift reference is the template.
_TEMPLATE_SCHEMA = "guild_template"


def _norm_default(d):
    # Per-schema sequences are correct; collapse nextval(...) so the seq name
    # (and a legacy rename like teams_id_seq) doesn't read as drift.
    return re.sub(r"nextval\('[^']+'::regclass\)", "nextval(SEQ)", d) if d else d


def _norm_constraint(s):
    # PG re-renders array casts on round-trip; strip cast/paren/space noise so a
    # semantically identical CHECK doesn't read as drift.
    s = re.sub(
        r"::(?:text|character varying|varchar|bpchar|integer|bigint)(?:\[\])?", "", s
    )
    return re.sub(r"[\s()\[\]]", "", s)


async def test_guild_schema_matches_guild_template(engine):
    """A provisioned guild schema must be a structurally faithful CLONE of the
    ``guild_template`` schema it was rendered from (``app.db.guild_ddl`` reflects
    the live template) — same columns/types/nullability/defaults, CHECK/PK/UNIQUE,
    indexes (incl. opclasses), and intra-schema FK ON DELETE rules. Cross-schema
    FKs are intentionally absent (soft refs). This catches any fidelity gap in the
    live-reflection renderer."""
    schema = guild_schema_name(_GID_DRIFT)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_DRIFT)

        async with engine.connect() as conn:

            async def cols(ns, t):
                r = await conn.execute(
                    text(
                        "SELECT a.attname a, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull n, "
                        "pg_get_expr(ad.adbin,ad.adrelid) d FROM pg_attribute a "
                        "LEFT JOIN pg_attrdef ad ON ad.adrelid=a.attrelid AND ad.adnum=a.attnum "
                        "WHERE a.attrelid=(:ns||'.'||:t)::regclass AND a.attnum>0 AND NOT a.attisdropped"
                    ),
                    {"ns": ns, "t": t},
                )
                return {x.a: (x.ty, x.n, _norm_default(x.d)) for x in r}

            async def cons(ns, t):  # CHECK/PK/UNIQUE
                r = await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) d FROM pg_constraint "
                        "WHERE conrelid=(:ns||'.'||:t)::regclass AND contype IN ('c','p','u')"
                    ),
                    {"ns": ns, "t": t},
                )
                return sorted(_norm_constraint(x.d) for x in r)

            async def intra_fks(ns, t):  # (target, ON DELETE) for guild->guild FKs only
                r = await conn.execute(
                    text(
                        "SELECT tgt.relname g, con.confdeltype::text d FROM pg_constraint con "
                        "JOIN pg_class tgt ON tgt.oid=con.confrelid "
                        "WHERE con.conrelid=(:ns||'.'||:t)::regclass AND con.contype='f' "
                        "AND tgt.relname = ANY(:gs)"
                    ),
                    {"ns": ns, "t": t, "gs": list(GUILD_SCOPED_TABLES)},
                )
                return {(x.g, x.d) for x in r}

            async def idx(ns, t):  # the USING ... part is schema-independent
                r = await conn.execute(
                    text(
                        "SELECT indexdef i FROM pg_indexes WHERE schemaname=:ns AND tablename=:t"
                    ),
                    {"ns": ns, "t": t},
                )
                return sorted(x.i.split(" USING ", 1)[1] for x in r if " USING " in x.i)

            async def trig(ns, t):  # guild_id denorm triggers (functions stay shared)
                r = await conn.execute(
                    text(
                        "SELECT pg_get_triggerdef(tg.oid) d FROM pg_trigger tg "
                        "JOIN pg_class cl ON cl.oid=tg.tgrelid "
                        "WHERE cl.oid=(:ns||'.'||:t)::regclass AND NOT tg.tgisinternal"
                    ),
                    {"ns": ns, "t": t},
                )
                return sorted(
                    re.sub(r"\bON \w+\.", "ON ", x.d) for x in r
                )  # strip table schema

            drift = []
            for t in sorted(GUILD_SCOPED_TABLES):
                if await cols(_TEMPLATE_SCHEMA, t) != await cols(schema, t):
                    drift.append(f"columns: {t}")
                if await cons(_TEMPLATE_SCHEMA, t) != await cons(schema, t):
                    drift.append(f"constraints: {t}")
                if await intra_fks(_TEMPLATE_SCHEMA, t) != await intra_fks(schema, t):
                    drift.append(f"foreign keys: {t}")
                if await idx(_TEMPLATE_SCHEMA, t) != await idx(schema, t):
                    drift.append(f"indexes: {t}")
                if await trig(_TEMPLATE_SCHEMA, t) != await trig(schema, t):
                    drift.append(f"triggers: {t}")
            assert drift == [], f"guild schema drifted from guild_template: {drift}"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_DRIFT)


async def test_public_schema_has_no_tenant_tables(engine):
    """Squash leak-check: on a fresh database the ``public`` schema must contain
    NO copy of any guild-scoped (tenant) table. Post-v0.53.5-baseline, tenant
    content lives ONLY in ``guild_<id>`` (and ``guild_template``); a stray public
    copy would be a silent cross-tenant leak surface, so this fails closed if one
    reappears."""
    async with engine.connect() as conn:
        leaked = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:t)"
                    ),
                    {"t": list(GUILD_SCOPED_TABLES)},
                )
            )
        }
    assert leaked == set(), (
        f"public must hold NO tenant tables post-squash; found: {sorted(leaked)}"
    )


# --- back-fill sweep: heal half-states and drift for existing guilds -----------


async def test_backfill_provisions_a_guild_missing_its_schema(engine):
    """A guild row whose schema was never created (e.g. a crash mid-provision)
    gets its schema + tables on the next back-fill sweep."""
    done, missing = _GID_BACKFILL_DONE, _GID_BACKFILL_MISSING
    missing_schema = guild_schema_name(missing)
    try:
        async with engine.begin() as conn:
            await _insert_public_guild(conn, done, "backfill-done")
            await _insert_public_guild(conn, missing, "backfill-missing")
            await provision_guild_schema(conn, done)  # only `done` is provisioned

        async with engine.connect() as conn:
            before = await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": missing_schema},
            )
        assert before is None, "precondition: missing guild has no schema yet"

        summary = await backfill_guild_schemas()
        # Assert about OUR guilds only — the sweep covers every guild row in the
        # shared test DB, and an unrelated broken guild must not fail this test.
        assert done not in summary.failed_guild_ids
        assert missing not in summary.failed_guild_ids
        # `missing` had no schema, so it must have been provisioned; `done` was
        # provisioned with the current artifacts, so the stamp skips it.
        assert summary.provisioned >= 1
        assert summary.skipped >= 1

        async with engine.connect() as conn:
            tables = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": missing_schema},
            )
        assert tables == len(GUILD_SCOPED_TABLES), "schema should be fully back-filled"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, done)
            await drop_guild_schema(conn, missing)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = ANY(:ids)"),
                {"ids": [done, missing]},
            )


async def test_backfill_repairs_a_dropped_table(engine):
    """A table missing from an already-provisioned schema (drift: a table added to
    guild_schema.sql after the guild was made) is recreated by the back-fill.

    In that scenario the guild's schema-comment stamp predates the current
    artifacts, so the sweep re-provisions it (a schema stamped with the CURRENT
    artifacts is skipped — out-of-band corruption needs FORCE_GUILD_BACKFILL)."""
    gid = _GID_BACKFILL_DRIFT
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await _insert_public_guild(conn, gid, "backfill-drift")
            await provision_guild_schema(conn, gid)
            # Simulate a table that didn't exist when the schema was provisioned:
            # the table is absent AND the stamp names the older artifact version.
            await conn.exec_driver_sql(f'DROP TABLE "{schema}".subtasks CASCADE')
            await conn.exec_driver_sql(
                f"COMMENT ON SCHEMA \"{schema}\" IS 'provisioned:pre-subtasks'"
            )

        async with engine.connect() as conn:
            gone = await conn.scalar(text(f"SELECT to_regclass('{schema}.subtasks')"))
        assert gone is None, "precondition: subtasks dropped"

        summary = await backfill_guild_schemas()
        # Scoped to our guild — unrelated broken guilds in the shared test DB
        # must not fail this test.
        assert gid not in summary.failed_guild_ids
        assert summary.provisioned >= 1

        async with engine.connect() as conn:
            recreated = await conn.scalar(
                text(f"SELECT to_regclass('{schema}.subtasks')")
            )
        assert recreated is not None, "back-fill should recreate the dropped table"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_backfill_continues_past_a_failing_guild(engine, monkeypatch):
    """One guild that fails to provision is logged and skipped — the others in the
    same sweep are still processed."""
    ok_a, ok_b, bad = _GID_BACKFILL_OK_A, _GID_BACKFILL_OK_B, _GID_BACKFILL_FAIL
    try:
        async with engine.begin() as conn:
            for gid, name in (
                (ok_a, "backfill-ok-a"),
                (ok_b, "backfill-ok-b"),
                (bad, "backfill-bad"),
            ):
                await _insert_public_guild(conn, gid, name)

        # Force exactly one guild's provisioning to blow up; the real function
        # handles every other id. backfill_guild_schemas calls provision_guild as
        # a module-level name, so patching it here is enough.
        real_provision_guild = schema_provisioning.provision_guild

        async def _flaky_provision_guild(guild_id: int) -> str:
            if guild_id == bad:
                raise RuntimeError("forced provisioning failure")
            return await real_provision_guild(guild_id)

        monkeypatch.setattr(
            schema_provisioning, "provision_guild", _flaky_provision_guild
        )

        summary = await backfill_guild_schemas()

        # The bad guild is counted as failed but doesn't abort the sweep; both
        # healthy guilds (plus any other real guild rows) still get provisioned.
        assert bad in summary.failed_guild_ids
        assert ok_a not in summary.failed_guild_ids
        assert ok_b not in summary.failed_guild_ids
        assert summary.provisioned >= 2

        async with engine.connect() as conn:
            for gid in (ok_a, ok_b):
                tables = await conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = :s"
                    ),
                    {"s": guild_schema_name(gid)},
                )
                assert tables == len(GUILD_SCOPED_TABLES), (
                    f"healthy guild {gid} should be provisioned despite a sibling failure"
                )
            bad_exists = await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": guild_schema_name(bad)},
            )
        assert bad_exists is None, "the forced-failure guild's schema must not exist"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, ok_a)
            await drop_guild_schema(conn, ok_b)
            await drop_guild_schema(conn, bad)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = ANY(:ids)"),
                {"ids": [ok_a, ok_b, bad]},
            )


async def test_provisioning_stamp_tracks_grant_behavior_not_cosmetics(engine):
    """The back-fill skip stamp is derived from the RENDERED provisioning bundle
    (live schema DDL + registry RLS + rendered grant statements) — no manual
    version bump: a behavioral grants change moves it; a cosmetic rewrite of
    ``_grant_statements`` does not."""
    from unittest import mock

    from app.db import schema_provisioning as sp

    sp.reset_provisioning_bundle()
    baseline = (await sp.get_provisioning_bundle()).stamp

    _original = sp._grant_statements

    def _different_grants(
        schema: str, role: str, ro_role: str, support_role: str
    ) -> list[str]:
        return ["GRANT USAGE ON SCHEMA x TO y"]

    def _cosmetic_rewrite(
        schema: str, role: str, ro_role: str, support_role: str
    ) -> list[str]:
        # Different source text, byte-identical output.
        return list(_original(schema, role, ro_role, support_role))

    try:
        with mock.patch.object(sp, "_grant_statements", _different_grants):
            sp.reset_provisioning_bundle()
            changed = (await sp.get_provisioning_bundle()).stamp
        with mock.patch.object(sp, "_grant_statements", _cosmetic_rewrite):
            sp.reset_provisioning_bundle()
            cosmetic = (await sp.get_provisioning_bundle()).stamp
    finally:
        sp.reset_provisioning_bundle()

    assert changed != baseline, "a behavioral grants change must move the stamp"
    assert cosmetic == baseline, "a cosmetic rewrite must NOT move the stamp"
    assert (await sp.get_provisioning_bundle()).stamp == baseline


# --- ensure_system_engine_bypassrls (issue #835) -----------------------------
#
# A system-engine login without BYPASSRLS reads shared tables as empty and
# boot seeding dies on the guilds RLS policy. The boot check must pass a
# healthy posture untouched, repair the attribute when the provisioning login
# lawfully can, and stop boot with instructions when it can't.


async def _login_can_alter_bypassrls(engine) -> bool:
    async with engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    text(
                        "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                        "WHERE rolname = current_user"
                    )
                )
            ).scalar()
        )


async def _create_policy_bound_login(engine, role: str, password: str):
    """Create a LOGIN role WITHOUT BYPASSRLS and return an engine for it."""
    from sqlalchemy.ext.asyncio import create_async_engine

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        await conn.execute(
            text(f"CREATE ROLE \"{role}\" WITH LOGIN NOBYPASSRLS PASSWORD '{password}'")
        )
    return create_async_engine(
        engine.url.set(username=role, password=password), echo=False
    )


async def _drop_login(engine, role: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))


async def test_system_engine_check_passes_on_healthy_posture():
    # The harness routes the admin engine to the real app_admin (BYPASSRLS)
    # against the test DB — the check must be a silent no-op.
    await schema_provisioning.ensure_system_engine_bypassrls()


async def test_system_engine_check_heals_missing_bypassrls(engine, monkeypatch):
    import app.db.session as db_session

    if not await _login_can_alter_bypassrls(engine):
        pytest.skip("test login may not alter BYPASSRLS roles")

    role = f"{engine.url.database}_heal_role"
    bound_engine = await _create_policy_bound_login(engine, role, "heal-pw")
    monkeypatch.setattr(db_session, "admin_engine", bound_engine)
    # provisioning_engine is the (privileged) test engine via the harness.
    try:
        await schema_provisioning.ensure_system_engine_bypassrls()
        async with engine.connect() as conn:
            healed = (
                await conn.execute(
                    text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"),
                    {"r": role},
                )
            ).scalar()
        assert healed, "the check must re-assert BYPASSRLS on the system engine"
    finally:
        await bound_engine.dispose()
        await _drop_login(engine, role)


async def test_system_engine_check_fails_closed_when_it_cannot_heal(
    engine, monkeypatch
):
    import app.db.session as db_session

    if not await _login_can_alter_bypassrls(engine):
        pytest.skip("test login may not alter BYPASSRLS roles")

    role = f"{engine.url.database}_unheal_role"
    bound_engine = await _create_policy_bound_login(engine, role, "unheal-pw")
    # Point BOTH engines at the policy-bound login: the provisioning side may
    # not alter BYPASSRLS, so the check must stop boot with instructions.
    monkeypatch.setattr(db_session, "admin_engine", bound_engine)
    monkeypatch.setattr(db_session, "provisioning_engine", bound_engine)
    try:
        with pytest.raises(SystemExit) as excinfo:
            await schema_provisioning.ensure_system_engine_bypassrls()
        assert "ALTER ROLE" in str(excinfo.value)
        assert role in str(excinfo.value)
        # No repair was possible here, so the message must not claim one ran.
        assert "already ran" not in str(excinfo.value)
        async with engine.connect() as conn:
            still_bound = (
                await conn.execute(
                    text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"),
                    {"r": role},
                )
            ).scalar()
        assert not still_bound, "an unprivileged check must not change the role"
    finally:
        await bound_engine.dispose()
        await _drop_login(engine, role)


def test_bypassrls_exit_message_distinguishes_attempted_repair():
    """The heal-attempted variant must say a repair already ran (so the
    operator doesn't re-run an ALTER that silently changed nothing) and point
    at role-resolution debugging; the plain variant must not claim one ran."""
    plain = schema_provisioning._bypassrls_exit_message(
        "app_admin", heal_attempted=False
    )
    attempted = schema_provisioning._bypassrls_exit_message(
        "app_admin", heal_attempted=True
    )
    for message in (plain, attempted):
        assert 'ALTER ROLE "app_admin" WITH BYPASSRLS;' in message
    assert "already ran" not in plain
    assert "already ran" in attempted
    assert "current_user" in attempted  # the which-role-am-I diagnostic query


# --- ensure_shared_table_grants (issue #835 follow-up) -----------------------
#
# BYPASSRLS skips RLS *policies*, not table GRANTs. A restored/recreated role
# can bypass RLS yet be missing the per-table grants, failing one gate deeper
# with "permission denied for table ...". The boot heal must leave a healthy
# posture untouched and otherwise re-assert the audited grants (table + owned
# sequence). These tests point the registry at a throwaway public table so they
# never mutate the real app_admin/app_user grants (cluster-global roles shared
# across xdist workers); the per-worker test DB keeps the throwaway isolated.

_PROBE_TABLE = "grant_heal_probe"


async def _make_probe_table(engine, *, admin_grants, user_grants):
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS public.{_PROBE_TABLE}"))
        await conn.execute(
            text(f"CREATE TABLE public.{_PROBE_TABLE} (id serial PRIMARY KEY)")
        )
        # Fresh table created by the (superuser) test engine gives app_admin /
        # app_user nothing (default privileges were revoked for them); the
        # explicit REVOKE is belt-and-suspenders for the "restored role" state.
        await conn.execute(
            text(f"REVOKE ALL ON public.{_PROBE_TABLE} FROM app_admin, app_user")
        )
        if admin_grants:
            await conn.execute(
                text(f"GRANT {admin_grants} ON public.{_PROBE_TABLE} TO app_admin")
            )
        if user_grants:
            await conn.execute(
                text(f"GRANT {user_grants} ON public.{_PROBE_TABLE} TO app_user")
            )


async def _drop_probe_table(engine):
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS public.{_PROBE_TABLE}"))


def _point_registry_at_probe(monkeypatch, *, sys_verbs, user_verbs):
    from app.db import system_grants

    monkeypatch.setattr(
        system_grants,
        "SHARED_TABLE_SYSTEM_GRANTS",
        {_PROBE_TABLE: frozenset(sys_verbs) if sys_verbs else None},
    )
    monkeypatch.setattr(
        system_grants,
        "SHARED_TABLE_APP_USER_GRANTS",
        {_PROBE_TABLE: frozenset(user_verbs) if user_verbs else None},
    )


async def test_shared_grants_heal_restores_missing_table_and_sequence(
    engine, monkeypatch
):
    # A restored role: the table exists but app_admin/app_user hold no grants —
    # exactly issue #835's second report ("permission denied for table guilds").
    await _make_probe_table(engine, admin_grants=None, user_grants=None)
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    try:
        await schema_provisioning.ensure_shared_table_grants()
        async with engine.connect() as conn:
            admin_insert, user_select, admin_seq, user_seq = (
                await conn.execute(
                    text(
                        "SELECT has_table_privilege('app_admin', :t, 'INSERT'), "
                        "has_table_privilege('app_user', :t, 'SELECT'), "
                        "has_sequence_privilege('app_admin', :s, 'USAGE'), "
                        "has_sequence_privilege('app_user', :s, 'USAGE')"
                    ),
                    {
                        "t": f"public.{_PROBE_TABLE}",
                        "s": f"public.{_PROBE_TABLE}_id_seq",
                    },
                )
            ).one()
        assert admin_insert, "system engine INSERT grant must be restored"
        assert user_select, "bare login SELECT grant must be restored"
        assert admin_seq, "INSERT needs the row-id sequence — must be restored too"
        # app_user is SELECT-only on this table, so it needs NO sequence grant:
        # the heal grants a sequence only where the role actually holds INSERT
        # (least privilege), matching each role's real per-table need.
        assert not user_seq, "a SELECT-only role must not receive a sequence grant"
    finally:
        await _drop_probe_table(engine)


async def test_shared_grants_heal_is_noop_when_intact(engine, monkeypatch):
    # Already fully granted (table + sequence) — the heal must not re-assert.
    await _make_probe_table(engine, admin_grants="SELECT, INSERT", user_grants="SELECT")
    async with engine.begin() as conn:
        await conn.execute(
            text(f"GRANT ALL ON SEQUENCE public.{_PROBE_TABLE}_id_seq TO app_admin")
        )
        await conn.execute(
            text(
                f"GRANT SELECT, USAGE ON SEQUENCE public.{_PROBE_TABLE}_id_seq "
                "TO app_user"
            )
        )
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    reasserted = False

    async def _spy(*args, **kwargs):
        nonlocal reasserted
        reasserted = True
        return 0

    monkeypatch.setattr(schema_provisioning, "_reassert_shared_grants", _spy)
    try:
        await schema_provisioning.ensure_shared_table_grants()
        assert not reasserted, "a healthy grant posture must be a single-probe no-op"
    finally:
        await _drop_probe_table(engine)


async def test_shared_grants_probe_detects_partial_grant(engine, monkeypatch):
    import app.db.session as db_session

    # SELECT present but INSERT missing → the probe must report NOT intact, so a
    # partially-restored role still triggers the heal.
    await _make_probe_table(engine, admin_grants="SELECT", user_grants="SELECT")
    _point_registry_at_probe(
        monkeypatch, sys_verbs={"SELECT", "INSERT"}, user_verbs={"SELECT"}
    )
    try:
        expected = schema_provisioning._expected_shared_table_grants()
        async with db_session.provisioning_engine.connect() as conn:
            intact = await schema_provisioning._shared_grants_intact(conn, expected)
        assert intact is False
    finally:
        await _drop_probe_table(engine)
