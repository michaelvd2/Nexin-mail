"""Local release gate for a verified Nexin Mail package or archive.

This check intentionally reports signing as unattested.  A manifest hash is an
integrity check and does not establish publisher identity or enterprise policy
approval.  No network, upload, or signing operation is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from pathlib import PurePosixPath
import zipfile


_RESERVED_WINDOWS_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _validate_archive_name(name: str) -> None:
    """Apply the extraction-safe package path rules before reading content."""
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 240
        or name.endswith("/")
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or PurePosixPath(name).is_absolute()
    ):
        raise ValueError("release archive contains an unsafe path")
    parts = name.split("/")
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        if (
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or stem in _RESERVED_WINDOWS_NAMES
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
        ):
            raise ValueError("release archive contains an unsafe path")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def inspect_archive(path: Path) -> dict[str, object]:
    try:
        if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("release archive path may not be a link")
    except OSError as exc:
        raise ValueError("release archive is missing") from exc
    if not path.is_file():
        raise ValueError("release archive is missing")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        folded_names = {name.casefold() for name in names}
        if len(names) != len(folded_names) or "package-manifest.json" not in names:
            raise ValueError("release archive has duplicate or missing manifest entries")
        for entry in entries:
            name = entry.filename
            _validate_archive_name(name)
            if stat.S_ISLNK((entry.external_attr >> 16) & 0o177777):
                raise ValueError("release archive contains a link")
        manifest = json.loads(archive.read("package-manifest.json"), object_pairs_hook=_strict_object)
        if not isinstance(manifest, dict) or set(manifest) != {"schema", "product", "version", "files"} or type(manifest.get("schema")) is not int or manifest.get("product") != "nexin-mail" or manifest.get("schema") != 1:
            raise ValueError("release archive has the wrong product")
        if not isinstance(manifest.get("files"), list) or not manifest["files"]:
            raise ValueError("release archive manifest files are invalid")
        listed: set[str] = set()
        for item in manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"} or not isinstance(item["path"], str) or type(item["bytes"]) is not int or item["bytes"] < 0 or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
                raise ValueError("release archive manifest entry is invalid")
            key = item["path"].casefold()
            if key in listed or key == "package-manifest.json" or item["path"] not in names:
                raise ValueError("release archive manifest paths do not match")
            listed.add(key)
            content = archive.read(item["path"])
            if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("release archive file hash mismatch")
        actual = {name.casefold() for name in names if name != "package-manifest.json"}
        if actual != listed:
            raise ValueError("release archive contains an unlisted file")
        plugin = json.loads(archive.read("plugin.json"), object_pairs_hook=_strict_object)
        if not isinstance(plugin, dict) or plugin.get("name") != "nexin-mail" or plugin.get("version") != manifest.get("version"):
            raise ValueError("release archive plugin identity mismatch")
    return {
        "product": "nexin-mail",
        "archive": str(path.resolve()),
        "sha256": _sha256(path),
        "package_manifest": "present",
        "integrity": "manifest_verified",
        "runtime_import": "not_checked",
        "signing": "not_attested",
        "publisher_authenticity": "not_attested",
        "upload": "not_performed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_archive(args.archive), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
