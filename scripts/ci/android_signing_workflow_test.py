"""Regression tests for Android signing-secret transport in the release workflow."""

from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/docker-publish.yml"


class AndroidSigningWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        text = WORKFLOW.read_text()
        cls.job = text.split("  build-android:", 1)[1].split(
            "\n  build-docker-public:", 1
        )[0]

    def test_passwords_reach_gradle_as_environment_properties(self) -> None:
        for name in ("store.password", "key.alias", "key.password"):
            self.assertRegex(
                self.job,
                rf"ORG_GRADLE_PROJECT_android\.injected\.signing\.{re.escape(name)}:",
            )
        self.assertNotRegex(self.job, r"-P\S*signing\S*(?:password|alias)=")
        self.assertNotIn("gradle.properties", self.job)

    def test_only_the_keystore_is_staged_and_it_is_cleaned_up(self) -> None:
        self.assertIn('signing_dir="$RUNNER_TEMP/signing"', self.job)
        self.assertIn('> "$signing_dir/release.jks"', self.job)
        self.assertIn(
            '-Pandroid.injected.signing.store.file="$RUNNER_TEMP/signing/release.jks"',
            self.job,
        )
        self.assertRegex(
            self.job,
            r"- name: Remove staged signing material\n\s+if: always\(\)",
        )


if __name__ == "__main__":
    unittest.main()
