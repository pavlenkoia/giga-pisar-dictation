#!/usr/bin/python3
"""Allow only the known package warnings; reject malformed and unexpected warnings."""
import re
import sys

ALLOWED = {"copyright-without-copyright-notice", "no-manual-page"}
WARNING = re.compile(r"^W: [^:\s]+: ([a-z0-9][a-z0-9-]*)(?: \[[^\]\n]+\])?$")


def check(lines):
    for raw in lines:
        line = raw.rstrip("\n")
        if re.match(r"^W:", line):
            match = WARNING.fullmatch(line)
            if not match:
                raise ValueError(f"Malformed lintian warning: {line}")
            tag = match.group(1)
            if tag not in ALLOWED:
                raise ValueError(f"Unexpected lintian warning: {tag}")


if __name__ == "__main__":
    try:
        check(sys.stdin)
    except ValueError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
