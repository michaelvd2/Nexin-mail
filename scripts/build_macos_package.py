[output summary: 367 lines / 16886 chars; artifact in diagnostics]
signals:
-         except Exception:
-         print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
representative beginning:
"""Build a real, relocatable Nexin Mail package for macOS arm64.

The runtime is downloaded from the pinned python-build-standalone release and
is materialized without symlinks before the package builder sees it.  The
package therefore remains independent of Homebrew, a developer venv, and the
build machine's absolute paths.  This script intentionally builds only the
host's arm64 target; an Intel artifact needs its own upstream asset and proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request


PRODUCT_VERSION = "0.2.0"
PYTHON_VERSION = "3.12.14"
PBA_RELEASE = "20260901"
PBA_TARGET = "aarch64-apple-darwin"
PBA_ARCHIVE = f"cpython-{PYTHON_VERSION}+{PBA_RELEASE}-{PBA_TARGET}-install_only.tar.gz"
PBA_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PBA_RELEASE}/{PBA_ARCHIVE.replace('+', '%2B')}"
)
PBA_CHECKSUM_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PBA_RELEASE}/SHA256SUMS"
)
PBA_SHA256 = "3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76"
PBA_RELEASE_URL = f"https://github.com/astral-sh/python-build-standalone/releases/tag/{PBA_RELEASE}"
PBA_LICENSE_URL = "https://github.com/astral-sh/python-build-standalone/blob/main/LICENSE"
PYTHON_LICENSE_URL = "https://github.com/astral-sh/python-build-standalone/blob/main/LICENSE.cpython.txt"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _relative_member(name: str) -> tuple[str, ...]:
    """Validate an upstream archive name before it reaches the filesystem."""

    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("upstream archive contains an invalid path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("upstream archive contains traversal")
    return path.parts


def _link_target(relative: tuple[str, ...], target: str) -> tuple[str, ...]:
    if not isinstance(target, str) or not target or "\x00" in target or "\\" in target:
        raise ValueError("upstream archive contains an invalid link target")
    candidate = PurePosixPath(*relative[:-1], target)
    if candidate.is_absolute():
        raise ValueError("upstream archive contains an absolute link")
    parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("upstream archive link escapes its root")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
representative end:
        "--source", str(source_root), "--runtime", str(runtime_root), "--output", str(package_root),
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root / "src")
    result = subprocess.run(command, cwd=str(source_root), env=environment, check=True,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    build_result = json.loads(result.stdout.strip().splitlines()[-1])
    built_archive = Path(str(build_result["archive"])).resolve(strict=True)
    package_manifest = json.loads((package_root / "package-manifest.json").read_text(encoding="utf-8"))
    provenance = {
        "schema": 1,
        "product": "nexin-mail",
        "package_version": PRODUCT_VERSION,
        "target": "macos-arm64",
        "python_version": PYTHON_VERSION,
        "python_architecture": "arm64",
        "upstream": {
            "project": "astral-sh/python-build-standalone",
            "release": PBA_RELEASE,
            "release_url": PBA_RELEASE_URL,
            "artifact": PBA_ARCHIVE,
            "artifact_url": PBA_URL,
            "artifact_sha256": PBA_SHA256,
            "checksum_url": PBA_CHECKSUM_URL,
            "license_url": PBA_LICENSE_URL,
            "python_license_url": PYTHON_LICENSE_URL,
        },
        "runtime_archive_bytes": archive.stat().st_size,
        "runtime_executable_sha256": sha256(runtime),
        "dependencies_lock_sha256": sha256(source_root / "requirements-runtime.lock"),
        "dependencies": dependency_versions,
        "package_archive": {
            "path": str(built_archive),
            "bytes": built_archive.stat().st_size,
            "sha256": sha256(built_archive),
        },
        "manifest_sha256": sha256(package_root / "package-manifest.json"),
        "manifest_files": len(package_manifest["files"]),
        "license_in_package": "payload/runtime/python/lib/python3.12/LICENSE.txt",
        "build_host": {"system": "Darwin", "machine": platform_machine()},
    }
    (artifact_root / "runtime-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def platform_machine() -> str:
    import platform
    return platform.machine()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.source, args.artifact_root)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "pass", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
