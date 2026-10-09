import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build-deb.py"
_spec = importlib.util.spec_from_file_location("build_deb_script", BUILD_SCRIPT)
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)
build_deb, project_version = _builder.build_deb, _builder.project_version


class DebBuildTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_deb_payload_dependencies_modes_and_relocated_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            deb = build_deb(Path(temp) / "out")
            self.assertEqual(deb.name, f"giga-pisar-dictation_{project_version()}_amd64.deb")
            info = subprocess.run(["dpkg-deb", "--info", str(deb)], text=True, capture_output=True, check=True)
            self.assertIn("Architecture: amd64", info.stdout)
            for dependency in ("python3-gi", "python3-gi-cairo", "gir1.2-gtk-3.0", "gir1.2-soup-3.0",
                "gir1.2-gstreamer-1.0", "gir1.2-ayatanaappindicator3-0.1", "gstreamer1.0-plugins-base",
                "gstreamer1.0-plugins-good", "gstreamer1.0-pulseaudio", "libx11-6", "libxtst6"):
                self.assertIn(dependency, info.stdout)

            extracted = Path(temp) / "extracted"
            extracted.mkdir()
            subprocess.run(["dpkg-deb", "--extract", str(deb), str(extracted)], check=True)
            launcher = extracted / "usr/bin/giga-pisar-dictation"
            modules = extracted / "usr/lib/giga-pisar-dictation/giga_pisar_dictation"
            self.assertTrue(launcher.is_file())
            self.assertTrue((modules / "__main__.py").is_file())
            self.assertTrue((extracted / "usr/share/applications/org.gigapisar.Dictation.desktop").is_file())
            copyright_file = extracted / "usr/share/doc/giga-pisar-dictation/copyright"
            changelog_file = extracted / "usr/share/doc/giga-pisar-dictation/changelog.gz"
            self.assertIn("No license is granted", copyright_file.read_text(encoding="utf-8"))
            self.assertTrue(changelog_file.is_file())
            for state in ("idle", "recording", "processing", "error"):
                self.assertTrue((extracted / f"usr/share/icons/hicolor/scalable/status/giga-pisar-dictation-{state}.svg").is_file())
            contents = subprocess.run(["dpkg-deb", "--contents", str(deb)], text=True, capture_output=True, check=True).stdout
            self.assertIn("root/root", contents)
            self.assertIn("-rwxr-xr-x root/root", contents)
            for line in contents.splitlines():
                if line.startswith("drwx"):
                    self.assertEqual(line[:10], "drwxr-xr-x", line)
            self.assertNotIn("test_", contents)
            self.assertNotIn("config.json", contents)
            self.assertNotIn("api-key", contents)
            self.assertNotIn(".pyc", contents)
            self.assertNotIn("DEBIAN/postinst", contents)
            control_dir = Path(temp) / "control"
            control_dir.mkdir()
            subprocess.run(["dpkg-deb", "--control", str(deb), str(control_dir)], check=True)
            self.assertEqual(sorted(path.name for path in control_dir.iterdir()), ["control"])

            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            result = subprocess.run([str(launcher), "--help"], cwd=temp, env=env, text=True,
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Giga Pisar Dictation desktop client", result.stdout)

    def test_desktop_file_exec_icon_and_no_terminal(self):
        desktop = Path(__file__).resolve().parents[1] / "packaging/org.gigapisar.Dictation.desktop"
        text = desktop.read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/bin/giga-pisar-dictation", text)
        self.assertIn("Icon=giga-pisar-dictation", text)
        self.assertIn("Terminal=false", text)
        validator = shutil.which("desktop-file-validate")
        if validator:
            subprocess.run([validator, str(desktop)], check=True)


if __name__ == "__main__": unittest.main()
