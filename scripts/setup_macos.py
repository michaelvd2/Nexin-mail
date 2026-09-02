from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

from imap_plugin.config import AccountConfig, config_path
from imap_plugin.credentials import platform_store


def _ask(label: str, *, initial: str = "", secret: bool = False) -> str | None:
    return simpledialog.askstring(
        "IMAP Plugin setup",
        label,
        initialvalue=initial,
        show="*" if secret else None,
    )


def _port(value: str | None, label: str) -> int:
    try:
        number = int(value or "")
    except ValueError as exc:
        raise ValueError(f"{label} must be a number between 1 and 65535") from exc
    if not 1 <= number <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return number


def _security(value: str | None, label: str) -> str:
    normalized = (value or "").strip().casefold()
    if normalized not in {"implicit_tls", "starttls"}:
        raise ValueError(f"{label} must be implicit_tls or starttls")
    return normalized


def _toml_string(value: str) -> str:
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("configuration values must be single-line")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_config(settings: AccountConfig) -> None:
    values = [
        'account_id = "default"',
        f"username = {_toml_string(settings.username)}",
        f"email_address = {_toml_string(settings.email_address or settings.username)}",
        f"host = {_toml_string(settings.host)}",
        f"port = {settings.port}",
        f"imap_security = {_toml_string(settings.imap_security)}",
        'credential_target = "imap-plugin/imap"',
        'smtp_credential_target = "imap-plugin/smtp"',
        "trusted_authserv_ids = [" + ", ".join(_toml_string(value) for value in settings.trusted_authserv_ids) + "]",
        f"operator_enabled = {'true' if settings.operator_enabled else 'false'}",
        "timeout_seconds = 15.0",
        "max_results = 20",
        "max_scan = 250",
        "max_days = 31",
        "max_message_bytes = 262144",
        "trace_max_bytes = 262144",
        "trace_files = 3",
    ]
    if settings.send_configured:
        values.extend([
            f"smtp_host = {_toml_string(settings.smtp_host or '')}",
            f"smtp_port = {settings.smtp_port}",
            f"smtp_security = {_toml_string(settings.smtp_security)}",
            f"smtp_username = {_toml_string(settings.smtp_login)}",
        ])
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(values) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo(
            "IMAP Plugin setup",
            "Connect one standards-based IMAP mailbox. Passwords stay in macOS Keychain and never enter Codex chat or configuration files.",
        )
        email_address = _ask("Mailbox email address")
        username = _ask("IMAP username", initial=email_address or "")
        host = _ask("IMAP server DNS name (for example imap.example.com)")
        security = _security(_ask("IMAP security: implicit_tls or starttls", initial="implicit_tls"), "IMAP security")
        port = _port(_ask("IMAP port", initial="993" if security == "implicit_tls" else "143"), "IMAP port")
        password = _ask("IMAP password or app password", secret=True)
        confirmation = _ask("Confirm IMAP password", secret=True)
        if None in {email_address, username, host, password, confirmation}:
            return 1
        if not password or password != confirmation:
            raise ValueError("IMAP passwords are empty or do not match")

        smtp_enabled = messagebox.askyesno("IMAP Plugin setup", "Configure SMTP for reviewed sending?")
        smtp_values: dict[str, object] = {}
        smtp_password: str | None = None
        if smtp_enabled:
            smtp_host = _ask("SMTP server DNS name")
            smtp_security = _security(_ask("SMTP security: implicit_tls or starttls", initial="implicit_tls"), "SMTP security")
            smtp_port = _port(_ask("SMTP port", initial="465" if smtp_security == "implicit_tls" else "587"), "SMTP port")
            smtp_username = _ask("SMTP username", initial=username or "")
            reuse = messagebox.askyesno("IMAP Plugin setup", "Use the same password for SMTP?")
            if reuse:
                smtp_password = password
            else:
                smtp_password = _ask("SMTP password or app password", secret=True)
                smtp_confirmation = _ask("Confirm SMTP password", secret=True)
                if not smtp_password or smtp_password != smtp_confirmation:
                    raise ValueError("SMTP passwords are empty or do not match")
            if None in {smtp_host, smtp_username}:
                return 1
            smtp_values = {
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "smtp_security": smtp_security,
                "smtp_username": smtp_username,
            }

        trusted_raw = _ask("Trusted Authentication-Results hostnames, comma-separated (optional)", initial="")
        if trusted_raw is None:
            return 1
        trusted = tuple(value.strip() for value in trusted_raw.split(",") if value.strip())
        request_operator = messagebox.askyesno(
            "IMAP Plugin setup",
            "Enable reviewed mailbox actions after the read-only connection check passes?",
        )
        base = dict(
            username=username or "",
            email_address=email_address,
            host=host or "",
            port=port,
            imap_security=security,
            trusted_authserv_ids=trusted,
            operator_enabled=False,
            **smtp_values,
        )
        settings = AccountConfig(**base)
        store = platform_store()
        store.write_secret(settings.credential_target, password)
        if smtp_enabled and smtp_password is not None:
            store.write_secret(settings.smtp_credential_target, smtp_password)
        _write_config(settings)

        environment = os.environ.copy()
        environment["IMAP_PLUGIN_PROFILE"] = "read"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-m", "imap_plugin.cli", "doctor"],
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=90,
            check=False,
            env=environment,
        )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            report = {}
        if completed.returncode != 0 or report.get("connectivity") != "pass":
            raise RuntimeError("Connection verification failed. Credentials remain local and mailbox actions remain disabled.")
        if request_operator:
            if not report.get("mailbox_actions_ready"):
                raise RuntimeError("Reading works, but safe MOVE, Drafts, or Trash support is missing. Mailbox actions remain disabled.")
            _write_config(AccountConfig(**{**base, "operator_enabled": True}))
        messagebox.showinfo(
            "IMAP Plugin setup",
            "Connection verified. Reviewed mailbox actions are enabled." if request_operator else "Connection verified in safe read mode.",
        )
        return 0
    except Exception as exc:
        messagebox.showerror("IMAP Plugin setup", str(exc))
        return 1
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
