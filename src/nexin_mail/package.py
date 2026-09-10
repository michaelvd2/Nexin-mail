"""Verification and registration metadata for an immutable Nexin Mail payload.

Release files are immutable and addressed by the hash of their manifest.
Codex registration is derived outside that payload because it contains
absolute, machine-specific paths.  Keeping that boundary explicit makes safe
update and rollback possible without rewriting a release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from .diagnostics import VERSION

PRODUCT = "nexin-mail"
MANIFEST_SCHEMA = 1
MCP_SERVER_NAME = "mail"
MCP_SERVER_MODULE = "nexin_mail.server"
_REPARSE_POINT = 0x400
_MAX_MANIFEST_FILES = 100_000
_MAX_RELATIVE_LENGTH = 240
_MACOS_METADATA_NAME = ".DS_Store"


class PackageError(ValueError):
    """Raised when an untrusted package cannot be accepted."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate package JSON key")
        value[key] = item
    return value


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _reparse(path: Path) -> bool:
    """Return whether *path* is a Windows reparse point, when available."""

    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def contained(root: Path, relative: str) -> Path:
    """Resolve a manifest path while rejecting traversal and link tricks."""

    if not isinstance(relative, str) or not relative or len(relative) > _MAX_RELATIVE_LENGTH:
        raise PackageError("Invalid package path")
    if "\\" in relative or ":" in relative or "\x00" in relative:
        raise PackageError("Invalid package path")
    parts = relative.split("/")
    if any(p in {"", ".", ".."} or p.endswith((".", " ")) for p in parts):
        raise PackageError("Invalid package path")
    if PurePosixPath(relative).is_absolute():
        raise PackageError("Invalid package path")
    reserved = {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        if stem in reserved or any(ord(c) < 32 or c in '<>"|?*' for c in part):
            raise PackageError("Invalid Windows package path")
    target = root
    for part in parts:
        target = target / part
        if target.is_symlink() or _reparse(target):
            raise PackageError("Package links are forbidden")
    try:
        if not target.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
            raise PackageError("Package path escaped root")
    except OSError as exc:
        raise PackageError("Package path could not be resolved") from exc
    if _reparse(root):
        raise PackageError("Package root reparse point is forbidden")
    return target


def _load_json(path: Path) -> Any:
    try:
        if path.is_symlink() or _reparse(path) or not stat.S_ISREG(path.stat().st_mode):
            raise PackageError("Package file is not a regular file")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except PackageError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise PackageError("Invalid or incomplete package") from exc


def _manifest_entry(item: Any, root: Path, seen: set[str]) -> None:
    if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
        raise PackageError("Invalid package entry")
    if type(item["bytes"]) is not int or item["bytes"] < 0:
        raise PackageError("Invalid package entry")
    relative = item["path"]
    if not isinstance(relative, str):
        raise PackageError("Invalid package path")
    target = contained(root, relative)
    key = relative.casefold()
    if key in seen or key == "package-manifest.json" or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
        raise PackageError("Duplicate or invalid package entry")
    seen.add(key)
    try:
        stat_result = target.stat()
    except OSError as exc:
        raise PackageError("Package file is missing") from exc
    if not stat.S_ISREG(stat_result.st_mode) or stat_result.st_size != item["bytes"] or digest(target) != item["sha256"]:
        raise PackageError("Package integrity check failed")


def _iter_package_files(root: Path, manifest_path: Path) -> set[str]:
    actual: set[str] = set()
    try:
        paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().casefold())
    except OSError as exc:
        raise PackageError("Package tree could not be read") from exc
    for target in paths:
        relative = target.relative_to(root).as_posix()
        contained(root, relative)
        if target.name == _MACOS_METADATA_NAME:
            try:
                metadata_mode = target.lstat().st_mode
            except OSError as exc:
                raise PackageError("Package tree could not be read") from exc
            if not stat.S_ISREG(metadata_mode):
                raise PackageError("Package metadata is not a regular file")
            # Finder may add this inert regular file after extraction.  It is
            # deliberately outside the signed inventory and is never trusted.
            continue
        try:
            is_file = target.is_file()
        except OSError as exc:
            raise PackageError("Package tree could not be read") from exc
        if is_file and target != manifest_path:
            key = relative.casefold()
            if key in actual:
                raise PackageError("Case-colliding package files")
            if len(actual) >= _MAX_MANIFEST_FILES:
                raise PackageError("Package contains too many files")
            actual.add(key)
    return actual


def verify(root: Path) -> dict:
    """Verify every package file and return only its trusted manifest data."""

    root = Path(root)
    if root.is_symlink() or _reparse(root):
        raise PackageError("Package root links are forbidden")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise PackageError("Package root is unavailable") from exc
    manifest_path = contained(root, "package-manifest.json")
    try:
        if manifest_path.stat().st_size > 4_000_000:
            raise PackageError("Oversized manifest")
    except OSError as exc:
        raise PackageError("Package manifest is missing") from exc
    data = _load_json(manifest_path)
    if not isinstance(data, dict) or set(data) != {"schema", "product", "version", "files"}:
        raise PackageError("Invalid package identity")
    if type(data["schema"]) is not int or data["schema"] != MANIFEST_SCHEMA or data["product"] != PRODUCT:
        raise PackageError("Invalid package identity")
    if not isinstance(data["version"], str) or not VERSION.fullmatch(data["version"]):
        raise PackageError("Invalid package version")
    if not isinstance(data["files"], list) or not data["files"] or len(data["files"]) > _MAX_MANIFEST_FILES:
        raise PackageError("Invalid package files")
    seen: set[str] = set()
    for item in data["files"]:
        _manifest_entry(item, root, seen)
    actual = _iter_package_files(root, manifest_path)
    if actual != seen:
        raise PackageError("Unlisted or missing package file")
    plugin = _load_json(contained(root, "plugin.json"))
    if not isinstance(plugin, dict) or plugin.get("name") != PRODUCT or plugin.get("version") != data["version"]:
        raise PackageError("Plugin and package identity differ")
    return data


def registration(payload: Path, version: str) -> dict:
    """Build derived MCP metadata for one unified lazy server entrypoint."""

    if not payload.is_absolute() or not VERSION.fullmatch(version):
        raise PackageError("Registration needs an absolute payload and valid version")
    if payload.is_symlink() or _reparse(payload):
        raise PackageError("Registration payload links are forbidden")
    try:
        payload = payload.resolve(strict=True)
    except OSError as exc:
        raise PackageError("Registration payload is unavailable") from exc
    candidates = (
        payload / "runtime" / "python" / "python.exe",
        payload / "runtime" / "python" / "python",
        payload / "runtime" / "python" / "bin" / "python3",
    )
    python = next((candidate for candidate in candidates if candidate.is_file()), None)
    if python is None or python.is_symlink() or _reparse(python):
        raise PackageError("Registration runtime is missing")
    return {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": str(python),
                "args": ["-B", "-X", "utf8", "-m", MCP_SERVER_MODULE],
                "cwd": str(payload),
                # The Windows embedded runtime receives this path from its
                # _pth file; macOS private runtimes need the same explicit
                # source path in the derived registration.
                "env": {
                    "PYTHONPATH": str(payload / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                "startup_timeout_sec": 30,
                "tool_timeout_sec": 660,
            }
        }
    }
