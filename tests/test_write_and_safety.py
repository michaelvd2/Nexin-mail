from pathlib import Path

import pytest

from imap_plugin.bridge import MailBridge, MailError
from imap_plugin.trace import SafeTrace


def make_write(settings, fake_factory, tmp_path):
    return MailBridge(settings, "write", fake_factory, lambda _: "unit-secret", SafeTrace("write", root=tmp_path / "logs"))


def test_read_process_rejects_write(bridge):
    with pytest.raises(MailError):
        bridge.set_seen("INBOX", 101, True)


def test_seen_transition_returns_prior_and_result(settings, fake_factory, tmp_path):
    bridge = make_write(settings, fake_factory, tmp_path)
    result = bridge.set_seen("INBOX", 101, True)
    assert "\\Seen" not in result["previous_flags"]
    assert "\\Seen" in result["resulting_flags"]


def test_flagged_transition(settings, fake_factory, tmp_path):
    bridge = make_write(settings, fake_factory, tmp_path)
    result = bridge.set_flagged("INBOX", 101, True)
    assert "\\Flagged" in result["resulting_flags"]


def test_draft_uses_special_use_and_not_smtp(settings, fake_factory, tmp_path):
    bridge = make_write(settings, fake_factory, tmp_path)
    result = bridge.save_draft("recipient@example.test", "Reply", "Proposed reply")
    assert result["folder"] == "Drafts"
    assert result["message_id"].endswith("@imap-plugin.invalid>")


def test_multiline_draft_body_is_allowed(settings, fake_factory, tmp_path):
    bridge = make_write(settings, fake_factory, tmp_path)
    result = bridge.save_draft("recipient@example.test", "Reply", "Line one\n\nLine two")
    assert result["folder"] == "Drafts"


def test_production_bridge_has_no_permanent_cleanup_path(settings, fake_factory, tmp_path):
    bridge = make_write(settings, fake_factory, tmp_path)
    assert not hasattr(bridge, "acceptance_cleanup_draft")


def test_no_hidden_timer_watcher_or_service_path():
    root = Path(__file__).parents[1] / "src" / "imap_plugin"
    production = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py") if path.name != "smtp_guard.py")
    forbidden = ("threading.Timer", "watchdog", "schedule.every", "CreateService", "SMTP(")
    assert not any(value in production for value in forbidden)


def test_cli_scheduled_path_forces_read_profile_without_being_exposed_as_a_plugin_tool():
    root = Path(__file__).parents[1]
    cli = (root / "src" / "imap_plugin" / "cli.py").read_text(encoding="utf-8")
    server = (root / "src" / "imap_plugin" / "server.py").read_text(encoding="utf-8")
    assert 'os.environ["IMAP_PLUGIN_PROFILE"] = "read"' in cli
    assert "scheduled_check" not in server
