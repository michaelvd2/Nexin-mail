from __future__ import annotations

import os
import sys
from pathlib import Path


CHUNK = 1024 * 1024


def owner_path_needles() -> tuple[bytes, ...]:
    values = {str(Path.home())}
    for name in ("USERPROFILE", "HOME"):
        if os.environ.get(name):
            values.add(str(Path(os.environ[name])))
    variants = {
        item
        for value in values
        for item in (value, value.replace("\\", "/"), value.replace("/", "\\"))
        if len(item) >= 4
    }
    return tuple(
        encoded
        for value in variants
        for encoded in (value.casefold().encode("utf-8"), value.casefold().encode("utf-16-le"))
    )


def contains_owner_path(path: Path, needles: tuple[bytes, ...]) -> bool:
    overlap = max(len(value) for value in needles) - 1
    previous = b""
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            combined = previous + block
            lowered = combined.lower()
            if any(value in lowered for value in needles):
                return True
            previous = combined[-overlap:] if overlap > 0 else b""
    return False


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: package_owner_path_scan.py ROOT [ROOT ...]")
    needles = owner_path_needles()
    findings: list[str] = []
    scanned = 0
    for raw_root in sys.argv[1:]:
        root = Path(raw_root).resolve()
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            scanned += 1
            if contains_owner_path(path, needles):
                findings.append(str(path.relative_to(root)) if root.is_dir() else path.name)
    if findings:
        print(f"owner path scan failed ({len(findings)} finding(s), {scanned} file(s) scanned)")
        for finding in sorted(findings):
            print(f"- build-machine path: {finding}")
        return 3
    print(f"owner path scan passed ({scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
