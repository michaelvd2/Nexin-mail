from __future__ import annotations

import json
import sys
from pathlib import Path

from imap_plugin.config import load_settings
from imap_plugin.credentials import platform_store


def contains(path: Path, needles: tuple[bytes, ...]) -> bool:
    overlap = max(len(item) for item in needles) - 1
    previous = b""
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            combined = previous + block
            if any(item in combined for item in needles):
                return True
            previous = combined[-overlap:] if overlap else b""
    return False


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: package_secret_scan.py ROOT [ROOT ...]")
    settings = load_settings()
    store = platform_store()
    targets = [settings.credential_target]
    if settings.send_configured:
        targets.append(settings.smtp_credential_target)
    secrets = [store.read_secret(target) for target in targets]
    needles = tuple(
        encoded
        for secret in secrets
        for encoded in (secret.encode("utf-8"), secret.encode("utf-16-le"))
    )
    findings: list[str] = []
    unreadable: list[str] = []
    scanned = 0
    for raw_root in sys.argv[1:]:
        root = Path(raw_root).resolve()
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            try:
                scanned += 1
                if contains(path, needles):
                    findings.append(str(path))
            except OSError:
                unreadable.append(str(path))
    secrets.clear()
    print(
        json.dumps(
            {
                "status": "pass" if not findings and not unreadable else "fail",
                "credential_values_checked": len(targets),
                "encodings": ["utf-8", "utf-16-le"],
                "files_scanned": scanned,
                "finding_count": len(findings),
                "finding_paths": findings,
                "unreadable_count": len(unreadable),
                "unreadable_paths": unreadable,
            },
            indent=2,
        )
    )
    return 0 if not findings and not unreadable else 3


if __name__ == "__main__":
    raise SystemExit(main())
