"""Verify a built macOS package after extraction to two relocated roots.

This harness is intentionally package/runtime evidence only.  It never calls
the installer, Codex, Keychain, IMAP, SMTP, or a live mailbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import zipfile

from nexin_mail.package import contained, registration, verify


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_package(archive: Path, destination: Path) -> Path:
    archive = archive.resolve(strict=True)
    destination = destination.resolve(strict=False)
    if destination.exists():
        raise ValueError("relocation destination already exists")
    destination.mkdir(parents=True)
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as stream:
        for info in stream.infolist():
            name = info.filename
            if name.endswith("/"):
                raise ValueError("package contains an unexpected directory entry")
            key = name.casefold()
            if key in seen:
                raise ValueError("package contains a case-colliding path")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0o170000
            if info.create_system == 3 and mode == stat.S_IFLNK:
                raise ValueError("package contains a symlink entry")
            if info.create_system == 3 and mode not in {0, stat.S_IFREG}:
                raise ValueError("package contains a non-regular entry")
            target = contained(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with stream.open(info, "r") as source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            if info.create_system == 3:
                target.chmod((info.external_attr >> 16) & 0o777)
    if any(item.is_symlink() for item in destination.rglob("*")):
        raise ValueError("package extraction left a symlink")
    return destination


def verify_extracted(root: Path) -> dict[str, object]:
    manifest = verify(root)
    runtime_root = root / "payload" / "runtime" / "python"
    runtime = runtime_root / "bin" / "python3.12"
    if not runtime.is_file() or runtime.is_symlink() or not os.access(runtime, os.X_OK):
        raise ValueError("relocated runtime is missing or not executable")
    ui = root / "payload" / "src" / "imap_dashboard" / "ui" / "mail-app.html"
    ui_text = ui.read_text(encoding="utf-8")
    if "<script src=" in ui_text or "<link href=" in ui_text or '<link rel="stylesheet"' in ui_text:
        raise ValueError("relocated UI is not self-contained")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root / "payload" / "src")
    environment.pop("IMAP_PLUGIN_CONFIG", None)
    check = subprocess.run(
        [str(runtime), "-B", "-X", "utf8", str(root / "payload" / "scripts" / "verify_nexin_runtime.py")],
        cwd=str(root), env=environment, check=True, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    verifier = json.loads(check.stdout.strip().splitlines()[-1])
    if verifier.get("status") != "pass" or verifier.get("server") != "nexin-mail" or verifier.get("tools") != 57:
        raise ValueError(f"runtime verifier returned an unexpected result: {verifier!r}")
    probe = subprocess.run(
        [str(runtime), "-B", "-c", "import json,platform,sys,sysconfig; print(json.dumps({'version':sys.version.split()[0],'machine':platform.machine(),'executable':sys.executable,'prefix':sys.prefix,'purelib':sysconfig.get_path('purelib')}))"],
        cwd=str(root), env=environment, check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    identity = json.loads(probe.stdout.strip())
    for field in ("executable", "prefix", "purelib"):
        if not Path(identity[field]).resolve(strict=False).is_relative_to(runtime_root.resolve(strict=True)):
            raise ValueError(f"runtime path escaped relocated package: {field}")
    metadata = registration((root / "payload").resolve(strict=True), manifest["version"])
    entry = metadata["mcpServers"]["mail"]
    return {
        "manifest_files": len(manifest["files"]),
        "runtime": {"version": identity["version"], "machine": identity["machine"]},
        "server": verifier["server"],
        "tools": verifier["tools"],
        "unconfigured_onboarding": verifier["unconfigured_onboarding"],
        "registration_command": entry["command"],
        "registration_cwd": entry["cwd"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--extract-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        archive = args.archive.resolve(strict=True)
        first = extract_package(archive, args.extract_root / "relocation-1")
        second = extract_package(archive, args.extract_root / "relocation-2")
        one = verify_extracted(first)
        two = verify_extracted(second)
        stable = {key: value for key, value in one.items() if key not in {"registration_command", "registration_cwd"}}
        stable_two = {key: value for key, value in two.items() if key not in {"registration_command", "registration_cwd"}}
        if stable != stable_two:
            raise ValueError("relocated package probes disagree")
        print(json.dumps({
            "status": "pass",
            "archive": str(archive),
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": sha256(archive),
            "relocations": [str(first), str(second)],
            "verification": stable,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
