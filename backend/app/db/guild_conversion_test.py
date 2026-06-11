"""Tests for the one-time public -> per-guild-schema data conversion."""

import pytest
from sqlalchemy import text

from app.db.guild_conversion import convert_public_to_guild_schemas
from app.db.schema_provisioning import drop_guild_schema, guild_schema_name

pytestmark = pytest.mark.database


async def _seed_public_guild(conn, label: str) -> tuple[int, int]:
    """Insert legacy pre-cutover data straight into public (bypassing the schema
    router): a guild + a default initiative + an initiative role (the role has no
    guild_id, so it exercises the chain partition predicate)."""
    gid = await conn.scalar(
        text("INSERT INTO public.guilds (name) VALUES (:n) RETURNING id"),
        {"n": f"Conv {label}"},
    )
    init_id = await conn.scalar(
        text(
            "INSERT INTO public.initiatives (name, created_at, updated_at, is_default, guild_id) "
            "VALUES (:n, now(), now(), true, :g) RETURNING id"
        ),
        {"n": f"{label} Initiative", "g": gid},
    )
    await conn.execute(
        text(
            "INSERT INTO public.initiative_roles (initiative_id, name, display_name) "
            "VALUES (:i, 'member', 'Member')"
        ),
        {"i": init_id},
    )
    return gid, init_id


async def test_convert_moves_public_data_into_guild_schemas(engine):
    """Existing guilds' public rows must land in their own schemas, isolated per
    guild, including guild_id-less tables (via the chain predicate). Idempotent."""
    seeded: dict[str, tuple[int, int]] = {}
    try:
        async with engine.begin() as conn:
            seeded["Alpha"] = await _seed_public_guild(conn, "Alpha")
            seeded["Beta"] = await _seed_public_guild(conn, "Beta")

        assert await convert_public_to_guild_schemas() == 2

        async with engine.connect() as conn:
            for gid, init_id in seeded.values():
                schema = guild_schema_name(gid)
                inits = (
                    (await conn.execute(text(f'SELECT id FROM "{schema}".initiatives')))
                    .scalars()
                    .all()
                )
                assert list(inits) == [init_id]  # only this guild's initiative
                roles = (
                    (
                        await conn.execute(
                            text(f'SELECT name FROM "{schema}".initiative_roles')
                        )
                    )
                    .scalars()
                    .all()
                )
                assert list(roles) == ["member"]  # chain predicate copied the role
                # sequence was advanced past the copied id, so new inserts don't collide
                next_id = await conn.scalar(
                    text(
                        f"SELECT nextval(pg_get_serial_sequence('\"{schema}\".initiatives','id'))"
                    )
                )
                assert next_id > init_id

        # Second run is a no-op (idempotent / resumable).
        assert await convert_public_to_guild_schemas() == 0
    finally:
        async with engine.begin() as conn:
            for gid, _ in seeded.values():
                await drop_guild_schema(conn, gid)
            for gid, _ in seeded.values():
                await conn.execute(
                    text(
                        "DELETE FROM public.initiative_roles WHERE initiative_id IN "
                        "(SELECT id FROM public.initiatives WHERE guild_id = :g)"
                    ),
                    {"g": gid},
                )
                await conn.execute(
                    text("DELETE FROM public.initiatives WHERE guild_id = :g"),
                    {"g": gid},
                )
                await conn.execute(
                    text("DELETE FROM public.guilds WHERE id = :g"), {"g": gid}
                )


async def test_convert_handles_guild_without_initiatives(engine):
    """A guild with data but no initiatives must still convert (the old
    sentinel-count skip would silently leave it behind)."""
    gid = None
    try:
        async with engine.begin() as conn:
            gid = await conn.scalar(
                text(
                    "INSERT INTO public.guilds (name) VALUES ('No Inits') RETURNING id"
                )
            )
            # guild-scoped data that doesn't hang off an initiative
            await conn.execute(
                text(
                    "INSERT INTO public.tags (guild_id, name, created_at, updated_at) "
                    "VALUES (:g, 'orphan', now(), now())"
                ),
                {"g": gid},
            )

        assert await convert_public_to_guild_schemas() == 1
        async with engine.connect() as conn:
            schema = guild_schema_name(gid)
            tags = (
                (await conn.execute(text(f'SELECT name FROM "{schema}".tags')))
                .scalars()
                .all()
            )
            assert list(tags) == ["orphan"]
        assert await convert_public_to_guild_schemas() == 0  # marker set -> skipped
    finally:
        if gid is not None:
            async with engine.begin() as conn:
                await drop_guild_schema(conn, gid)
                await conn.execute(
                    text("DELETE FROM public.tags WHERE guild_id = :g"), {"g": gid}
                )
                await conn.execute(
                    text("DELETE FROM public.guilds WHERE id = :g"), {"g": gid}
                )
