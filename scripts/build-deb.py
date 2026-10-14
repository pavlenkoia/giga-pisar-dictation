#!/usr/bin/python3
"""Build an unprivileged amd64 .deb using dpkg-deb only."""
from __future__ import annotations
import argparse
import datetime
import gzip
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "giga-pisar-dictation"
def project_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([0-9]+(?:\.[0-9]+)*)"\s*$', text, re.MULTILINE)
    if not match: raise ValueError("Не удалось определить версию проекта в pyproject.toml")
    return match.group(1)


def build_deb(output_dir):
    if platform.machine() != "x86_64": raise RuntimeError("Сборка пакета поддерживается только для x86_64/amd64")
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb: raise RuntimeError("Требуется dpkg-deb")
    version = project_version()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{PACKAGE}_{version}_amd64.deb"

    with tempfile.TemporaryDirectory(prefix="giga-pisar-deb-") as temp:
        staging = Path(temp) / "root"
        module_dir = staging / "usr/lib" / PACKAGE / "giga_pisar_dictation"
        launcher_dir = staging / "usr/bin"
        desktop_dir = staging / "usr/share/applications"
        app_icons = staging / "usr/share/icons/hicolor/scalable/apps"
        status_icons = staging / "usr/share/icons/hicolor/scalable/status"
        doc_dir = staging / "usr/share/doc" / PACKAGE
        debian = staging / "DEBIAN"
        for directory in (module_dir, launcher_dir, desktop_dir, app_icons, status_icons, doc_dir, debian):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o755)

        for source in (ROOT / "src/giga_pisar_dictation").glob("*.py"):
            shutil.copyfile(source, module_dir / source.name)
            (module_dir / source.name).chmod(0o644)
        shutil.copyfile(ROOT / "packaging/launcher", launcher_dir / PACKAGE)
        (launcher_dir / PACKAGE).chmod(0o755)
        shutil.copyfile(ROOT / "packaging/org.gigapisar.Dictation.desktop", desktop_dir / "org.gigapisar.Dictation.desktop")
        (desktop_dir / "org.gigapisar.Dictation.desktop").chmod(0o644)

        for source in sorted((ROOT / "packaging/icons").glob("*.svg")):
            destination = app_icons if source.stem == PACKAGE else status_icons
            shutil.copyfile(source, destination / source.name)
            (destination / source.name).chmod(0o644)

        template = (ROOT / "packaging/deb/control.in").read_text(encoding="utf-8")
        (debian / "control").write_text(template.replace("@VERSION@", version), encoding="utf-8")
        (debian / "control").chmod(0o644)
        copyright_file = ROOT / "packaging/deb/copyright"
        shutil.copyfile(copyright_file, doc_dir / "copyright")
        changelog_date = datetime.datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
        changelog = (f"{PACKAGE} ({version}) unstable; urgency=low\n\n"
                     "  * Убрать предупреждение HTTP из проверки доступности сервера.\n\n"
                     f" -- Local package <pavlenko@it-tian.ru>  {changelog_date}\n").encode("utf-8")
        (doc_dir / "changelog.gz").write_bytes(gzip.compress(changelog, mtime=0))
        (doc_dir / "copyright").chmod(0o644)
        (doc_dir / "changelog.gz").chmod(0o644)
        for directory in staging.rglob("*"):
            if directory.is_dir(): directory.chmod(0o755)
        staging.chmod(0o755)

        subprocess.run([dpkg_deb, "--root-owner-group", "--build", str(staging), str(output)], check=True)
    return output


def main(argv=None):
    class RussianArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            return super().format_usage().replace("usage:", "использование:")

        def format_help(self):
            return (super().format_help().replace("usage:", "использование:")
                    .replace("options:", "параметры:")
                    .replace("show this help message and exit", "показать эту справку и выйти"))

        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"{self.prog}: ошибка: неверные аргументы\n")

    parser = RussianArgumentParser(description="Сборка пакета «Гига Писарь» без установки")
    parser.add_argument("--output-dir", default=str(ROOT / "dist"), help="каталог для пакета (по умолчанию: dist/)")
    arguments = parser.parse_args(argv)
    print(build_deb(arguments.output_dir))
    return 0


if __name__ == "__main__": raise SystemExit(main())
