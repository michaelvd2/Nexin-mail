from datetime import datetime, timezone
from pathlib import Path

import pytest

from imap_plugin.bridge import BoundError, MailBridge, SizeLimitError, _decode_modified_utf7, _encode_modified_utf7
from imap_plugin.config import Settings
from imap_plugin.contracts import MessageRef
from imap_plugin.trace import SafeTrace


def test_tls_and_authenticated_capability(bridge):
    result = bridge.tls_and_capabilities()
    assert result["tls"]["verified"] is True
    assert result["tls"]["hostname_checked"] is True
    assert result["idle"] is True
    assert result["notify"] is False


def test_mandatory_starttls_is_supported(settings, fake_factory, tmp_path):
    starttls_calls = []

    def factory(host, port, timeout):
        assert host == "imap.example.test"
        assert port == 143
        client = fake_factory(
            "imap.example.test",
            993,
            ssl_context=__import__("ssl").create_default_context(),
            timeout=timeout,
        )

        def starttls(*, ssl_context):
            assert ssl_context.check_hostname
            starttls_calls.append(True)
            return "OK", [b"TLS active"]

        client.starttls = starttls
        return client

    starttls_settings = Settings(
        username=settings.username,
        host=settings.host,
        port=143,
        imap_security="starttls",
    )
    trace = SafeTrace("read", root=tmp_path / "logs")
    local = MailBridge(starttls_settings, "read", factory, lambda _: "unit-secret", trace)

    result = local.tls_and_capabilities()

    assert starttls_calls == [True]
    assert result["tls"]["verified"] is True


def test_list_mailboxes_special_use_and_uid_metadata(bridge):
    boxes = bridge.list_mailboxes()
    assert {box["name"] for box in boxes} == {"INBOX", "Drafts", "Archive"}
    assert next(box for box in boxes if box["name"] == "Drafts")["uidvalidity"] == 20


def test_bounded_headers(bridge):
    items = bridge.list_message_headers("INBOX", "2026-08-01", "2026-08-28", 2)
    assert [item["uid"] for item in items] == [101, 102]
    assert items[0]["preview"] == "Please reply."


def test_list_previews_are_bounded_and_do_not_fetch_full_messages(bridge, fake_factory):
    items = bridge.list_messages("INBOX", "2026-08-01", "2026-08-28", 2)
    client = fake_factory.instances[0]
    assert items[1]["preview"] == "Fallback"
    assert "https://tracker.test" not in repr(items)
    assert client.partial_body_fetches == 2
    assert client.full_body_fetches == 0

def test_incremental_uid_sync_reuses_headers_and_fetches_only_new_messages(bridge, fake_factory):
    from conftest import sample_message

    first = bridge.list_messages("INBOX", "2026-08-01", "2026-08-28", 20)
    client = fake_factory.instances[0]
    assert [item["uid"] for item in first] == [101, 102]
    assert client.header_fetches == 2

    client.messages["INBOX"][101]["flags"].add("\\Seen")
    second = bridge.list_messages("INBOX", "2026-08-01", "2026-08-28", 20)
    assert client.header_fetches == 2
    assert "\\Seen" in second[0]["flags"]
    assert bridge.last_sync_status["mode"] == "unchanged"
    assert bridge.last_sync_status["reused_headers"] == 2

    client.messages["INBOX"][103] = {
        "raw": sample_message("New", "Only this new message is fetched."),
        "flags": set(),
    }
    third = bridge.list_messages("INBOX", "2026-08-01", "2026-08-28", 20)
    assert [item["uid"] for item in third] == [101, 102, 103]
    assert client.header_fetches == 3
    assert bridge.last_sync_status["mode"] == "incremental"
    assert bridge.last_sync_status["fetched_headers"] == 1
    assert bridge.last_sync_status["reused_headers"] == 2

    client.folders["INBOX"]["uidvalidity"] += 1
    bridge.list_messages("INBOX", "2026-08-01", "2026-08-28", 20)
    assert client.header_fetches == 6
    assert bridge.last_sync_status["mode"] == "full"


def test_search_requires_date_plus_constraint(bridge):
    with pytest.raises(BoundError):
        bridge.search_messages("INBOX", "2026-08-01", "2026-08-28")
    assert bridge.search_messages("INBOX", "2026-08-01", "2026-08-28", subject="Question", limit=1)


def test_search_rejects_injection(bridge):
    with pytest.raises(BoundError):
        bridge.search_messages("INBOX", "2026-08-01", "2026-08-28", text="x\r\nUID STORE 1")


def test_date_window_is_bounded(bridge):
    with pytest.raises(BoundError):
        bridge.list_message_headers("INBOX", "2026-01-01", "2026-08-28")


def test_get_one_message_is_untrusted_and_no_remote_fetch(bridge):
    item = bridge.get_message("INBOX", 101)
    assert item["uid"] == 101
    assert item["untrusted_content"] is True
    assert item["remote_content_fetched"] is False


def test_html_message_returns_safe_formatted_tree(bridge):
    item = bridge.get_message("INBOX", 102)
    assert item["formatted_body"][0]["tag"] == "p"
    assert "https://tracker.test" not in repr(item["formatted_body"])


def test_advertising_header_is_classified_without_moving_mail(bridge, fake_factory):
    fake_factory.instances.clear()
    client = fake_factory("imap.example.test", 993, ssl_context=__import__("ssl").create_default_context(), timeout=15)
    from email.message import EmailMessage
    message = EmailMessage()
    message["Date"] = "Wed, 27 Aug 2026 09:00:00 +0200"
    message["From"] = "Offers <promo@shop.example>"
    message["To"] = "Mailbox <mailbox@example.test>"
    message["Subject"] = "Newsletter with 30% off"
    message["Message-ID"] = "<promo@example.test>"
    message["List-ID"] = "shop.example"
    message["List-Unsubscribe"] = "<https://shop.example/unsubscribe>"
    message.set_content("Offer")
    client.messages["INBOX"][101]["raw"] = message.as_bytes()
    local = MailBridge(bridge.settings, "read", lambda *args, **kwargs: client, lambda _: "unit-secret", bridge.trace)
    header = local.list_message_headers("INBOX", "2026-08-01", "2026-08-28", 2)[0]
    assert header["category"] == "advertising"
    assert "mailing_list_header" in header["classification_reasons"]
    assert 101 in client.messages["INBOX"]


def test_attachment_metadata_without_bytes(bridge, fake_factory):
    fake_factory.instances.clear()
    client = fake_factory("imap.example.test", 993, ssl_context=__import__("ssl").create_default_context(), timeout=15)
    from conftest import sample_message
    client.messages["INBOX"][101]["raw"] = sample_message(attachment=True)
    factory = lambda *args, **kwargs: client
    local = MailBridge(bridge.settings, "read", factory, lambda _: "unit-secret", bridge.trace)
    metadata = local.get_attachment_metadata("INBOX", 101)
    assert metadata == [{"part_id": "2", "name": "invoice.bin", "mime_type": "application/octet-stream", "size": 3, "transfer_encoding": "base64"}]
    assert "content" not in metadata[0]
    assert client.full_body_fetches == 0
    reference = local.resolve_message_reference("INBOX", 101)["message_ref"]
    content = local.fetch_attachment_bytes(MessageRef.from_mapping(reference), "2", transfer_encoding="base64")
    assert content == b"abc"
    assert client.attachment_fetches == 1


def test_actionables_have_local_citations(bridge):
    items = bridge.find_actionables("INBOX", "2026-08-01", "2026-08-28", 2)
    assert items[0]["citation"]["folder"] == "INBOX"
    assert isinstance(items[0]["citation"]["uid"], int)


def test_oversize_fails_without_temp_file(settings, fake_factory, tmp_path):
    from conftest import sample_message
    client = fake_factory("imap.example.test", 993, ssl_context=__import__("ssl").create_default_context(), timeout=15)
    client.messages["INBOX"][101]["raw"] = sample_message(body="X" * 20000)
    small = Settings(username=settings.username, host=settings.host, max_message_bytes=16384)
    trace = SafeTrace("read", root=tmp_path / "logs")
    local = MailBridge(small, "read", lambda *a, **k: client, lambda _: "unit-secret", trace)
    before = {p for p in tmp_path.rglob("*")}
    with pytest.raises(SizeLimitError):
        local.get_message("INBOX", 101)
    after = {p for p in tmp_path.rglob("*")}
    assert after - before <= {tmp_path / "logs" / "bridge.jsonl"}


def test_baseline_contains_no_folder_names(bridge):
    result = bridge.baseline()
    rendered = repr(result)
    assert "INBOX" not in rendered and "Drafts" not in rendered


def test_generic_unicode_mailbox_names_round_trip_modified_utf7():
    name = "Projecten & facturen 📬"
    encoded = _encode_modified_utf7(name)
    assert encoded.isascii()
    assert _decode_modified_utf7(encoded.encode("ascii")) == name
