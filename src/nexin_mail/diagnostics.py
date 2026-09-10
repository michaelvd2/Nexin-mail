"""Local, schema-limited installation evidence. This module has no upload path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid

STAGES = {"package", "runtime", "host", "registration", "setup", "mailbox", "dashboard"}
OUTCOMES = {"attempted", "verified", "blocked", "not_checked"}
CODES = {
    "none", "package_invalid", "runtime_missing", "runtime_failed", "platform_unsupported",
    "architecture_unverified", "codex_missing", "codex_unsupported", "codex_failed",
    "installation_conflict", "registration_failed", "setup_pending", "mailbox_pending",
    "filesystem_failed", "language_mode_restricted", "powershell_blocked",
    "codex_config_mismatch", "migration_confirmation_required", "migration_failed",
    "migration_completed", "update_staged", "rollback_unavailable", "rollback_failed",
    "rollback_completed", "uninstall_not_registered", "uninstall_completed",
}
REPAIRS = {
    "none", "verify_package", "check_runtime", "check_host", "stage_package",
    "stage_update", "register_plugin", "migrate_legacy", "rollback", "uninstall",
}
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")


def event(stage: str, outcome: str, code: str = "none", repair: str = "none") -> dict:
    if stage not in STAGES or outcome not in OUTCOMES or code not in CODES or repair not in REPAIRS:
        raise ValueError("Unsupported diagnostic field")
    return {"stage": stage, "outcome": outcome, "code": code, "repair": repair}


def report(version: str, events: list[dict]) -> dict:
    if not isinstance(version, str) or not VERSION.fullmatch(version) or not isinstance(events, list) or not 1 <= len(events) <= 32:
        raise ValueError("Invalid diagnostic report")
    safe = []
    for item in events:
        if set(item) != {"stage", "outcome", "code", "repair"}:
            raise ValueError("Unexpected diagnostic fields")
        safe.append(event(**item))
    return {"schema": 1, "product": "nexin-mail", "version": version, "events": safe,
            "delivery": "local_only"}


def save_report(folder: Path, value: dict) -> Path:
    # Reconstruct rather than serializing caller-supplied extras or exception text.
    if set(value) != {"schema", "product", "version", "events", "delivery"}:
        raise ValueError("Unexpected report fields")
    clean = report(value["version"], value["events"])
    if value != clean:
        raise ValueError("Invalid report identity")
    folder = Path(folder)
    current = folder
    while True:
        try:
            if current.is_symlink() or bool(getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
                raise ValueError("Diagnostic path is a link")
        except FileNotFoundError:
            pass
        if current.parent == current:
            break
        current = current.parent
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("repair-" + uuid.uuid4().hex + ".json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    with os.fdopen(os.open(target, flags, 0o600), "w", encoding="utf-8") as stream:
        json.dump(clean, stream, indent=2)
        stream.write("\n")
    return target
