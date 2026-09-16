"""The database and ``app.db.authorization`` say the same thing.

These functions used to live only inside the migrations that created them, so
"what is the rule right now" was answered by reading three migrations and a
baseline in the right order. Now the module is the source and boot applies it —
which is only true for as long as something checks. This is that something.

The comparison is on ``pg_get_functiondef`` output, which round-trips: feeding
Postgres its own rendering back produces the identical text, so an exact match
is a fair test rather than a brittle one.
"""

import pytest
from sqlalchemy import text

from app.db.authorization import (
    AUTHORIZATION_FUNCTIONS,
    apply_authorization_functions,
    authorization_functions_digest,
)

pytestmark = pytest.mark.database

#: ``pg_get_functiondef`` needs the argument types to identify an overload.
#: These are the only signatures; a second overload of any of them would be a
#: design change, and ``test_no_unexpected_overloads`` is what would say so.
SIGNATURES = {
    "guild_auth_satisfied": "()",
    "initiative_access": "(int,int,bool)",
    "initiative_full_access": "(int,bool)",
    "initiative_role_permits": "(int,int,text,bool)",
    "resource_access": "(text,int,int,int,bool)",
}


async def _live_def(session, name: str) -> str:
    return (
        await session.exec(
            text("SELECT pg_get_functiondef(CAST(:sig AS regprocedure))").bindparams(
                sig=f"public.{name}{SIGNATURES[name]}"
            )
        )
    ).one()[0]


@pytest.mark.parametrize(
    "name,expected",
    AUTHORIZATION_FUNCTIONS,
    ids=[n for n, _ in AUTHORIZATION_FUNCTIONS],
)
async def test_the_database_matches_this_module(session, name, expected):
    """What is deployed is what this file says.

    A failure means one of two things and the diff says which: a migration
    changed a function without changing the module, or the module was edited
    and the change has not reached this database.
    """
    assert (await _live_def(session, name)).strip() == expected.strip()


async def test_applying_is_idempotent(session):
    """Boot runs this on every start, so it has to be safe to run twice."""
    conn = await session.connection()
    before = {n: await _live_def(session, n) for n, _ in AUTHORIZATION_FUNCTIONS}
    await apply_authorization_functions(conn)
    after = {n: await _live_def(session, n) for n, _ in AUTHORIZATION_FUNCTIONS}
    assert before == after
    await session.rollback()


@pytest.mark.parametrize(
    "name,_sql", AUTHORIZATION_FUNCTIONS, ids=[n for n, _ in AUTHORIZATION_FUNCTIONS]
)
async def test_none_runs_as_its_owner(session, name, _sql):
    """Each runs as its caller: these are declared ``SECURITY INVOKER``."""
    secdef = (
        await session.exec(
            text(
                "SELECT p.prosecdef FROM pg_proc p"
                " JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'public' AND p.proname = :name"
            ).bindparams(name=name)
        )
    ).one()[0]
    assert secdef is False


async def test_no_unexpected_overloads(session):
    """One definition per name — the signatures above are the whole set."""
    rows = (
        await session.exec(
            text(
                "SELECT p.proname, count(*) FROM pg_proc p"
                " JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'public' AND p.proname = ANY(:names)"
                " GROUP BY p.proname"
            ).bindparams(names=list(SIGNATURES))
        )
    ).all()
    assert {r[0]: r[1] for r in rows} == {n: 1 for n in SIGNATURES}


def test_the_digest_changes_with_the_definitions(monkeypatch):
    """The stamp is of the text, so an edit moves it."""
    import app.db.authorization as module

    first = authorization_functions_digest()
    assert first == authorization_functions_digest(), "should be deterministic"

    name, sql = module.AUTHORIZATION_FUNCTIONS[0]
    monkeypatch.setattr(
        module,
        "AUTHORIZATION_FUNCTIONS",
        ((name, sql + "\n-- edited"),) + module.AUTHORIZATION_FUNCTIONS[1:],
    )
    assert module.authorization_functions_digest() != first
