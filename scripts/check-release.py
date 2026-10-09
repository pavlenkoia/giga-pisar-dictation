#!/usr/bin/python3
"""Validate release tag and Debian package metadata without modifying inputs."""
from __future__ import annotations
import argparse
import re
import subprocess
from pathlib import Path

PACKAGE = "giga-pisar-dictation"
TAG_RE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def validate(tag: str, project_file: Path, deb: Path) -> None:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise ValueError("tag must be vX.Y.Z with decimal components and no leading zeroes")
    project = project_file.read_text(encoding="utf-8")
    versions = re.findall(r'^version\s*=\s*"([^"\n]+)"\s*$', project, re.MULTILINE)
    if len(versions) != 1 or versions[0] != ".".join(match.groups()):
        raise ValueError("tag version does not exactly match the single pyproject.toml version")
    if not deb.is_file() or deb.name != f"{PACKAGE}_{versions[0]}_amd64.deb":
        raise ValueError("expected exactly named amd64 Debian package is missing")
    def field(name: str) -> str:
        return subprocess.run(["dpkg-deb", "-f", str(deb), name], check=True,
                              capture_output=True, text=True).stdout.strip()
    if field("Version") != versions[0] or field("Architecture") != "amd64" or field("Package") != PACKAGE:
        raise ValueError("Debian package metadata does not match release version/package/architecture")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("deb", type=Path)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    validate(args.tag, args.project, args.deb)
    return 0

if __name__ == "__main__":
    main()
