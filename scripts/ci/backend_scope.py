#!/usr/bin/env python3
"""Choose the backend test scope for a CI event.

The workflow supplies the changed paths so this policy can be tested without
depending on a runner, a checkout, or shell interpolation.
"""

from __future__ import annotations

import argparse
import json


def select(event: str, paths: list[str]) -> dict[str, str]:
    if event == "push" or ".github/workflows/ci.yml" in paths:
        return {"skip": "false", "alembic_changed": "true", "scope": "app/ alembic/"}

    backend = [path.removeprefix("backend/") for path in paths if path.startswith("backend/")]
    if not backend:
        return {"skip": "true", "alembic_changed": "false", "scope": ""}

    alembic = any(path.startswith("alembic/") for path in backend)
    non_alembic = [path for path in backend if not path.startswith("alembic/")]
    if not non_alembic:
        return {"skip": "false", "alembic_changed": "true", "scope": "alembic/"}

    shared = any(
        path.startswith(prefix)
        for path in non_alembic
        for prefix in ("app/testing/", "app/models/", "app/schemas/", "app/core/", "app/db/", "app/services/")
    ) or "conftest.py" in non_alembic
    if shared:
        scope = "app/"
    else:
        directories = {
            ("app/services/marketplace" if path.startswith("app/marketplace_catalog/") else path.rsplit("/", 1)[0])
            for path in non_alembic
            if not path.startswith("app/locales/")
        }
        scope = " ".join(sorted(directories)) or "app/"
    if alembic:
        scope += " alembic/"
    return {"skip": "false", "alembic_changed": str(alembic).lower(), "scope": scope}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--paths-json", required=True)
    args = parser.parse_args()
    for key, value in select(args.event, json.loads(args.paths_json)).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
