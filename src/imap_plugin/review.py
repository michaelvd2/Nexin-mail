from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


class ReviewError(RuntimeError):
    pass


Reviewer = Callable[[str, Mapping[str, Any], bool], bool]


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def native_review(title: str, payload: Mapping[str, Any], require_checkbox: bool = False) -> bool:
    system = platform.system()
    if os.name == "nt":
        script = plugin_root() / "scripts" / "review.ps1"
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-STA", "-File", str(script)]
    elif system == "Darwin":
        script = plugin_root() / "scripts" / "review_macos.py"
        command = [sys.executable, str(script)]
    else:
        raise ReviewError("native action review is available only on Windows and macOS")
    if not script.is_file():
        raise ReviewError("the native review component is missing")
    request = json.dumps(
        {
            "version": 1,
            "title": str(title)[:160],
            "require_checkbox": bool(require_checkbox),
            "payload": payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(request.encode("utf-8")) > 1_500_000:
        raise ReviewError("the review payload exceeds the local display limit")
    try:
        completed = subprocess.run(
            command,
            input=request,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=315,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReviewError("the local review expired; nothing was changed") from exc
    except OSError as exc:
        raise ReviewError("the local review could not start") from exc
    decision = completed.stdout.strip()
    if completed.returncode == 0 and decision == "CONFIRMED":
        return True
    if completed.returncode in {1, 2} and decision in {"", "CANCELLED"}:
        return False
    raise ReviewError("the local review failed closed; nothing was changed")


def launch_setup() -> bool:
    system = platform.system()
    if os.name == "nt":
        script = plugin_root() / "scripts" / "enroll_gui.ps1"
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-STA", "-File", str(script)]
    elif system == "Darwin":
        script = plugin_root() / "scripts" / "setup_macos.py"
        command = [sys.executable, str(script)]
    else:
        raise ReviewError("secure setup is available only on Windows and macOS")
    if not script.is_file():
        raise ReviewError("the secure setup component is missing")
    try:
        completed = subprocess.run(
            command,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReviewError("mailbox setup expired without completing") from exc
    except OSError as exc:
        raise ReviewError("the secure setup form could not start") from exc
    return completed.returncode == 0
