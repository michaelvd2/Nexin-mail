from __future__ import annotations

import copy
import ssl

import pytest

from conftest import FakeIMAP
from imap_plugin.bridge import MailBridge, MailError
from imap_plugin.config import Settings, load_settings
from imap_plugin.trace import SafeTrace


def local_bridge(settings, client_or_factory, tmp_path):
    factory = client_or_factory if callable(client_or_factory) and not isinstance(client_or_factory, FakeIMAP) else (lambda *a, **k: client_or_factory)
    return MailBridge(settings, "read", factory, lambda _: "unit-secret", SafeTrace("read", root=tmp_path / "logs"))


def test_duplicate_uid_search_results_are_suppressed(settings, tmp_path):
    class DuplicateIMAP(FakeIMAP):
        def uid(self, command, *args):
            if command.lower() == "search":
                return "OK", [b"101 101 102 102"]
            return super().uid(command, *args)
    client = DuplicateIMAP(settings.host, settings.port, ssl.create_default_context(), 15)
    items = local_bridge(settings, client, tmp_path).list_message_headers("INBOX", "2026-08-01", "2026-08-28", 10)
    assert [item["uid"] for item in items] == [101, 102]


def test_connection_budget_is_one_per_operation(settings, tmp_path):
    calls = 0
    def factory(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeIMAP(*args, **kwargs)
    local_bridge(settings, factory, tmp_path).list_mailboxes()
    assert calls == 1


def test_timeout_has_no_hidden_retry(settings, tmp_path):
    calls = 0
    def factory(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("fake timeout")
    with pytest.raises(TimeoutError):
        local_bridge(settings, factory, tmp_path).list_mailboxes()
    assert calls == 1


def test_idle_notify_fallback_is_polling_safe(settings, tmp_path):
    class PlainIMAP(FakeIMAP):
        def capability(self):
            return "OK", [b"IMAP4rev1 SPECIAL-USE"]
    client = PlainIMAP(settings.host, settings.port, ssl.create_default_context(), 15)
    result = local_bridge(settings, client, tmp_path).tls_and_capabilities()
    assert result["idle"] is False
    assert result["notify"] is False


def test_uidvalidity_change_is_visible_in_baseline(settings, tmp_path):
    client = FakeIMAP(settings.host, settings.port, ssl.create_default_context(), 15)
    client.folders = copy.deepcopy(client.folders)
    bridge = local_bridge(settings, client, tmp_path)
    before = bridge.baseline()
    client.folders["INBOX"]["uidvalidity"] += 1
    after = bridge.baseline()
    assert before != after


def test_partial_fetch_response_fails_closed(settings, tmp_path):
    class PartialIMAP(FakeIMAP):
        def uid(self, command, *args):
            if command.lower() == "fetch" and "BODY.PEEK[]" in args[1]:
                return "NO", [b"partial"]
            return super().uid(command, *args)
    client = PartialIMAP(settings.host, settings.port, ssl.create_default_context(), 15)
    with pytest.raises(MailError):
        local_bridge(settings, client, tmp_path).get_message("INBOX", 101)


def test_plaintext_secret_config_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('username="x"\npassword="forbidden"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path)
