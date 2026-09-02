from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .bridge import MailBridge
from .config import config_path, load_settings, state_root
from .credentials import platform_store
from .privacy import trace_schema_is_safe
from .sender import MailSender


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def scheduled_check() -> int:
    os.environ["IMAP_PLUGIN_PROFILE"] = "read"
    path = state_root() / "health.json"
    started = time.monotonic()
    stage = "load_settings"
    try:
        settings = load_settings()
        stage = "connectivity"
        bridge = MailBridge(settings, "read")
        health = bridge.tls_and_capabilities()
        stage = "folders"
        boxes = bridge.list_mailboxes()
        stage = "write_health"
        timestamp = datetime.now(timezone.utc).isoformat()
        correlation_id = bridge.trace.event("scheduled_check", started, "success", last_successful_check=timestamp)
        value = {
            "timestamp": timestamp,
            "correlation_id": correlation_id,
            "bridge_version": __version__,
            "profile": "read",
            "result": "success",
            "endpoint": health["endpoint"],
            "tls_verified": health["tls"]["verified"],
            "folder_count": len(boxes),
            "total_message_count": sum(item.get("messages") or 0 for item in boxes),
        }
        _atomic_json(path, value)
        return 0
    except Exception as exc:
        from .trace import SafeTrace
        timestamp = datetime.now(timezone.utc).isoformat()
        correlation_id = SafeTrace("read").event("scheduled_check", started, "error", error_class=type(exc).__name__)
        _atomic_json(path, {
            "timestamp": timestamp,
            "correlation_id": correlation_id,
            "bridge_version": __version__,
            "profile": "read",
            "result": "error",
            "error_class": type(exc).__name__,
            "failure_stage": stage,
        })
        return 1


def doctor() -> int:
    report: dict[str, object] = {
        "bridge_version": __version__,
        "python": sys.executable,
        "config_path": str(config_path()),
        "config_present": config_path().is_file(),
        "credentials": {
            "imap": {"present": False},
            "smtp": {"present": False},
        },
        "connectivity": "not_checked",
        "smtp_connectivity": "not_checked",
        "mailbox_actions_ready": False,
        "send_ready": False,
        "operator_ready": False,
        "trace_schema_safe": trace_schema_is_safe(state_root() / "logs" / "bridge.jsonl"),
        "scheduler": {"present": False},
    }
    try:
        settings = load_settings()
        store = platform_store()
        metadata = store.metadata(settings.credential_target)
        report["credentials"]["imap"] = {
            "present": True,
            "type": metadata.credential_type,
            "persist": metadata.persist,
            "blob_size": metadata.blob_size,
        }
        health = MailBridge(settings, "read").tls_and_capabilities()
        report["connectivity"] = "pass" if health["tls"]["verified"] else "fail"
        report["feature_gates"] = health["operator_features"]
        if settings.send_configured:
            smtp_metadata = store.metadata(settings.smtp_credential_target)
            report["credentials"]["smtp"] = {
                "present": True,
                "type": smtp_metadata.credential_type,
                "persist": smtp_metadata.persist,
                "blob_size": smtp_metadata.blob_size,
            }
            smtp_health = MailSender(settings, store.read_secret).probe()
            report["smtp_connectivity"] = "pass" if smtp_health["authenticated"] else "fail"
            report["smtp"] = smtp_health
        gates = health["operator_features"]
        report["mailbox_actions_ready"] = bool(
            report["connectivity"] == "pass"
            and all(gates.get(name) is True for name in ("safe_move", "drafts", "bin"))
        )
        report["send_ready"] = bool(
            report["mailbox_actions_ready"]
            and report["smtp_connectivity"] == "pass"
            and all(gates.get(name) is True for name in ("sent", "send_configured"))
        )
        report["operator_ready"] = report["mailbox_actions_ready"]
    except Exception as exc:
        report["error_class"] = type(exc).__name__
    if os.name == "nt":
        try:
            task = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", "IMAP Plugin Read Check", "/FO", "LIST", "/V"],
                text=True, capture_output=True, timeout=10, check=False,
            )
            report["scheduler"] = {"present": task.returncode == 0, "kind": "windows_task"}
        except Exception:
            pass
    elif platform.system() == "Darwin":
        launch_agent = Path.home() / "Library" / "LaunchAgents" / "org.openai.codex.imap-plugin.read-check.plist"
        report["scheduler"] = {"present": launch_agent.is_file(), "kind": "launch_agent"}
    print(json.dumps(report, indent=2))
    credentials = report.get("credentials", {})
    imap = credentials.get("imap", {}) if isinstance(credentials, dict) else {}
    smtp = credentials.get("smtp", {}) if isinstance(credentials, dict) else {}
    return 0 if (
        report.get("connectivity") == "pass"
        and imap.get("persist") == 2
        and (report.get("smtp_connectivity") != "pass" or smtp.get("persist") == 2)
    ) else 1


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "doctor"
    raise SystemExit(scheduled_check() if command == "check" else doctor())
