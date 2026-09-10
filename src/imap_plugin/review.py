from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .windows_host import PowerShellUnavailable, powershell_command
from .setup_recovery import recovery_report


class ReviewError(RuntimeError):
    pass


class SetupError(ReviewError):
    def __init__(self, result: Any) -> None:
        self.report = recovery_report(result)
        super().__init__(self.report["message"])


Reviewer = Callable[[str, Mapping[str, Any], bool], bool]


_APPROVAL_KEY_RE = re.compile(r"(?:approval|confirm).*(?:handle|token|secret)|(?:handle|token|secret).*approval", re.IGNORECASE)


def _contains_approval_material(value: Any) -> bool:
    """Reject accidental export of the in-process approval capability."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).replace("-", "_")
            if _APPROVAL_KEY_RE.search(key_text):
                return True
            if _contains_approval_material(child):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_approval_material(child) for child in value)
    return False


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def native_review(title: str, payload: Mapping[str, Any], require_checkbox: bool = False) -> bool:
    if _contains_approval_material(payload):
        raise ReviewError("the native review payload cannot contain approval material")
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
    system = platform.system()
    if os.name == "nt":
        script = plugin_root() / "scripts" / "review.ps1"
        try:
            command = powershell_command(script)
        except PowerShellUnavailable as exc:
            raise ReviewError(str(exc)) from exc
    elif system == "Darwin":
        script = plugin_root() / "scripts" / "review_macos.py"
        command = [sys.executable, str(script)]
    else:
        raise ReviewError("native action review is available only on Windows and macOS")
    if not script.is_file():
        raise ReviewError("the native review component is missing")
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
        script = plugin_root() / "scripts" / "configure.py"
        command = [sys.executable, "-X", "utf8", str(script)]
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
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise SetupError({"error_code": "setup_timeout"}) from exc
    except OSError as exc:
        raise SetupError({"error_code": "permission_denied" if isinstance(exc, PermissionError) else "setup_launch_failed"}) from exc
    if completed.returncode not in {0, 2}:
        try:
            result = json.loads(completed.stdout)
        except ValueError:
            result = {"error_code": "setup_launch_failed"}
        raise SetupError(result)
    return completed.returncode == 0
