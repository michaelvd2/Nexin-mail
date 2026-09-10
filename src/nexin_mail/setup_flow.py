"""Durable, single-owner native setup with bounded, resumable host waits.

Only enumerated state crosses the host boundary. Credentials stay in the
original native form and OS keystore. A lost worker never authorizes reopening
an unconfirmed popup. The receipt is canonical; no PID is used as identity.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from imap_plugin.config import config_path, load_settings
from imap_plugin.review import SetupError, launch_setup
from imap_plugin.setup_recovery import recovery_report
from .install import _assert_no_links

TERMINAL = {"ready", "cancelled", "failed"}
STATES = TERMINAL | {"starting", "waiting_for_input", "checking_connection"}


def session_root() -> Path:
    return config_path().absolute().parent / "nexin-setup-session"


def _root(root: Path | None) -> Path:
    value = _assert_no_links(root if root is not None else session_root())
    value.mkdir(mode=0o700, parents=True, exist_ok=True)
    return value


@contextmanager
def _lock(root: Path, name: str):
    path = _assert_no_links(root / name)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    held = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        os.lseek(fd, 0, 0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except (BlockingIOError, OSError):
            pass
        yield held
    finally:
        if held:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(root: Path) -> dict | None:
    path = _assert_no_links(root / "current.json")
    if not path.exists():
        return None
    if path.stat().st_size > 16384:
        raise ValueError("invalid setup receipt")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema") != 1
        or not re.fullmatch(r"[a-f0-9]{32}", str(value.get("session_id", "")))
        or value.get("status") not in STATES
        or not isinstance(value.get("updated_at"), (float, int))):
        raise ValueError("invalid setup receipt")
    return value


def _write(root: Path, value: dict) -> None:
    value = {**value, "updated_at": time.time()}
    target = _assert_no_links(root / "current.json")
    temp = root / ("receipt-" + uuid.uuid4().hex + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)


def _public(value: dict) -> dict:
    result = {key: value[key] for key in ("session_id", "status", "updated_at")}
    status = result["status"]
    result["next_action"] = {
        "starting": "wait_setup", "waiting_for_input": "wait_setup",
        "checking_connection": "wait_setup", "ready": "render_mail_view",
        "cancelled": "stop", "failed": "follow_recovery",
    }[status]
    if status == "ready":
        result.update(mail_connection="verified", dashboard="not_checked")
    if status == "failed":
        result["recovery"] = recovery_report(value.get("recovery") or {"error_code": value.get("error_code")})
    return result


def status(session_id: str | None = None, *, root: Path | None = None) -> dict:
    root = _root(root)
    value = _read(root)
    if value is None:
        return {"status": "not_started", "next_action": "open_setup"}
    if session_id is not None and value["session_id"] != session_id:
        return {"status": "session_mismatch", "next_action": "inspect_setup_owner"}
    result = _public(value)
    if value["status"] not in TERMINAL:
        with _lock(root, "worker.lock") as available:
            if available and (value["status"] != "starting" or time.time() - value["updated_at"] > 15):
                result.update(status="interrupted", next_action="inspect_setup_owner")
    return result


def _spawn(root: Path, session_id: str) -> None:
    command = [sys.executable, "-P", "-B", "-X", "utf8", "-m", "nexin_mail.setup_flow", "worker", "--session-id", session_id, "--session-root", str(root)]
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def start(*, new_attempt: bool = False, root: Path | None = None) -> dict:
    root = _root(root)
    with _lock(root, "start.lock") as held:
        if not held:
            return {"status": "starting", "next_action": "setup_status", "retry_after_seconds": 1}
        existing = _read(root)
        if existing is not None:
            # Never reopen an active/interrupted session, even on explicit retry.
            if existing["status"] not in TERMINAL or not new_attempt:
                return status(existing["session_id"], root=root)
        value = {"schema": 1, "session_id": uuid.uuid4().hex, "status": "starting", "updated_at": time.time(), "open_form": new_attempt or not config_path().is_file()}
        _write(root, value)
        try:
            _spawn(root, value["session_id"])
        except OSError:
            _write(root, {**value, "status": "failed", "error_code": "setup_launch_failed"})
        return status(value["session_id"], root=root)


def wait(session_id: str, timeout_seconds: float = 50, *, root: Path | None = None) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise ValueError("invalid setup session")
    timeout_seconds = min(50, max(0, timeout_seconds))
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = status(session_id, root=root)
        if result["status"] not in {"starting", "waiting_for_input", "checking_connection"}:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result
        time.sleep(min(0.25, remaining))


def _check_connection() -> None:
    from imap_plugin.bridge import MailBridge
    settings = load_settings()
    # Strict TLS/connectivity/capabilities only. No messages or mailbox changes.
    health = MailBridge(settings, "read").tls_and_capabilities()
    if health.get("tls", {}).get("verified") is not True:
        raise SetupError({"error_code": "tls_failed"})


def _error_code(exc: Exception) -> str:
    from imap_plugin.bridge import MailAuthenticationError, MailTlsError, MailLoginDisabledError
    if isinstance(exc, SetupError):
        return exc.report["error_code"]
    if isinstance(exc, MailAuthenticationError):
        return "authentication_failed"
    if isinstance(exc, MailTlsError):
        return "tls_failed"
    if isinstance(exc, MailLoginDisabledError):
        return "password_login_disabled"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "network_failed"
    return "setup_failed"


def worker(session_id: str, *, root: Path | None = None, launch=None, check=None) -> None:
    root = _root(root)
    with _lock(root, "worker.lock") as held:
        value = _read(root)
        if not held or value is None or value["session_id"] != session_id or value["status"] != "starting":
            return
        try:
            if value.get("open_form", True):
                _write(root, {**value, "status": "waiting_for_input"})
                # Wait lifetime belongs to the window, not an MCP request timeout.
                if not (launch or (lambda: launch_setup(timeout=None)))():
                    _write(root, {**value, "status": "cancelled"})
                    return
            _write(root, {**value, "status": "checking_connection"})
            (check or _check_connection)()
            _write(root, {**value, "status": "ready"})
        except Exception as exc:
            failure = {**value, "status": "failed", "error_code": _error_code(exc)}
            if isinstance(exc, SetupError):
                failure["recovery"] = recovery_report(exc.report)
            _write(root, failure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "wait", "worker"))
    parser.add_argument("--session-id")
    parser.add_argument("--session-root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=50)
    parser.add_argument("--new-attempt", action="store_true")
    args = parser.parse_args()
    if args.action == "worker":
        worker(args.session_id, root=args.session_root)
        return 0
    if args.action == "start":
        result = start(new_attempt=args.new_attempt, root=args.session_root)
    elif args.action == "wait":
        result = wait(args.session_id, args.timeout_seconds, root=args.session_root)
    else:
        result = status(args.session_id, root=args.session_root)
    if result.get("session_id"):
        result["wait_command"] = [sys.executable, "-P", "-B", "-X", "utf8", "-m", "nexin_mail.setup_flow", "wait", "--session-id", result["session_id"], "--session-root", str(_root(args.session_root)), "--timeout-seconds", "50"]
        result["pythonpath"] = str(Path(__file__).resolve().parents[1])
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
