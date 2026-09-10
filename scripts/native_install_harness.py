"""Synthetic/native readiness harness for Nexin Mail installation gates.

The default mode performs no installation and never touches a mailbox or
credential.  On Windows it can be run in an isolated test profile with an
explicit package and install root.  Native acceptance remains a separate
environmental gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys


def check(package: Path | None, install_root: Path | None) -> dict[str, object]:
    value: dict[str, object] = {
        "product": "nexin-mail",
        "harness": "native_install",
        "platform": sys.platform,
        "architecture": platform.machine(),
        "mailbox": "not_touched",
        "credentials": "not_touched",
        "installation": "not_run",
        "native_acceptance": "not_checked",
    }
    if sys.platform != "win32":
        value["status"] = "unsupported_platform"
        return value
    if package is None or install_root is None:
        value["status"] = "ready_to_run"
        return value
    if not package.is_dir() or not install_root.is_absolute():
        value["status"] = "invalid_fixture"
        return value
    value["status"] = "ready_to_run"
    value["package"] = "explicit_fixture"
    value["install_root"] = "explicit_isolated_root"
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path)
    parser.add_argument("--install-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.package, args.install_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
