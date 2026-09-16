"""Structural checks on how the release workflow signs the Android APK.

The workflow and ``frontend/android/app/build.gradle`` have to agree on a set
of Gradle property names, and the release job has to verify what it signed
before it stages anything for upload. Both are checked here against the parsed
workflow rather than against its text.
"""

from __future__ import annotations

import pathlib
import re
import string
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/docker-publish.yml"
BUILD_GRADLE = ROOT / "frontend/android/app/build.gradle"

GRADLE_ENV_PREFIX = "ORG_GRADLE_PROJECT_"
SIGNING_SECRET = re.compile(r"secrets\.ANDROID_\w+")

# Gradle's wrapper is a /bin/sh script, and the names it forwards to the build
# JVM are the ones a POSIX shell accepts as variable names.
POSIX_LEADING = frozenset(string.ascii_letters + "_")
POSIX_TRAILING = POSIX_LEADING | frozenset(string.digits)


def is_posix_name(name: str) -> bool:
    return (
        bool(name)
        and name[0] in POSIX_LEADING
        and all(c in POSIX_TRAILING for c in name)
    )


def _load_job(name: str) -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow["jobs"][name]


class AndroidSigningWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job = _load_job("build-android")
        cls.steps = cls.job["steps"]
        cls.names = [step.get("name", "") for step in cls.steps]

    def step(self, name: str) -> dict:
        for step in self.steps:
            if step.get("name") == name:
                return step
        raise AssertionError(f"no step named {name!r}; found {self.names}")

    def gradle_properties(self) -> dict[str, str]:
        found = {}
        for step in self.steps:
            for key, value in (step.get("env") or {}).items():
                if key.startswith(GRADLE_ENV_PREFIX):
                    found[key[len(GRADLE_ENV_PREFIX) :]] = str(value)
        return found

    def test_gradle_property_names_are_posix_names(self) -> None:
        properties = self.gradle_properties()
        self.assertTrue(properties, "no Gradle project properties are set")
        for name in properties:
            self.assertTrue(
                is_posix_name(name), f"{GRADLE_ENV_PREFIX}{name} is not a POSIX name"
            )

    def test_gradle_property_names_match_the_build_file(self) -> None:
        declared = set(re.findall(r"initiativeSigning\w+", BUILD_GRADLE.read_text()))
        self.assertEqual(declared, set(self.gradle_properties()))

    def test_signing_secrets_are_not_interpolated_into_commands(self) -> None:
        for step in self.steps:
            run = step.get("run")
            if not run:
                continue
            self.assertNotRegex(
                run, SIGNING_SECRET, f"step {step.get('name')!r} names a signing secret"
            )
            self.assertNotRegex(
                run, r"-P\w[\w.]*[Pp]assword=", "signing password on a command line"
            )

    def test_the_keystore_is_staged_outside_the_checkout_and_removed(self) -> None:
        staged = self.step("Stage the signing keystore outside the workspace")
        self.assertIn('"$RUNNER_TEMP/signing/release.jks"', staged["run"])
        self.assertIn("umask 077", staged["run"])

        store_file = self.gradle_properties()["initiativeSigningStoreFile"]
        self.assertEqual(store_file, "${{ runner.temp }}/signing/release.jks")

        cleanup = self.step("Remove the staged signing keystore")
        self.assertEqual(cleanup["if"], "always()")
        self.assertIn("rm -rf", cleanup["run"])

    def test_the_job_runs_in_the_release_environment(self) -> None:
        self.assertEqual(self.job.get("environment"), "android-release")

    def test_a_release_tag_cannot_build_without_signing(self) -> None:
        guard = self.step("Require signing on release tags")
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", guard["if"])
        self.assertIn("env.HAS_KEYSTORE != 'true'", guard["if"])
        self.assertIn("exit 1", guard["run"])

    def test_the_signature_is_verified_before_anything_is_staged(self) -> None:
        verify = self.step("Verify the APK signature")
        self.assertEqual(verify["if"], "${{ env.HAS_KEYSTORE == 'true' }}")
        self.assertIn("apksigner", verify["run"])
        self.assertIn("keytool", verify["run"])
        self.assertLess(
            self.names.index("Verify the APK signature"),
            self.names.index("Stage the APK for upload"),
        )

    def test_the_uploaded_artifact_follows_the_configuration(self) -> None:
        run = self.step("Stage the APK for upload")["run"]
        self.assertIn("if [ \"$HAS_KEYSTORE\" = 'true' ]", run)
        self.assertNotIn("-f frontend/android", run)


if __name__ == "__main__":
    unittest.main()
