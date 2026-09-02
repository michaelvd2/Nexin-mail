from __future__ import annotations

from pathlib import Path


def scan_for_secret(paths: list[Path], secret: str) -> list[Path]:
    if not secret:
        raise ValueError("empty scan needle is rejected")
    needles = (secret.encode("utf-8"), secret.encode("utf-16-le"))
    findings: list[Path] = []
    for root in paths:
        candidates = [root] if root.is_file() else (list(root.rglob("*")) if root.exists() else [])
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                data = candidate.read_bytes()
            except (OSError, PermissionError):
                continue
            if any(needle in data for needle in needles):
                findings.append(candidate)
    return findings


def trace_schema_is_safe(path: Path) -> bool:
    import json
    from .trace import ALLOWED_FIELDS
    if not path.exists():
        return True
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and (set(json.loads(line)) - ALLOWED_FIELDS):
            return False
    return True
