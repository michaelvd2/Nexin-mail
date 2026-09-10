from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


class VerificationError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def verify(root: Path) -> dict[str, object]:
    root = root.resolve()
    manifest_path = root / "package-manifest.json"
    if not manifest_path.is_file():
        raise VerificationError("package-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema") != 1 or manifest.get("product") != "imap-dashboard-handoff":
        raise VerificationError("package manifest identity is invalid")
    expected: dict[str, tuple[int, str]] = {}
    for item in manifest.get("files", []):
        relative = str(item.get("path", ""))
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise VerificationError(f"package path escaped the root: {relative}") from exc
        if not relative or relative in expected or not candidate.is_file():
            raise VerificationError(f"package entry is missing or duplicated: {relative}")
        expected[relative] = (int(item["bytes"]), str(item["sha256"]).upper())
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != "package-manifest.json"
    }
    if set(actual) != set(expected):
        raise VerificationError("package file set does not match the manifest")
    for relative, path in actual.items():
        expected_bytes, expected_hash = expected[relative]
        if path.stat().st_size != expected_bytes or digest(path) != expected_hash:
            raise VerificationError(f"package verification failed for {relative}")
    plugin_root = root / "plugins" / "imap-dashboard"
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        plugin_root = root
    plugin = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if plugin.get("name") != "imap-dashboard":
        raise VerificationError("plugin identity is invalid")
    return {
        "status": "pass",
        "product": manifest["product"],
        "version": manifest.get("version"),
        "files_verified": len(actual),
        "contains_runtime": (root / "runtime").exists(),
        "contains_credentials": False,
    }


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    try:
        result = verify(root)
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
