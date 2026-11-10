"""Are the installed libraries the ones requirements.txt asks for?

After an update of Alpline a pinned version may have changed (for example a library with a security fix). The
launcher's checks page shows what differs and offers one button to install it, instead of a command line.

    python -m fpv3d.deps            prints the differences as JSON (the launcher runs this with the project's Python)
"""
from __future__ import annotations

import json
import re
import sys
from importlib import metadata
from pathlib import Path

LINE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s#;]+)\s*(#.*)?$")


def wanted(req_file: Path) -> list:
    """[(name, version, optional)] from a requirements file with exact pins (a comment starting "optional" marks one)."""
    out: list = []
    try:
        lines = Path(req_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        m = LINE.match(line)
        if m:
            out.append((m.group(1), m.group(2), bool(m.group(3)) and "optional" in m.group(3).lower()))
    return out


def differences(req_file: Path) -> list:
    """What is missing or at another version: [{"name", "want", "have" (None = not installed), "optional"}]."""
    out = []
    for name, want, optional in wanted(req_file):
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            have = None
        if have != want and not (have is None and optional):       # an optional library that was never installed is fine
            out.append(dict(name=name, want=want, have=have, optional=optional))
    return out


if __name__ == "__main__":
    req = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "requirements.txt"
    print(json.dumps(differences(req)))
