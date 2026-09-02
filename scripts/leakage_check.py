from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from imap_plugin.config import load_settings, state_root
from imap_plugin.credentials import platform_store


CHUNK = 1024 * 1024


def contains(path: Path, needles: tuple[bytes, ...]) -> bool:
    overlap = max(len(value) for value in needles) - 1
    previous = b""
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                return False
            data = previous + block
            if any(value in data for value in needles):
                return True
            previous = data[-overlap:] if overlap > 0 else b""


def main() -> int:
    settings = load_settings()
    store = platform_store()
    targets = [settings.credential_target]
    if settings.send_configured:
        targets.append(settings.smtp_credential_target)
    metadata = [store.metadata(target) for target in targets]
    secrets = [store.read_secret(target) for target in targets]
    needles = tuple(
        encoded
        for secret in secrets
        for encoded in (secret.encode("utf-8"), secret.encode("utf-16-le"))
    )
    credential_time = max(datetime.fromisoformat(item.last_written_utc) for item in metadata)
    profile = Path(os.environ["USERPROFILE"])
    local = Path(os.environ["LOCALAPPDATA"])
    roaming = Path(os.environ["APPDATA"])
    roots = [
        profile / "plugins" / "imap-plugin",
        state_root(),
        profile / ".codex" / "config.toml",
        profile / ".codex" / "backups",
        Path(os.environ.get("TEMP", str(local / "Temp"))),
        local / "CrashDumps",
        local / "Microsoft" / "Windows" / "WER",
        roaming / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
    ]
    findings = []
    scanned = 0
    unreadable = 0
    unreadable_paths = []
    unreadable_precredential = []
    seen: set[Path] = set()
    for root in roots:
        candidates = [root] if root.is_file() else (root.rglob("*") if root.exists() else [])
        for path in candidates:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if "runtime\\venv" in str(path) or "runtime\\wheelhouse" in str(path):
                continue
            try:
                scanned += 1
                if contains(path, needles):
                    findings.append(str(path))
            except (OSError, PermissionError):
                try:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                    if modified <= credential_time:
                        unreadable_precredential.append(str(path))
                    else:
                        unreadable += 1
                        unreadable_paths.append(str(path))
                except OSError:
                    unreadable += 1
                    unreadable_paths.append(str(path))
    secrets = []
    report = {
        "encodings": ["utf-8", "utf-16-le"],
        "credential_count": len(targets),
        "scanned_files": scanned,
        "unreadable_files": unreadable,
        "unreadable_paths": unreadable_paths,
        "unreadable_precredential_files": len(unreadable_precredential),
        "unreadable_precredential_paths": unreadable_precredential,
        "skipped_large_files": 0,
        "finding_count": len(findings),
        "finding_paths": findings,
    }
    print(json.dumps(report, indent=2))
    return 3 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
