"""``app_guild_base_ro`` is the read half of ``app_guild_base``.

The read-only floor exists so a role that only reads can hold only reads. What
it must *not* become is a wider grant than the writable floor it mirrors: the
shared tables withheld from the request path (see
``SHARED_TABLE_APP_USER_GRANTS``) are withheld by explicit revokes, and a role
added later does not inherit those decisions unless something holds it to them.

That something is this test. Both roles receive schema-wide default privileges,
so a table added tomorrow reaches both; a table revoked from one and not the
other shows up here as a difference.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.database

WRITABLE_FLOOR = "app_guild_base"
READ_FLOOR = "app_guild_base_ro"

_TABLES = """
SELECT c.oid::regclass::text AS name,
       has_table_privilege(:writable, c.oid, 'SELECT') AS writable_reads,
       has_table_privilege(:read_only, c.oid, 'SELECT') AS read_only_reads
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
"""


async def _rows(engine):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(_TABLES), {"writable": WRITABLE_FLOOR, "read_only": READ_FLOOR}
            )
        ).all()


async def test_the_read_floor_reads_nothing_extra(engine):
    """The interesting direction: a table the writable floor cannot read must
    not be readable here either."""
    wider = [
        r.name
        for r in await _rows(engine)
        if r.read_only_reads and not r.writable_reads
    ]
    assert wider == [], f"{READ_FLOOR} reads tables {WRITABLE_FLOOR} cannot: {wider}"


async def test_the_read_floor_reads_everything_the_writable_one_does(engine):
    """The other direction, which is a working problem rather than a security
    one: a guild read that the full role can serve has to work here too."""
    narrower = [
        r.name
        for r in await _rows(engine)
        if r.writable_reads and not r.read_only_reads
    ]
    assert narrower == [], f"{READ_FLOOR} cannot read: {narrower}"


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE"])
async def test_the_read_floor_writes_nothing(engine, verb):
    async with engine.connect() as conn:
        writable = (
            await conn.execute(
                text(
                    "SELECT c.oid::regclass::text AS name FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                    "AND has_table_privilege(:r, c.oid, :v)"
                ),
                {"r": READ_FLOOR, "v": verb},
            )
        ).all()
    assert [row.name for row in writable] == []
