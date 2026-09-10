from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path, PurePosixPath


MINIMUM_VERSION = (0, 1, 3)


class BackendVerificationError(RuntimeError):
    pass


def _version(value: object) -> tuple[int, int, int]:
    parts = str(value).split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise BackendVerificationError("the IMAP Plugin version is invalid")
    result = tuple(int(part) for part in parts)
    if result < MINIMUM_VERSION:
        raise BackendVerificationError("update IMAP Plugin to version 0.1.3 or newer")
    return result


def _contained_path(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if not relative or posix.is_absolute() or "\\" in relative or ".." in posix.parts:
        raise BackendVerificationError(f"invalid backend manifest path: {relative}")
    candidate = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise BackendVerificationError(f"backend manifest path uses a symbolic link: {relative}")
    return candidate


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def verify(program_root: Path) -> dict[str, object]:
    program_root = program_root.resolve()
    distribution = program_root / "distribution"
    backend = distribution / "plugins" / "imap-plugin"
    if not backend.is_dir() or backend.is_symlink():
        raise BackendVerificationError("the installed IMAP Plugin directory is missing or redirected")

    system = platform.system()
    if system == "Darwin":
        manifest_path = distribution / "backend-integrity.json"
        expected_product = "imap-plugin-installed-backend"
    elif system == "Windows":
        manifest_path = distribution / "package-manifest.json"
        expected_product = "imap-plugin-windows-handoff"
    else:
        raise BackendVerificationError("only Windows and macOS are supported")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BackendVerificationError("the installed IMAP Plugin integrity manifest is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema") != 1 or manifest.get("product") != expected_product:
        raise BackendVerificationError("the installed IMAP Plugin integrity identity is invalid")
    manifest_version = _version(manifest.get("version"))

    prefix = "plugins/imap-plugin/"
    expected: dict[str, tuple[str, int, str, str | None]] = {}
    for entry in manifest.get("files", []):
        relative = str(entry.get("path", ""))
        if not relative.startswith(prefix):
            continue
        if relative in expected:
            raise BackendVerificationError(f"duplicate backend manifest path: {relative}")
        target = _contained_path(distribution, relative)
        entry_type = str(entry.get("type", "file"))
        expected_target = str(entry.get("target")) if entry_type == "symlink" else None
        expected[relative] = (entry_type, int(entry["bytes"]), str(entry["sha256"]).upper(), expected_target)
        _, expected_bytes, expected_hash, expected_target = expected[relative]
        if entry_type == "symlink":
            if not target.is_symlink():
                raise BackendVerificationError(f"backend symbolic link is missing: {relative}")
            actual_target = os.readlink(target)
            encoded = actual_target.encode("utf-8", "surrogateescape")
            if actual_target != expected_target or len(encoded) != expected_bytes or hashlib.sha256(encoded).hexdigest().upper() != expected_hash:
                raise BackendVerificationError(f"backend integrity check failed for {relative}")
        elif entry_type == "file":
            if not target.is_file() or target.is_symlink():
                raise BackendVerificationError(f"backend file is missing or redirected: {relative}")
            if target.stat().st_size != expected_bytes or _digest(target) != expected_hash:
                raise BackendVerificationError(f"backend integrity check failed for {relative}")
        else:
            raise BackendVerificationError(f"unknown backend manifest entry type: {entry_type}")
    if not expected:
        raise BackendVerificationError("the integrity manifest contains no IMAP Plugin files")

    actual = {
        path.relative_to(distribution).as_posix()
        for path in backend.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != set(expected):
        raise BackendVerificationError("the installed IMAP Plugin file set differs from its integrity manifest")

    plugin_manifest = json.loads(
        (backend / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    if plugin_manifest.get("name") != "imap-plugin" or _version(plugin_manifest.get("version")) != manifest_version:
        raise BackendVerificationError("the installed IMAP Plugin name or version does not match its integrity manifest")
    return {
        "status": "pass",
        "product": expected_product,
        "version": ".".join(str(part) for part in manifest_version),
        "files_verified": len(expected),
        "backend_code_executed": False,
    }


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Library" / "Application Support" / "IMAP Plugin"
    try:
        result = verify(root)
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
