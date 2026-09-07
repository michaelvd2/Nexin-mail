from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imap_plugin.windows_host import PowerShellUnavailable, powershell_command
from imap_plugin.setup_recovery import recovery_report


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the private two-field IMAP Plugin setup window.")
    parser.add_argument("--imap-host")
    parser.add_argument("--imap-port", type=int)
    parser.add_argument("--imap-security", choices=("implicit_tls", "starttls"))
    parser.add_argument("--imap-username-style", choices=("email", "localpart"), default="email")
    parser.add_argument("--smtp-host")
    parser.add_argument("--smtp-port", type=int)
    parser.add_argument("--smtp-security", choices=("implicit_tls", "starttls"))
    parser.add_argument("--smtp-username-style", choices=("email", "localpart"), default="email")
    return parser.parse_args()


def _hints(args: argparse.Namespace) -> dict[str, object]:
    result: dict[str, object] = {}
    imap_values = (args.imap_host, args.imap_port, args.imap_security)
    if any(value is not None for value in imap_values):
        if not all(value is not None for value in imap_values):
            raise SystemExit("IMAP provider hints require host, port, and security together")
        result["imap"] = {
            "host": args.imap_host,
            "port": args.imap_port,
            "security": args.imap_security,
            "username_style": args.imap_username_style,
        }
    smtp_values = (args.smtp_host, args.smtp_port, args.smtp_security)
    if any(value is not None for value in smtp_values):
        if not all(value is not None for value in smtp_values):
            raise SystemExit("SMTP provider hints require host, port, and security together")
        result["smtp"] = {
            "host": args.smtp_host,
            "port": args.smtp_port,
            "security": args.smtp_security,
            "username_style": args.smtp_username_style,
        }
    return result


def main() -> int:
    args = _arguments()
    environment = os.environ.copy()
    hints = _hints(args)
    if hints:
        environment["IMAP_PLUGIN_DISCOVERY_HINTS"] = json.dumps(hints, separators=(",", ":"))
    if os.name == "nt":
        try:
            command = powershell_command(ROOT / "scripts" / "enroll_gui.ps1")
        except PowerShellUnavailable:
            print(json.dumps(recovery_report({"error_code": "powershell_blocked"})))
            return 21
    elif platform.system() == "Darwin":
        command = [sys.executable, str(ROOT / "scripts" / "setup_macos.py")]
    else:
        raise RuntimeError("IMAP Plugin secure enrollment is available only on Windows and macOS")
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        code = "permission_denied" if isinstance(exc, PermissionError) else "setup_launch_failed"
        print(json.dumps(recovery_report({"error_code": code})))
        return 21
    # Native runtime errors must not dump process diagnostics into the customer chat.
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or result.get("status") not in {"configured", "error", "cancelled"}:
            raise ValueError("invalid setup result")
    except (ValueError, TypeError):
        result = recovery_report({"error_code": "setup_launch_failed"})
        print(json.dumps(result, ensure_ascii=True))
        return 21
    if result["status"] == "error":
        result = recovery_report(result)
    print(json.dumps(result, ensure_ascii=True))
    if result["status"] == "error" and completed.returncode == 0:
        return 20
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
