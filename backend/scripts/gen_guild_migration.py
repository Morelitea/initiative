"""Autogenerate a GUILD-SCOPED Alembic migration (issue #781).

One command replaces the hand-written guild-migration workflow:

    python scripts/gen_guild_migration.py "add tasks.archived flag"

which runs, in order:

1. ``alembic upgrade head``            — guild_template must be current, or the
                                          diff would re-emit already-applied ops
2. ``alembic -x guild revision --autogenerate``
                                        — alembic's -x argument channel puts
                                          env.py in guild mode: it reflects
                                          guild_template (not public) and
                                          inverts the table filter to
                                          guild-content tables only;
                                          script.py.mako wraps the ops in the
                                          per-guild-schema loop
3. ``alembic upgrade head``            — applies the new migration to
                                          guild_template + every guild_<id>
There is nothing to regenerate afterward: NEW guilds are provisioned by
reflecting the LIVE guild_template, so they match by construction.

Review the generated file after (it's printed); to back out, ``alembic
downgrade -1`` and delete the file.

Pass ``--no-apply`` to stop after step 2 (generate only; ``alembic upgrade
head`` is then YOUR next step).

Everything here is plain Alembic: the -x argument channel
(``context.get_x_argument``), env.py, and script.py.mako — its two official
extension points plus its documented CLI parameter mechanism.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run(argv: list[str]) -> None:
    print(f"$ {' '.join(argv)}")
    subprocess.run(argv, cwd=BACKEND_DIR, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autogenerate a guild-scoped migration from SQLModel changes."
    )
    parser.add_argument("message", help="migration message (imperative, short)")
    parser.add_argument(
        "--no-apply",
        action="store_true",
        help="generate only; skip the final `alembic upgrade head`",
    )
    args = parser.parse_args()

    before = set(BACKEND_DIR.glob("alembic/versions/*.py"))
    _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    _run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            "guild",
            "revision",
            "--autogenerate",
            "-m",
            args.message,
        ]
    )
    new_files = set(BACKEND_DIR.glob("alembic/versions/*.py")) - before
    for f in sorted(new_files):
        print(f"generated: {f.relative_to(BACKEND_DIR)}")

    if args.no_apply:
        print("\n--no-apply: review the migration, then run `alembic upgrade head`.")
        return

    _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    print("\nDone. Review and commit the generated migration above.")


if __name__ == "__main__":
    main()
