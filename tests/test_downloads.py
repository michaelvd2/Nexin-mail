from __future__ import annotations

from types import SimpleNamespace

from imap_plugin import downloads
import pytest

from imap_plugin.downloads import DownloadError, is_potentially_executable, safe_download_name, save_attachment


def test_download_name_blocks_traversal_reserved_names_and_control_characters():
    assert safe_download_name("..\\..\\CON.exe") == ".._.._CON.exe"
    assert safe_download_name("report\x00.pdf") == "report_.pdf"
    assert "/" not in safe_download_name("folder/file.txt")


def test_attachment_is_written_once_without_opening_or_execution(tmp_path):
    result = save_attachment(
        "invoice.pdf",
        b"unit-pdf",
        root=tmp_path,
        scanner=lambda path: "completed_no_detection_reported",
    )
    assert (tmp_path / "invoice.pdf").read_bytes() == b"unit-pdf"
    assert result["opened_or_executed"] is False
    assert result["scan_status"] == "completed_no_detection_reported"
    assert result["available_after_scan"] is True


def test_potentially_executable_extensions_are_flagged():
    assert is_potentially_executable("setup.EXE") is True
    assert is_potentially_executable("document.pdf") is False


def test_macos_quarantine_falls_back_to_xattr_command(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(downloads.os, "setxattr", None, raising=False)

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(downloads.subprocess, "run", fake_run)
    attachment = tmp_path / "invoice.pdf"
    attachment.write_bytes(b"unit-pdf")

    assert downloads._apply_macos_quarantine(attachment) is True
    assert len(calls) == 1
    assert calls[0][:3] == ["/usr/bin/xattr", "-w", "com.apple.quarantine"]
    assert calls[0][3].startswith("0081;")
    assert calls[0][4] == str(attachment)


def test_attachment_is_removed_when_required_platform_marker_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "_apply_required_platform_marker", lambda _path: (False, False, True))

    with pytest.raises(DownloadError, match="safety marker"):
        save_attachment("dangerous.exe", b"unit-binary", root=tmp_path, scanner=lambda _path: "unused")

    assert list(tmp_path.iterdir()) == []


def test_attachment_remains_available_when_required_marker_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "_apply_required_platform_marker", lambda _path: (True, False, True))

    result = save_attachment(
        "reviewed.pdf",
        b"unit-pdf",
        root=tmp_path,
        scanner=lambda _path: "completed_no_detection_reported",
    )

    assert result["mark_of_the_web"] is True
    assert (tmp_path / "reviewed.pdf").read_bytes() == b"unit-pdf"
