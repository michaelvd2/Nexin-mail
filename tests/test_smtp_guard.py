from email.message import EmailMessage
import smtplib
import socketserver
import threading

import pytest

from imap_plugin.smtp_guard import SmtpGuardError, TestOnlySmtpGuard


class FakeSMTP:
    sent = []
    def __init__(self, host, port, timeout):
        assert host == "127.0.0.1"
        self.host = host
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def send_message(self, message, to_addrs):
        self.sent.append((str(message["Message-ID"]), tuple(to_addrs)))


def message(to="allowed@example.test"):
    msg = EmailMessage()
    msg["From"] = "sender@example.test"
    msg["To"] = to
    msg["Subject"] = "Test"
    msg.set_content("body")
    return msg


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    return TestOnlySmtpGuard("127.0.0.1", 2525, {"allowed@example.test"}, FakeSMTP, max_per_minute=2)


def test_disabled_without_test_mode(monkeypatch):
    monkeypatch.delenv("IMAP_PLUGIN_TEST_MODE", raising=False)
    with pytest.raises(SmtpGuardError):
        TestOnlySmtpGuard("127.0.0.1", 2525, set(), FakeSMTP)


def test_rejects_non_loopback(monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    with pytest.raises(SmtpGuardError):
        TestOnlySmtpGuard("192.0.2.10", 25, set(), FakeSMTP)


def test_confirmation_allowlist_and_message_id(guard):
    with pytest.raises(SmtpGuardError):
        guard.send(message(), False, "a")
    result = guard.send(message(), True, "a")
    assert result.endswith("@imap-plugin.test>")


def test_idempotency_retry_suppression(guard):
    guard.send(message(), True, "same")
    with pytest.raises(SmtpGuardError):
        guard.send(message(), True, "same")


def test_recipient_allowlist(guard):
    with pytest.raises(SmtpGuardError):
        guard.send(message("outside@example.test"), True, "x")


def test_bcc_rejected(guard):
    msg = message()
    msg["Bcc"] = "allowed@example.test"
    with pytest.raises(SmtpGuardError):
        guard.send(msg, True, "x")


def test_rate_limit(guard):
    guard.send(message(), True, "1")
    guard.send(message(), True, "2")
    with pytest.raises(SmtpGuardError):
        guard.send(message(), True, "3")


def test_header_injection_rejected_by_email_library(guard):
    msg = message()
    with pytest.raises(ValueError):
        msg["X-Test"] = "ok\r\nBcc: surprise@example.test"


def test_real_loopback_fake_smtp_protocol(monkeypatch):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 fake.local ESMTP\r\n")
            self.wfile.flush()
            in_data = False
            content = []
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                if in_data:
                    if line == b".\r\n":
                        self.server.messages.append(b"".join(content))
                        self.wfile.write(b"250 queued\r\n")
                        self.wfile.flush()
                        in_data = False
                        content = []
                    else:
                        content.append(line)
                    continue
                command = line.split(None, 1)[0].upper()
                if command in {b"EHLO", b"HELO"}:
                    self.wfile.write(b"250-fake.local\r\n250 SIZE 100000\r\n")
                elif command in {b"MAIL", b"RCPT", b"RSET", b"NOOP"}:
                    self.wfile.write(b"250 ok\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 end with dot\r\n")
                    in_data = True
                elif command == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    self.wfile.flush()
                    return
                else:
                    self.wfile.write(b"502 unsupported\r\n")
                self.wfile.flush()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    server = Server(("127.0.0.1", 0), Handler)
    server.messages = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
        guard = TestOnlySmtpGuard("127.0.0.1", server.server_address[1], {"allowed@example.test"}, smtplib.SMTP)
        guard.send(message(), True, "socket-test")
        assert len(server.messages) == 1
        assert b"Message-ID:" in server.messages[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
