from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Callable


MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
DANGEROUS_EXTENSIONS = {
    ".appref-ms", ".bat", ".cmd", ".com", ".cpl", ".exe", ".hta", ".img",
    ".inf", ".ins", ".iso", ".jar", ".js", ".jse", ".lnk", ".msc", ".msi",
    ".msp", ".mst", ".pif", ".ps1", ".psd1", ".psm1", ".reg", ".scr", ".sct",
    ".shb", ".sys", ".url", ".vb", ".vbe", ".vbs", ".ws", ".wsc", ".wsf",
    ".app", ".command", ".dmg", ".pkg", ".scpt", ".sh",
}
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class DownloadError(RuntimeError):
    pass


def safe_download_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", str(value)).strip().rstrip(". ")
    if not cleaned:
        cleaned = "attachment"
    stem = Path(cleaned).stem.casefold()
    if stem in WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > 160:
        suffix = Path(cleaned).suffix[:20]
        cleaned = cleaned[: max(1, 160 - len(suffix))].rstrip(". ") + suffix
    return cleaned


def is_potentially_executable(name: str) -> bool:
    return Path(name).suffix.casefold() in DANGEROUS_EXTENSIONS


def _defender_executable() -> Path | None:
    program_data = os.environ.get("ProgramData")
    if program_data:
        platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform.is_dir():
            candidates = sorted(platform.glob("*/MpCmdRun.exe"), reverse=True)
            if candidates:
                return candidates[0]
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidate = Path(program_files) / "Windows Defender" / "MpCmdRun.exe"
        if candidate.is_file():
            return candidate
    return None


def scan_with_windows_defender(path: Path) -> str:
    executable = _defender_executable()
    if executable is None:
        return "unavailable"
    try:
        result = subprocess.run(
            [str(executable), "-Scan", "-ScanType", "3", "-File", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if not path.exists():
        return "quarantined_or_removed"
    return "completed_no_detection_reported" if result.returncode == 0 else "attention_required"


def native_scan(path: Path) -> str:
    if os.name == "nt":
        return scan_with_windows_defender(path)
    return "unavailable"


def _apply_macos_quarantine(path: Path) -> bool:
    marker = f"0081;{int(time.time()):x};IMAP Plugin;"
    setxattr = getattr(os, "setxattr", None)
    if callable(setxattr):
        try:
            setxattr(path, "com.apple.quarantine", marker.encode("ascii"))
            return True
        except OSError:
            pass
    try:
        result = subprocess.run(
            ["/usr/bin/xattr", "-w", "com.apple.quarantine", marker, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _apply_required_platform_marker(path: Path) -> tuple[bool, bool, bool]:
    """Return Mark-of-the-Web, quarantine, and whether a marker is required."""
    if os.name == "nt":
        try:
            Path(str(path) + ":Zone.Identifier").write_text(
                "[ZoneTransfer]\r\nZoneId=3\r\n",
                encoding="ascii",
            )
        except OSError:
            return False, False, True
        return True, False, True
    if platform.system() == "Darwin":
        return False, _apply_macos_quarantine(path), True
    return False, False, False


def _discard_unmarked_download(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DownloadError(
            "download blocked because the operating-system safety marker failed; "
            "the incomplete file could not be removed"
        ) from exc
    raise DownloadError(
        "download blocked because the operating-system safety marker could not be applied"
    )


def save_attachment(
    name: str,
    content: bytes,
    *,
    root: Path | None = None,
    scanner: Callable[[Path], str] = native_scan,
) -> dict[str, object]:
    if not content:
        raise DownloadError("empty attachments are not downloaded")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise DownloadError("attachment exceeds the 25 MiB secure download ceiling")
    target_root = root or (Path.home() / "Downloads" / "IMAP Plugin")
    target_root.mkdir(parents=True, exist_ok=True)
    safe_name = safe_download_name(name)
    candidate = target_root / safe_name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = target_root / f"{stem} ({counter}){suffix}"
        counter += 1
        if counter > 10_000:
            raise DownloadError("could not allocate a unique download name")
    with candidate.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    motw_applied, quarantine_applied, marker_required = _apply_required_platform_marker(candidate)
    if marker_required and not (motw_applied or quarantine_applied):
        _discard_unmarked_download(candidate)
    scan_status = scanner(candidate)
    return {
        "download_path": str(candidate),
        "name": candidate.name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mark_of_the_web": motw_applied,
        "quarantine_marker": quarantine_applied,
        "scan_status": scan_status,
        "available_after_scan": candidate.exists(),
        "opened_or_executed": False,
    }
