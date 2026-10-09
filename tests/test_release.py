import importlib.util
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-release.py"
spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "pyproject.toml"
        self.project.write_text('[project]\nversion = "1.2.3"\n')
        self.deb = root / "giga-pisar-dictation_1.2.3_amd64.deb"
        self.deb.touch()

    def test_accepts_matching_release(self):
        with patch.object(release.subprocess, "run", side_effect=[self.result("1.2.3"), self.result("amd64"), self.result("giga-pisar-dictation")]):
            release.validate("v1.2.3", self.project, self.deb)

    def result(self, value):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=value)

    def test_rejects_invalid_tags_and_mismatch(self):
        for tag in ("1.2.3", "v01.2.3", "v1.2", "v1.2.3-rc1", "v1.2.3\necho bad"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.validate(tag, self.project, self.deb)
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            release.validate("v1.2.4", self.project, self.deb)

    def test_rejects_duplicate_version_and_wrong_filename(self):
        self.project.write_text('version = "1.2.3"\nversion = "1.2.3"\n')
        with self.assertRaises(ValueError):
            release.validate("v1.2.3", self.project, self.deb)
        self.project.write_text('version = "1.2.3"\n')
        wrong = self.deb.with_name("wrong.deb")
        wrong.touch()
        with self.assertRaises(ValueError):
            release.validate("v1.2.3", self.project, wrong)

    def test_rejects_metadata_mismatch(self):
        for values in (("1.2.4", "amd64", "giga-pisar-dictation"), ("1.2.3", "arm64", "giga-pisar-dictation"), ("1.2.3", "amd64", "other")):
            with self.subTest(values=values), patch.object(release.subprocess, "run", side_effect=[self.result(v) for v in values]), self.assertRaises(ValueError):
                release.validate("v1.2.3", self.project, self.deb)

class WorkflowPolicyTests(unittest.TestCase):
    WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release.yml"

    @classmethod
    def publish_run_block(cls):
        lines = cls.WORKFLOW.read_text(encoding="utf-8").splitlines()
        marker = "      - name: Validate and publish release"
        start = lines.index(marker)
        run_marker = "        run: |"
        run_start = lines.index(run_marker, start) + 1
        block = []
        for line in lines[run_start:]:
            if line and not line.startswith("          "):
                break
            block.append(line[10:] if line else "")
        return "\n".join(block) + "\n"

    def test_lintian_warning_policy_handles_known_details_and_fails_closed(self):
        script = Path(__file__).resolve().parents[1] / "scripts/check-lintian-release.py"
        allowed = ("W: giga-pisar-dictation: copyright-without-copyright-notice\n"
                   "W: giga-pisar-dictation: no-manual-page [usr/bin/giga-pisar-dictation]\n")
        subprocess.run(["/usr/bin/python3", str(script)], input=allowed, text=True, check=True)
        subprocess.run(["/usr/bin/python3", str(script)], input="", text=True, check=True)
        for output in (allowed + "W: giga-pisar-dictation: new-warning\n", "W: malformed warning\n"):
            with self.subTest(output=output), self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(["/usr/bin/python3", str(script)], input=output, text=True, check=True, capture_output=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "release-assets"
        self.assets.mkdir()
        self.mockbin = self.root / "bin"
        self.mockbin.mkdir()
        self.log = self.root / "gh.log"
        mock = self.mockbin / "gh"
        mock.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$GH_LOG"
case "$*" in
  "api repos/example/project/git/ref/tags/v1.2.3") exit "${MOCK_TAG_RC:-0}" ;;
  "api repos/example/project/releases/tags/v1.2.3")
    case "${MOCK_RELEASE:-missing}" in
      exists) exit 0 ;;
      missing) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
      error) echo 'gh: Internal Server Error (HTTP 500)' >&2; exit 1 ;;
    esac ;;
  "release create"*) exit 0 ;;
esac
exit 97
''')
        mock.chmod(0o755)
        self.deb = self.assets / "giga-pisar-dictation_1.2.3_amd64.deb"
        self.deb.write_bytes(b"fixture package bytes")
        self.write_sum()

    def write_sum(self):
        digest = hashlib.sha256(self.deb.read_bytes()).hexdigest()
        (self.assets / "SHA256SUMS").write_text(f"{digest}  {self.deb.name}\n")

    def run_workflow_publish(self, **extra):
        env = dict(os.environ, PATH=f"{self.mockbin}:{os.environ['PATH']}", GH_LOG=str(self.log),
                   RELEASE_TAG="v1.2.3", REPOSITORY="example/project", **extra)
        return subprocess.run(["bash", "-c", self.publish_run_block()], cwd=self.root,
                              env=env, text=True, capture_output=True)

    def test_actual_workflow_block_publishes_without_checkout_or_scripts(self):
        self.assertFalse((self.root / "scripts").exists())
        result = self.run_workflow_publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text()
        self.assertIn("release create v1.2.3", commands)
        self.assertIn("--verify-tag", commands)
        self.assertIn("api repos/example/project/releases/tags/v1.2.3", commands)

    def test_actual_workflow_block_rejects_invalid_assets_and_release_state(self):
        self.deb.write_bytes(b"tampered")
        self.assertNotEqual(self.run_workflow_publish().returncode, 0)
        self.deb.write_bytes(b"fixture package bytes")
        self.write_sum()
        (self.assets / "extra.txt").write_text("unexpected")
        self.assertNotEqual(self.run_workflow_publish().returncode, 0)
        (self.assets / "extra.txt").unlink()
        wrong = self.assets / "wrong_1.2.3_amd64.deb"
        self.deb.rename(wrong)
        digest = hashlib.sha256(wrong.read_bytes()).hexdigest()
        (self.assets / "SHA256SUMS").write_text(f"{digest}  {wrong.name}\n")
        self.assertNotEqual(self.run_workflow_publish().returncode, 0)
        wrong.rename(self.deb)
        self.write_sum()
        self.assertNotEqual(self.run_workflow_publish(MOCK_RELEASE="exists").returncode, 0)
        self.assertNotEqual(self.run_workflow_publish(MOCK_RELEASE="error").returncode, 0)
        self.assertNotIn("release create", self.log.read_text())

    def test_actual_workflow_block_rejects_missing_remote_tag(self):
        result = self.run_workflow_publish(MOCK_TAG_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("release create", self.log.read_text())

if __name__ == "__main__": unittest.main()
