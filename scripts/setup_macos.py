from __future__ import annotations

import json
import os
import tkinter as tk

from imap_plugin.autoconfig import AutoConfigurationError, autoconfigure
from imap_plugin.config import AccountConfig
from imap_plugin.credentials import platform_store
from imap_plugin.enrollment import enroll_microsoft_native, write_config
from imap_plugin.oauth import OAuthError


def _toml_string(value: str) -> str:
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("configuration values must be single-line")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_config(settings: AccountConfig) -> None:
    # Keep this local name for platform tests and older setup callers.
    write_config(settings)


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
    root.geometry("560x410")

    email_value = tk.StringVar()
    password_value = tk.StringVar()
    auth_method_value = tk.StringVar(value="password")
    smtp_value = tk.BooleanVar(value=False)
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
            "Choose Microsoft browser sign-in or the existing password/app-password "
            "route. Secrets stay inside the native setup process."
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

    tk.Label(frame, text="Sign-in method", anchor="w").grid(
        row=3, column=0, sticky="w", pady=6
    )
    method_frame = tk.Frame(frame)
    method_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=6)
    tk.Radiobutton(
        method_frame, text="Microsoft browser sign-in", variable=auth_method_value,
        value="microsoft",
    ).pack(side="left")
    tk.Radiobutton(
        method_frame, text="Password or app-password", variable=auth_method_value,
        value="password",
    ).pack(side="left", padx=(12, 0))

    password_label = tk.Label(frame, text="Password", anchor="w")
    password_label.grid(row=4, column=0, sticky="w", pady=6)
    password_entry = tk.Entry(frame, textvariable=password_value, show="*", width=46)
    password_entry.grid(row=4, column=1, sticky="ew", pady=6)

    def toggle_password() -> None:
        password_entry.configure(show="" if show_value.get() else "*")

    show_button = tk.Checkbutton(
        frame,
        text="Show",
        variable=show_value,
        command=toggle_password,
    )
    show_button.grid(row=4, column=2, sticky="w", padx=(8, 0))

    smtp_check = tk.Checkbutton(
        frame,
        text="Enable Microsoft SMTP sending (additional consent)",
        variable=smtp_value,
    )
    smtp_check.grid(row=5, column=1, columnspan=2, sticky="w", pady=(2, 6))

    status = tk.Label(
        frame,
        textvariable=status_value,
        justify="left",
        wraplength=500,
        anchor="w",
        fg="#8B1A1A",
    )
    status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 8))

    buttons = tk.Frame(frame)
    buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(8, 0))

    def update_method() -> None:
        microsoft = auth_method_value.get() == "microsoft"
        if microsoft:
            password_label.grid_remove()
            password_entry.grid_remove()
            show_button.grid_remove()
            smtp_check.configure(state="normal")
            status_value.set("Microsoft opens a local browser. No password is requested here.")
        else:
            password_label.grid()
            password_entry.grid()
            show_button.grid()
            smtp_check.configure(state="disabled")
            smtp_value.set(False)
            status_value.set("")

    auth_method_value.trace_add("write", lambda *_: update_method())
    update_method()

    def cancel() -> None:
        password_value.set("")
        root.destroy()

    def connect() -> None:
        nonlocal completed, report
        email = email_value.get()
        password = password_value.get()
        microsoft = auth_method_value.get() == "microsoft"
        if "@" not in email:
            status_value.set("Vul een geldig e-mailadres in.")
            return
        if not microsoft and not password:
            status_value.set("Vul je e-mailadres en wachtwoord of app-wachtwoord in.")
            return
        connect_button.configure(state="disabled")
        status.configure(fg="#333333")
        status_value.set(
            "Opening Microsoft sign-in in your browser..." if microsoft
            else "Finding your provider settings and checking the connection..."
        )
        root.update_idletasks()
        try:
            if microsoft:
                def oauth_progress(event: str) -> None:
                    status_value.set(
                        "Opening Microsoft sign-in in your browser..."
                        if event != "browser_sign_in_complete"
                        else "Microsoft sign-in complete. Saving protected setup..."
                    )
                    root.update_idletasks()

                enrollment = enroll_microsoft_native(
                    progress=oauth_progress,
                    email_address=email,
                    include_smtp=smtp_value.get(),
                )
                completed = True
                report = {"status": "configured", **enrollment.public_dict()}
            else:
                result = autoconfigure(
                    email,
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
        except OAuthError as exc:
            report = {"status": "error", "error_code": exc.code, "message": exc.public_message}
        except KeyboardInterrupt:
            report = {"status": "error", "error_code": "oauth_cancelled", "message": "Microsoft sign-in was cancelled."}
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
