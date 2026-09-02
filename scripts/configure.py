from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
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
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
