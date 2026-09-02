from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import state_root


ALLOWED_FIELDS = {
    "timestamp", "correlation_id", "bridge_version", "profile", "operation",
    "duration_ms", "result_class", "folder_hash", "count_delta", "error_class",
    "last_successful_check",
}


class SafeTrace:
    def __init__(self, profile: str, max_bytes: int = 262_144, files: int = 3, root: Path | None = None) -> None:
        self.profile = profile
        self.max_bytes = max_bytes
        self.files = files
        self.root = root or (state_root() / "logs")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "bridge.jsonl"

    def _rotate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        oldest = self.root / f"bridge.jsonl.{self.files}"
        if oldest.exists():
            oldest.unlink()
        for idx in range(self.files - 1, 0, -1):
            source = self.root / ("bridge.jsonl" if idx == 1 else f"bridge.jsonl.{idx - 1}")
            destination = self.root / f"bridge.jsonl.{idx}"
            if source.exists():
                os.replace(source, destination)

    def event(self, operation: str, started: float, result_class: str, **metadata: Any) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": secrets.token_hex(8),
            "bridge_version": __version__,
            "profile": self.profile,
            "operation": operation,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "result_class": result_class,
        }
        event.update(metadata)
        unknown = set(event) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"unsafe trace fields: {sorted(unknown)}")
        self._rotate()
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        return event["correlation_id"]


def hash_folder(value: str) -> str:
    import hashlib
    return hashlib.sha256(("imap-plugin-folder-v1:" + value).encode("utf-8")).hexdigest()[:16]
