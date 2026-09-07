from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk

from imap_plugin.autoconfig import AutoConfigurationError, autoconfigure
from imap_plugin.config import AccountConfig, config_path
from imap_plugin.credentials import platform_store


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
        "trusted_authserv_ids = ["
        + ", ".join(_toml_string(value) for value in settings.trusted_authserv_ids)
        + "]",
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
        values.extend(
            [
                f"smtp_host = {_toml_string(settings.smtp_host or '')}",
                f"smtp_port = {settings.smtp_port}",
                f"smtp_security = {_toml_string(settings.smtp_security)}",
                f"smtp_username = {_toml_string(settings.smtp_login)}",
            ]
        )
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix="config.", suffix=".tmp", dir=destination.parent
    )
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


def _discovery_hints() -> dict[str, object] | None:
    raw = os.getenv("IMAP_PLUGIN_DISCOVERY_HINTS", "").strip()
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Provider settings are invalid")
    return value


def main() -> int:
    root = tk.Tk()
    root.title("IMAP Plugin - secure setup")
    root.resizable(False, False)
    root.geometry("560x310")

    email_value = tk.StringVar()
    password_value = tk.StringVar()
    show_value = tk.BooleanVar(value=False)
    status_value = tk.StringVar(value="")
    completed = False
    report: dict[str, object] = {"status": "cancelled"}

    frame = tk.Frame(root, padx=28, pady=24)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Connect your email",
        font=("TkDefaultFont", 18, "bold"),
        anchor="w",
    ).grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Label(
        frame,
        text=(
            "Enter your email address and password. The plugin safely finds and "
            "checks the provider settings for you."
        ),
        justify="left",
        wraplength=500,
        anchor="w",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 20))

    tk.Label(frame, text="Email address", anchor="w").grid(
        row=2, column=0, sticky="w", pady=6
    )
    email_entry = tk.Entry(frame, textvariable=email_value, width=46)
    email_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=6)

    tk.Label(frame, text="Password", anchor="w").grid(
        row=3, column=0, sticky="w", pady=6
    )
    password_entry = tk.Entry(frame, textvariable=password_value, show="*", width=46)
    password_entry.grid(row=3, column=1, sticky="ew", pady=6)

    def toggle_password() -> None:
        password_entry.configure(show="" if show_value.get() else "*")

    tk.Checkbutton(
        frame,
        text="Show",
        variable=show_value,
        command=toggle_password,
    ).grid(row=3, column=2, sticky="w", padx=(8, 0))

    status = tk.Label(
        frame,
        textvariable=status_value,
        justify="left",
        wraplength=500,
        anchor="w",
        fg="#8B1A1A",
    )
    status.grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 8))

    buttons = tk.Frame(frame)
    buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(8, 0))

    def cancel() -> None:
        password_value.set("")
        root.destroy()

    def connect() -> None:
        nonlocal completed, report
        password = password_value.get()
        if "@" not in email_value.get() or not password:
            status_value.set("Vul je e-mailadres en wachtwoord of app-wachtwoord in.")
            return
        connect_button.configure(state="disabled")
        status.configure(fg="#333333")
        status_value.set("Finding your provider settings and checking the connection...")
        root.update_idletasks()
        try:
            result = autoconfigure(
                email_value.get(),
                password,
                hints=_discovery_hints(),
            )
            store = platform_store()
            store.write_secret(result.settings.credential_target, password)
            if result.settings.send_configured:
                store.write_secret(result.settings.smtp_credential_target, password)
            _write_config(result.settings)

            completed = True
            password_value.set("")
            report = {"status": "configured", "mailbox_actions_ready": result.mailbox_actions_ready,
                      "send_ready": result.send_ready, "smtp_diagnostics": list(result.smtp_diagnostics)}
        except AutoConfigurationError as exc:
            report = exc.public_dict()
        except Exception:
            report = {"status": "error", "error_code": "setup_failed",
                      "message": "De lokale setup is niet afgerond. Controleer gebruikerscontext, Keychain en installatiecomponenten."}
        finally:
            password = ""
            password_value.set("")
            root.destroy()

    tk.Button(buttons, text="Cancel", width=11, command=cancel).pack(
        side="right", padx=(8, 0)
    )
    connect_button = tk.Button(
        buttons,
        text="Connect",
        width=14,
        command=connect,
        default="active",
    )
    connect_button.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Return>", lambda _event: connect())
    email_entry.focus_set()
    root.mainloop()
    print(json.dumps(report, ensure_ascii=True))
    return 0 if completed else (20 if report["status"] == "error" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
