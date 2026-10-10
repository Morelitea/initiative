"""``python -m app.demo load <manifest> --accounts <secret file> [--rebuild]``."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.db import cohorts
from app.demo.loader import DemoModeRequired, load
from app.services.storage_config import refresh_storage_config


async def _main(args: argparse.Namespace) -> None:
    # The storage the deployment is configured with, not the environment's
    # first-boot default.
    async with cohorts.system_session(None) as session:
        await refresh_storage_config(session)
    await load(args.manifest, args.accounts, rebuild=args.rebuild)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    loading = commands.add_parser("load", help="seed the demo from its manifest")
    loading.add_argument("manifest", type=Path)
    loading.add_argument("--accounts", type=Path, required=True)
    loading.add_argument(
        "--rebuild",
        action="store_true",
        help="also delete and remake every seeded community not marked keep",
    )
    try:
        asyncio.run(_main(parser.parse_args()))
    except DemoModeRequired as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
