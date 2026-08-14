#!/usr/bin/env python
"""Write the app manifest JSON Schema to a file.

The schema is generated from the validator's own vocabulary
(:mod:`app.services.marketplace.manifest_schema`), and the generated file is
committed so an app author can read it without running this build — the same
arrangement the frontend's generated API types use.

Run it after changing anything the manifest validator accepts:

    python scripts/export_manifest_schema.py

CI regenerates and diffs, so a vocabulary change with no regenerated schema
fails there rather than shipping a schema that describes the old rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Importable when run as a script from anywhere in the backend tree.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.marketplace.manifest_schema import (  # noqa: E402
    build_manifest_schema,
)

#: Beside the other things this build publishes for people writing against it.
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent / "schemas" / "app-manifest.json"
)


def render() -> str:
    """The schema as it is written to disk: stable key order, trailing newline."""
    return json.dumps(build_manifest_schema(), indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to write (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the file on disk differs, writing nothing",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not args.output.exists():
            print(f"{args.output} does not exist; run this script", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(
                f"{args.output} is out of date; run scripts/export_manifest_schema.py",
                file=sys.stderr,
            )
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
