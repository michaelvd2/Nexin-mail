from __future__ import annotations

import pytest

from imap_plugin.config import AccountConfig
from imap_plugin.sender import MailSender, SendError, build_message, parse_recipients


class PartialRefusalTransport:
    def __init__(self):
        self.send_calls = 0
        self.login_calls = 0

    def login(self, username, secret):
        self.login_calls += 1

    def send_message(self, message, from_addr, to_addrs):
        self.send_calls += 1
        return {"second@example.test": (550, b"rejected")}

    def quit(self):
        return None


def test_partial_recipient_refusal_is_ambiguous_and_never_retried():
    settings = AccountConfig(
        username="sender@example.test",
        host="imap.example.test",
        smtp_host="smtp.example.test",
        smtp_port=465,
    )
    transport = PartialRefusalTransport()
    sender = MailSender(settings, lambda target: "secret", lambda settings, context: transport)
    message = build_message(
        from_address="sender@example.test",
        to=("first@example.test", "second@example.test"),
        cc=(),
        subject="Reviewed",
        body="Reviewed body",
        message_id="<reviewed@example.test>",
    )
    with pytest.raises(SendError) as error:
        sender.send_once(message)
    assert error.value.ambiguous is True
    assert transport.send_calls == 1


def test_recipient_header_injection_is_rejected_before_parsing():
    with pytest.raises(SendError, match="single-line"):
        parse_recipients("victim@example.test\r\nBcc: attacker@example.test")
