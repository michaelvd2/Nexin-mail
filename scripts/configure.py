from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-STA", "-File", str(ROOT / "scripts" / "enroll_gui.ps1")]
    elif platform.system() == "Darwin":
        command = [sys.executable, str(ROOT / "scripts" / "setup_macos.py")]
    else:
        raise RuntimeError("IMAP Plugin secure enrollment is available only on Windows and macOS")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        env=environment,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
