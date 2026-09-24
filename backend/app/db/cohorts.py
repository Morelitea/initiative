"""Communities divided into cohorts, and a request pool for each.

A database connection keeps the catalog of every table it has opened for as
long as it lives, and each community is a schema of its own, so a connection
that has served every community holds every community's catalog. Dividing the
communities into ``DB_COHORTS`` cohorts, and serving each cohort from a pool of
its own, means a connection only ever opens its own cohort's schemas.

:func:`cohort_of` is the one place that says which cohort a community is in.
Everything else asks it.

With one cohort (the default) there is nothing to divide: every request draws
from the one request pool, ``app.db.session.AsyncSessionLocal``, as it always
has, and nothing in this module is built.

What a request routes into is noted on the connection it runs on
(:func:`note_route`), so a connection that serves a community outside its
cohort is counted, and in the test suite refused.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Mapping

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import metrics
from app.core.config import settings

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

#: The tag on a connection from a pool that serves no community's schema.
PLATFORM = "platform"

#: Where a pooled connection keeps its cohort, and the communities it has
#: served. On the pool's record, so both last as long as the connection does.
_COHORT_KEY = "initiative_cohort"
_SERVED_KEY = "initiative_cohort_served"

#: Marks a session the request path handed out, which is what lets a
#: cross-community read give each community a session from its own cohort.
_REQUEST_SESSION_KEY = "cohort_request_session"

#: Marks a session whose transactions are opened read-only.
READ_ONLY_INFO_KEY = "cohort_read_only"

#: The test suite sets this, so a route outside the connection's cohort raises
#: rather than being counted.
STRICT = False

#: Each cohort's request sessionmaker, built on first use.
_request_makers: list[async_sessionmaker[AsyncSession]] | None = None


class CrossCohortRoute(RuntimeError):
    """A connection was routed into a community outside its cohort."""


def cohort_count() -> int:
    return settings.DB_COHORTS


def cohort_of(guild_id: int) -> int:
    """The cohort ``guild_id`` belongs to."""
    return int(guild_id) % cohort_count()


def cohort_url(url: str, cohort: int) -> str:
    """``url`` with the database ``DB_COHORT_DATABASE`` names for ``cohort``."""
    template = settings.DB_COHORT_DATABASE
    if not template:
        return url
    return (
        make_url(url)
        .set(database=template.format(cohort=cohort))
        .render_as_string(hide_password=False)
    )


def _served(record_info: dict[str, Any]) -> set[int]:
    return record_info.setdefault(_SERVED_KEY, set())


def tag_engine(engine: AsyncEngine, tag: int | str) -> None:
    """Mark every connection ``engine`` opens as belonging to ``tag``, and
    report how many communities each one served when it closes."""
    label = str(tag)
    communities = metrics.db_connection_communities.labels(cohort=label)

    def connected(_dbapi_connection: Any, record: Any) -> None:
        record.info[_COHORT_KEY] = tag

    def closed(_dbapi_connection: Any, record: Any) -> None:
        served = record.info.get(_SERVED_KEY)
        if served:
            communities.observe(len(served))

    event.listen(engine.sync_engine, "connect", connected)
    event.listen(engine.sync_engine, "close", closed)


def _build_request_makers() -> list[async_sessionmaker[AsyncSession]]:
    from app.db.session import instrument_engine

    makers = []
    for cohort in range(cohort_count()):
        engine = create_async_engine(
            cohort_url(settings.DATABASE_URL_APP, cohort),
            echo=False,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        )
        instrument_engine(engine, f"request/{cohort}")
        tag_engine(engine, cohort)
        makers.append(_sessionmaker(engine))
    return makers


def _sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )


def use_request_engines(engines: list[AsyncEngine]) -> None:
    """Serve the cohorts from ``engines``, one per cohort in order. For the
    test suite, which points every pool at its own database."""
    global _request_makers
    for cohort, engine in enumerate(engines):
        tag_engine(engine, cohort)
    _request_makers = [_sessionmaker(engine) for engine in engines]


def request_sessionmaker(guild_id: int | None) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker for request-path work in ``guild_id``'s community, or
    for work that names no community when it is ``None``."""
    global _request_makers
    # Looked up on the module rather than bound at import, so the test
    # harness's binding of the request pool applies here too.
    from app.db import session as db_session

    if guild_id is None or cohort_count() == 1:
        return db_session.AsyncSessionLocal
    if _request_makers is None:
        _request_makers = _build_request_makers()
    return _request_makers[cohort_of(guild_id)]


def addressed_guild_id(path_params: Mapping[str, Any]) -> int | None:
    """The community a request's path addresses, if it addresses one."""
    raw = path_params.get("guild_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def mark_request_session(session: AsyncSession) -> None:
    session.info[_REQUEST_SESSION_KEY] = True


def fans_out(session: AsyncSession) -> bool:
    """Whether a read across communities made on ``session`` gives each
    community a session from its own cohort, rather than routing ``session``
    into each in turn."""
    return cohort_count() > 1 and bool(session.info.get(_REQUEST_SESSION_KEY))


@asynccontextmanager
async def community_session(guild_id: int) -> AsyncIterator[AsyncSession]:
    """A read-only request-path session from ``guild_id``'s cohort, for one
    community's part of a read across several. It is closed without a commit,
    so what it reads is all it is for."""
    async with request_sessionmaker(guild_id)() as session:
        session.info[READ_ONLY_INFO_KEY] = True
        yield session


def routed_guild_id(params: Mapping[str, Any]) -> int | None:
    """The community a stored context routes into, whichever way it names it."""
    for key in (
        "guild_id",
        "pam_guild_id",
        "settings_guild_id",
        "system_guild_id",
        "billing_guild_id",
    ):
        value = params.get(key)
        if value is not None:
            return int(value)
    return None


def note_route(connection: "Connection | None", guild_id: int | None) -> None:
    """Record that ``connection`` is serving ``guild_id``'s community, and
    count it when that community is outside the connection's cohort."""
    if connection is None or guild_id is None:
        return
    info = connection.info
    tag = info.get(_COHORT_KEY)
    if tag is None:
        return
    _served(info).add(guild_id)
    if tag != PLATFORM and tag == cohort_of(guild_id):
        return
    metrics.db_cross_cohort_routes.labels(cohort=str(tag)).inc()
    if STRICT:
        raise CrossCohortRoute(
            f"a connection from the {tag!s} pool was routed into community "
            f"{guild_id}, which is in cohort {cohort_of(guild_id)}"
        )
