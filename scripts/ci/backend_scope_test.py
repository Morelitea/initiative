import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("backend_scope.py")


def select(event: str, paths: list[str]) -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--event", event, "--paths-json", json.dumps(paths)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class BackendScopeTests(unittest.TestCase):
    def test_workflow_change_runs_full_backend(self):
        self.assertEqual(
            select("pull_request", [".github/workflows/ci.yml"]),
            {"skip": "false", "alembic_changed": "true", "scope": "app/ alembic/"},
        )

    def test_push_runs_full_backend_even_for_docs(self):
        self.assertEqual(
            select("push", ["docs/ci.md"]),
            {"skip": "false", "alembic_changed": "true", "scope": "app/ alembic/"},
        )

    def test_docs_only_pull_request_skips_backend(self):
        self.assertEqual(
            select("pull_request", ["docs/ci.md"]),
            {"skip": "true", "alembic_changed": "false", "scope": ""},
        )

    def test_service_change_runs_full_backend(self):
        result = select("pull_request", ["backend/app/services/auth.py"])
        self.assertEqual(result["skip"], "false")
        self.assertEqual(result["alembic_changed"], "false")
        self.assertEqual(result["scope"], "app/")


if __name__ == "__main__":
    unittest.main()
