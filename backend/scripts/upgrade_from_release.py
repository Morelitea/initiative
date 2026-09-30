"""Upgrade a database that a release wrote, and check what the upgrade did.

Every other migration check starts from an empty database, where a backfill
has nothing to move and a ``NOT NULL`` column has no rows to refuse it. This
one starts where a deployment does:

1. Boot the release (``python -m app.db.init_db``, what the image runs at
   start) and fill it with ``upgrade_seed.py`` under that release's code.
2. With ``--walk``, boot every later release in turn, as a deployment that
   takes each one does.
3. Boot the current tree, then seed it again with the current code: the
   upgraded database has to take new writes as well as keep old ones.
4. Build a fresh install of the current tree on a second server, seeded the
   same way.

and fails when:

* any boot or seed fails;
* a table that held rows before a boot is empty after it;
* the upgraded database differs in structure from the fresh install —
  ``public``, ``guild_template``, and every community schema against a fresh
  one. That is the shape a revision edited after release leaves behind: fresh
  installs get the new body, and upgraded ones never do;
* a second start of the fresh install changes its structure. A start repairs
  what is out of date, so one that changes a current database undoes what the
  migrations set;
* with ``--same-as``, the fresh install differs from the one another run built
  in the other setup. One URL and explicit logins are two ways of giving the
  app the same database, and they must end up with the same one, roles and
  privileges included.

"Structure" is every schema's tables, columns, constraints, indexes, triggers,
policies, functions, grants and default privileges, and the app's roles: their
attributes and memberships.

Each database has its own Postgres server, because roles are cluster-wide and a
community's roles would otherwise be shared between the two.

Usage, from ``backend/`` with ``SECRET_KEY`` set, as each boot reads it::

    python scripts/upgrade_from_release.py --from v0.73.1 \\
        --server postgresql://initiative:initiative@localhost:5432 \\
        --fresh-server postgresql://initiative:initiative@localhost:5433

``--from`` defaults to the newest release tag. ``--walk`` starts at
:data:`WALK_FROM` and boots every release after it, less :data:`WITHDRAWN`.

``--one-url`` runs every boot, of each release and of the current tree, with a
single ``DATABASE_URL`` naming the database owner, as ``docker-compose.example.yml``
does: the app derives its three logins from it. Without it, each boot is given
the three logins and the owner URL explicitly. The walk then starts at
:data:`ONE_URL_FROM`, the first release that could run that way.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import asyncpg

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SEED = BACKEND / "scripts" / "upgrade_seed.py"
DATABASE = "initiative"

# The login roles every release since the bootstrap module creates for itself,
# with the passwords CI gives them.
LOGINS = {
    "DATABASE_URL": "app_provisioner",
    "DATABASE_URL_APP": "app_user",
    "DATABASE_URL_ADMIN": "app_admin",
}


#: Where ``--walk`` starts: the oldest release whose test factories hold
#: everything ``upgrade_seed.py`` makes.
WALK_FROM = "v0.70.0"

#: The first release that derives its logins from one owner ``DATABASE_URL``.
ONE_URL_FROM = "v0.72.0"

#: Releases that could not upgrade a database, and the release that replaced
#: them. A walk steps over each one, as the deployments it stopped did: what
#: it shipped is fixed, so booting it would only fail again.
WITHDRAWN = {
    # Its bootstrap withheld the TEMPORARY privilege a 0414 backfill needs
    # (issue #2152); v0.73.1 grants it.
    "v0.73.0": "v0.73.1",
}


#: Every database setting a boot may be given; each boot gets only its own.
_DATABASE_SETTINGS = (*LOGINS, "DATABASE_URL_BOOTSTRAP")


def _environment(server: str, *, one_url: bool) -> dict[str, str]:
    """The app's database settings for ``server``: the owner's URL alone, or
    the three logins and the owner explicitly."""
    base = {k: v for k, v in os.environ.items() if k not in _DATABASE_SETTINGS}
    owner = server.replace("postgresql://", "postgresql+asyncpg://") + f"/{DATABASE}"
    if one_url:
        return {**base, "DATABASE_URL": owner}
    host = server.split("@", 1)[1]
    env = {
        name: f"postgresql+asyncpg://{role}:{role}@{host}/{DATABASE}"
        for name, role in LOGINS.items()
    }
    env["DATABASE_URL_BOOTSTRAP"] = owner
    return {**base, **env}


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}  (in {cwd})", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _release_tags() -> list[str]:
    output = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=v:refname"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [tag for tag in output.split() if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]


async def _recreate_database(server: str) -> None:
    conn = await asyncpg.connect(f"{server}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{DATABASE}"')
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


async def _row_counts(server: str) -> dict[str, int]:
    """Rows in every table of ``public`` and of every community schema.

    Read as the owner, which row security does not bind here: the counts are of
    what is stored, not of what any request may see.
    """
    conn = await asyncpg.connect(f"{server}/{DATABASE}")
    try:
        tables = await conn.fetch(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
            "AND (n.nspname = 'public' OR n.nspname ~ '^guild_[0-9]+$')"
        )
        return {
            f"{schema}.{table}": await conn.fetchval(
                f'SELECT count(*) FROM "{schema}"."{table}"'
            )
            for schema, table in tables
        }
    finally:
        await conn.close()


def _lost(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Communities that are gone, and tables that held rows and still exist
    but hold none now.

    A table a revision drops or renames is not in ``after`` and is not listed:
    that is a decision the revision states. Emptying one it keeps is not, and
    no revision drops a community.
    """
    schemas_after = {table.split(".", 1)[0] for table in after}
    gone = {
        table.split(".", 1)[0]
        for table in before
        if _COMMUNITY.match(table) and table.split(".", 1)[0] not in schemas_after
    }
    return [f"{schema} (the whole community)" for schema in sorted(gone)] + sorted(
        f"{table} ({count} rows before)"
        for table, count in before.items()
        if count and after.get(table) == 0
    )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

# Everything is read with an empty search_path, so every name the catalog
# prints comes qualified and the same object reads the same in both databases.
# A privilege list the catalog leaves NULL holds the defaults, and is read as
# them, so a grant that spells a default out does not read as a difference.
_SNAPSHOT = {
    "relation": (
        "SELECT c.relname, c.relkind::text, c.relrowsecurity, "
        "c.relforcerowsecurity, coalesce(c.relacl, acldefault("
        "CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END::\"char\", c.relowner"
        "))::text[] "
        "FROM pg_class c WHERE c.relnamespace = $1::regnamespace "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
    ),
    "column": (
        "SELECT c.relname || '.' || a.attname, format_type(a.atttypid, a.atttypmod), "
        "a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attidentity::text, "
        "a.attgenerated::text, a.attacl::text[] "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE c.relnamespace = $1::regnamespace "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
        "AND a.attnum > 0 AND NOT a.attisdropped"
    ),
    "constraint": (
        "SELECT c.relname || '.' || k.conname, pg_get_constraintdef(k.oid) "
        "FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
        "WHERE c.relnamespace = $1::regnamespace"
    ),
    "index": ("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = $1::text"),
    "trigger": (
        "SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid), "
        "t.tgenabled::text "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE c.relnamespace = $1::regnamespace AND NOT t.tgisinternal"
    ),
    "policy": (
        "SELECT tablename || '.' || policyname, permissive, roles::text[], "
        "cmd, qual, with_check FROM pg_policies WHERE schemaname = $1::text"
    ),
    "function": (
        "SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid), "
        "pg_get_userbyid(p.proowner), "
        "coalesce(p.proacl, acldefault('f'::\"char\", p.proowner))::text[] "
        "FROM pg_proc p WHERE p.pronamespace = $1::regnamespace "
        "AND p.prokind IN ('f', 'p')"
    ),
    "enum": (
        "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
        "WHERE t.typnamespace = $1::regnamespace GROUP BY t.typname"
    ),
    "view": (
        "SELECT c.relname, pg_get_viewdef(c.oid) FROM pg_class c "
        "WHERE c.relnamespace = $1::regnamespace AND c.relkind IN ('v', 'm')"
    ),
    "default privilege": (
        "SELECT pg_get_userbyid(d.defaclrole) || ' ' || d.defaclobjtype::text, "
        "d.defaclacl::text[] FROM pg_default_acl d "
        "WHERE d.defaclnamespace = $1::regnamespace "
        "OR (d.defaclnamespace = 0 AND $1::text = 'public')"
    ),
    "schema": (
        "SELECT nspname, coalesce(nspacl, acldefault('n'::\"char\", nspowner))"
        "::text[] FROM pg_namespace WHERE nspname = $1::text"
    ),
}

_COMMUNITY = re.compile(r"\bguild_\d+")

#: A string literal or an array literal inside parentheses of its own.
_WRAPPED_ATOM = re.compile(r"\(\s*('(?:[^']|'')*'|ARRAY\[[^\]]*\])\s*\)")


def _normalize(kind: str, value: object) -> object:
    """One community's schema and roles read the same as another's.

    A privilege list is a set, and each community's roles collapse to one name
    in it. A function body is compared by digest, to keep a report readable. A
    constraint the provisioning render round-tripped comes back with its string
    array casts re-spelled and its literals and arrays parenthesized; those are
    not compared, and the parentheses that group an expression are.
    """
    if isinstance(value, list) and kind != "enum":
        return sorted({_COMMUNITY.sub("guild_#", item) for item in value})
    if not isinstance(value, str):
        return value
    value = _COMMUNITY.sub("guild_#", value)
    if kind == "function" and value.startswith("CREATE"):
        return hashlib.md5(value.encode()).hexdigest()
    if kind == "constraint":
        value = re.sub(r"::(?:character varying|text)(?:\[\])?", "", value)
        while True:
            unwrapped = _WRAPPED_ATOM.sub(r"\1", value)
            if unwrapped == value:
                return value
            value = unwrapped
    return value


async def _snapshot(conn: asyncpg.Connection, schema: str) -> dict[str, str]:
    shape: dict[str, str] = {}
    for kind, query in _SNAPSHOT.items():
        for name, *rest in await conn.fetch(query, schema):
            key = f"{kind} {_COMMUNITY.sub('guild_#', name)}"
            shape[key] = repr([_normalize(kind, value) for value in rest])
    return shape


def _app_role(alias: str) -> str:
    """Every role but Postgres's own and the owner login the check connects
    as: what the app made, whatever its names."""
    return f"{alias}.rolname !~ '^pg_' AND {alias}.rolname <> current_user"


_ROLES = {
    "role": (
        "SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, "
        "rolcanlogin, rolreplication, rolbypassrls, rolconnlimit "
        f"FROM pg_roles r WHERE {_app_role('r')}"
    ),
    "membership": (
        # One row per grantor: the same membership can be held twice.
        "SELECT m.rolname || ' in ' || g.rolname || ' from ' || "
        "pg_get_userbyid(a.grantor), a.admin_option, "
        "a.inherit_option, a.set_option "
        "FROM pg_auth_members a JOIN pg_roles m ON m.oid = a.member "
        "JOIN pg_roles g ON g.oid = a.roleid "
        f"WHERE ({_app_role('m')}) OR ({_app_role('g')})"
    ),
}


async def _roles(conn: asyncpg.Connection) -> dict[str, str]:
    """The roles and memberships, with each community's id read as ``guild_#``.

    A database holds a role set per community, so one name stands for several:
    every distinct record under it is kept, and a community whose roles differ
    from another's shows as an extra one.
    """
    records: dict[str, set[str]] = {}
    for kind, query in _ROLES.items():
        for name, *rest in await conn.fetch(query):
            key = f"{kind} {_COMMUNITY.sub('guild_#', name)}"
            records.setdefault(key, set()).add(repr(rest))
    return {key: repr(sorted(values)) for key, values in records.items()}


async def _schemas(server: str) -> dict[str, dict[str, str]]:
    conn = await asyncpg.connect(
        f"{server}/{DATABASE}", server_settings={"search_path": ""}
    )
    try:
        names = [
            row[0]
            for row in await conn.fetch(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('public', 'guild_template') "
                "OR nspname ~ '^guild_[0-9]+$' ORDER BY nspname"
            )
        ]
        shapes = {name: await _snapshot(conn, name) for name in names}
        shapes["roles"] = await _roles(conn)
        return shapes
    finally:
        await conn.close()


def _differences(
    label: str,
    got: dict[str, str],
    want: dict[str, str],
    names: tuple[str, str] = ("upgraded", "fresh"),
) -> list[str]:
    lines = []
    for key in sorted(set(got) | set(want)):
        if key not in got:
            lines.append(f"{label}: {names[0]} lacks {key} ({names[1]}: {want[key]})")
        elif key not in want:
            lines.append(f"{label}: {names[1]} lacks {key} ({names[0]}: {got[key]})")
        elif got[key] != want[key]:
            lines.append(
                f"{label}: {key}\n"
                f"    {names[0]}: {got[key]}\n"
                f"    {names[1]}: {want[key]}"
            )
    return lines


def _divergence(
    upgraded: dict[str, dict[str, str]], fresh: dict[str, dict[str, str]]
) -> list[str]:
    """Where the upgraded database differs from the fresh install: ``public``
    and the template against theirs, and every community schema against a
    community the fresh install created."""
    communities = sorted(name for name in fresh if _COMMUNITY.fullmatch(name))
    assert communities, "the fresh install has no community schema to compare with"
    reference = fresh[communities[0]]
    lines: list[str] = []
    for name in ("public", "guild_template", "roles"):
        lines += _differences(name, upgraded[name], fresh[name])
    for name, shape in upgraded.items():
        if _COMMUNITY.fullmatch(name):
            lines += _differences(name, shape, reference)
    return lines


def _other_setup(
    mine: dict[str, dict[str, str]], theirs: dict[str, dict[str, str]], shape: str
) -> list[str]:
    """Where this fresh install differs from the other setup's: ``public``, the
    template and the roles, and one community schema against one of theirs."""
    names = (shape, "other setup")
    lines: list[str] = []
    for name in ("public", "guild_template", "roles"):
        lines += _differences(name, mine[name], theirs[name], names)
    ours = sorted(name for name in mine if _COMMUNITY.fullmatch(name))
    others = sorted(name for name in theirs if _COMMUNITY.fullmatch(name))
    lines += _differences("community", mine[ours[0]], theirs[others[0]], names)
    return lines


def _restart_changes(
    first: dict[str, dict[str, str]], second: dict[str, dict[str, str]]
) -> list[str]:
    """What a second start changed. A start repairs what is out of date and
    nothing else, so on a database the first one left current there is
    nothing for it to do."""
    lines: list[str] = []
    for name in sorted(set(first) | set(second)):
        lines += _differences(
            name,
            second.get(name, {}),
            first.get(name, {}),
            ("after a restart", "first start"),
        )
    return lines


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _boot(backend: Path, python: str, env: dict[str, str]) -> None:
    """Start the app as its image does. The bootstrap is run first because
    releases before 0.72 did not run it from ``init_db``; their CI ran it as a
    step of its own, and it changes nothing where it has already run."""
    _run([python, "-m", "app.db.bootstrap"], cwd=backend, env=env)
    _run([python, "-m", "app.db.init_db"], cwd=backend, env=env)


def _seed(backend: Path, python: str, env: dict[str, str]) -> None:
    _run([python, str(SEED)], cwd=backend, env=env)


def _fail(title: str, lines: list[str]) -> None:
    print(f"::error::{title}")
    for line in lines:
        print(f"  {line}")
    sys.exit(1)


def _boot_keeping_rows(
    label: str, server: str, backend: Path, python: str, env: dict[str, str]
) -> None:
    before = asyncio.run(_row_counts(server))
    _boot(backend, python, env)
    lost = _lost(before, asyncio.run(_row_counts(server)))
    if lost:
        _fail(f"Booting {label} lost rows it held", lost)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--from",
        dest="start",
        help=f"release tag to upgrade from (newest; {WALK_FROM} with --walk)",
    )
    parser.add_argument(
        "--walk",
        action="store_true",
        help="boot every release after --from in turn before the current tree",
    )
    parser.add_argument(
        "--one-url",
        action="store_true",
        help="give every boot one owner DATABASE_URL, as the example compose file does",
    )
    parser.add_argument(
        "--same-as",
        metavar="SERVER",
        help="owner URL of the other setup's fresh-install server, to match exactly",
    )
    parser.add_argument("--server", required=True, help="owner URL, no database")
    parser.add_argument(
        "--fresh-server", required=True, help="a second server for the fresh install"
    )
    args = parser.parse_args()

    tags = _release_tags()
    walk_from = ONE_URL_FROM if args.one_url else WALK_FROM
    start = args.start or (walk_from if args.walk else tags[-1])
    if args.one_url and tags.index(start) < tags.index(ONE_URL_FROM):
        parser.error(f"{start} predates one-URL setups; the first is {ONE_URL_FROM}")
    releases = (
        [tag for tag in tags[tags.index(start) :] if tag not in WITHDRAWN]
        if args.walk
        else [start]
    )
    upgraded_env = _environment(args.server, one_url=args.one_url)
    fresh_env = _environment(args.fresh_server, one_url=args.one_url)
    shape = "one DATABASE_URL" if args.one_url else "explicit logins"

    asyncio.run(_recreate_database(args.server))
    asyncio.run(_recreate_database(args.fresh_server))

    with tempfile.TemporaryDirectory(prefix="upgrade-from-release-") as scratch:
        checkout = Path(scratch) / "release"
        # One environment re-synced to each release's lockfile, so a hop only
        # installs what changed.
        release_env = {**upgraded_env, "UV_PROJECT_ENVIRONMENT": f"{scratch}/venv"}
        python = f"{scratch}/venv/bin/python"
        _run(["git", "worktree", "add", "--detach", str(checkout), start], cwd=REPO)
        try:
            for index, tag in enumerate(releases):
                _run(["git", "checkout", "--detach", "--quiet", tag], cwd=checkout)
                _run(
                    ["uv", "sync", "--frozen"],
                    cwd=checkout / "backend",
                    env=release_env,
                )
                _boot_keeping_rows(
                    tag, args.server, checkout / "backend", python, release_env
                )
                if index == 0:
                    _seed(checkout / "backend", python, release_env)
        finally:
            _run(["git", "worktree", "remove", "--force", str(checkout)], cwd=REPO)

    _boot_keeping_rows(
        "the current tree", args.server, BACKEND, sys.executable, upgraded_env
    )
    _seed(BACKEND, sys.executable, upgraded_env)

    _boot(BACKEND, sys.executable, fresh_env)
    _seed(BACKEND, sys.executable, fresh_env)
    fresh = asyncio.run(_schemas(args.fresh_server))
    _boot_keeping_rows(
        "a fresh install again", args.fresh_server, BACKEND, sys.executable, fresh_env
    )

    problems = [
        *_restart_changes(fresh, asyncio.run(_schemas(args.fresh_server))),
        *_divergence(asyncio.run(_schemas(args.server)), fresh),
    ]
    if problems:
        _fail(
            f"Upgrading from {start} ({shape}) does not reach the schema a fresh "
            "install keeps across restarts",
            problems,
        )
    if args.same_as:
        other = _other_setup(fresh, asyncio.run(_schemas(args.same_as)), shape)
        if other:
            _fail(f"A fresh install with {shape} differs from the other setup's", other)
    print(
        f"Upgraded {' → '.join(releases)} → current tree ({shape}); "
        "matches a fresh install, and a restart changes nothing"
        + ("; the fresh install matches the other setup's." if args.same_as else ".")
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        _fail(f"{' '.join(map(str, error.cmd))} exited {error.returncode}", [])
