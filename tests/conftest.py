from __future__ import annotations

import email
import re
from email.message import EmailMessage
from email.policy import default

import pytest

from imap_plugin.bridge import MailBridge
from imap_plugin.config import Settings
from imap_plugin.trace import SafeTrace


def sample_message(subject: str = "Question?", body: str = "Please reply.", attachment: bool = False, html: bool = False) -> bytes:
    msg = EmailMessage()
    msg["Date"] = "Wed, 27 Aug 2026 09:00:00 +0200"
    msg["From"] = "Sender <sender@example.test>"
    msg["To"] = "Mailbox <mailbox@example.test>"
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{abs(hash(subject))}@example.test>"
    if html:
        msg.set_content("Fallback")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)
    if attachment:
        msg.add_attachment(b"abc", maintype="application", subtype="octet-stream", filename="invoice.bin")
    return msg.as_bytes(policy=default)


class FakeSocket:
    def getpeercert(self):
        return {
            "subject": ((("commonName", "imap.example.test"),),),
            "issuer": ((("commonName", "Fake Test CA"),),),
            "notAfter": "Aug 27 12:00:00 2027 GMT",
        }


class FakeIMAP:
    folders = {
        "INBOX": {"flags": ["\\Inbox"], "uidvalidity": 10},
        "Drafts": {"flags": ["\\Drafts"], "uidvalidity": 20},
        "Archive": {"flags": ["\\Archive"], "uidvalidity": 30},
    }

    def __init__(self, host, port, ssl_context, timeout):
        assert host == "imap.example.test"
        assert port == 993
        assert ssl_context.check_hostname
        assert timeout <= 15
        self.sock = FakeSocket()
        self._selected_folder = "INBOX"
        self.login_calls = 0
        self.full_body_fetches = 0
        self.partial_body_fetches = 0
        self.header_fetches = 0
        self.attachment_fetches = 0
        self.messages = {
            "INBOX": {
                101: {"raw": sample_message("Question?", "Please reply."), "flags": set()},
                102: {"raw": sample_message("Status", "<p>Hello</p><img src='https://tracker.test/x'>", html=True), "flags": {"\\Seen"}},
            },
            "Drafts": {},
            "Archive": {},
        }

    def login(self, username, secret):
        assert username == "user@example.test"
        assert secret == "unit-secret"
        self.login_calls += 1
        return "OK", [b"authenticated"]

    def logout(self):
        return "BYE", [b"done"]

    def capability(self):
        return "OK", [b"IMAP4rev1 IDLE SPECIAL-USE UIDPLUS MOVE"]

    def list(self):
        return "OK", [
            b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
            b'(\\HasNoChildren \\Drafts) "/" "Drafts"',
            b'(\\HasNoChildren \\Archive) "/" "Archive"',
        ]

    def status(self, folder, query):
        folder = folder[1:-1] if folder.startswith('"') and folder.endswith('"') else folder
        messages = self.messages[folder]
        uidnext = max(messages, default=0) + 1
        unseen = sum("\\Seen" not in value["flags"] for value in messages.values())
        uv = self.folders[folder]["uidvalidity"]
        return "OK", [f'"{folder}" (MESSAGES {len(messages)} UNSEEN {unseen} UIDVALIDITY {uv} UIDNEXT {uidnext})'.encode()]

    def select(self, folder, readonly=True):
        folder = folder[1:-1] if folder.startswith('"') and folder.endswith('"') else folder
        self._selected_folder = folder
        return "OK", [str(len(self.messages[folder])).encode()]

    def uid(self, command, *args):
        command = command.lower()
        folder = self._selected_folder
        if command == "search":
            return "OK", [" ".join(str(uid) for uid in sorted(self.messages[folder])).encode()]
        if command == "fetch":
            sequence, spec = args[0], args[1]
            if ":" in sequence or "," in sequence:
                if ":" in sequence:
                    start = int(sequence.split(":", 1)[0])
                    requested = [uid for uid in sorted(self.messages[folder]) if uid >= start]
                else:
                    requested = [int(value) for value in sequence.split(",") if value]
                payload = []
                for uid in requested:
                    item = self.messages[folder].get(uid)
                    if item is not None:
                        flags = " ".join(sorted(item["flags"]))
                        payload.append(f"* 1 FETCH (UID {uid} FLAGS ({flags}))".encode())
                return "OK", payload
            uid = int(sequence)
            item = self.messages[folder][uid]
            flags = " ".join(sorted(item["flags"]))
            if "BODYSTRUCTURE" in spec:
                parsed = email.message_from_bytes(item["raw"], policy=default)
                attachment = next((part for part in parsed.walk() if part.get_filename()), None)
                if attachment is None:
                    structure = '("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 13 1 NIL NIL NIL NIL)'
                else:
                    filename = attachment.get_filename()
                    media, subtype = attachment.get_content_type().split("/", 1)
                    size = len(attachment.get_payload(decode=True) or b"")
                    structure = (
                        '(("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 13 1 NIL NIL NIL NIL) '
                        f'("{media.upper()}" "{subtype.upper()}" ("NAME" "{filename}") NIL NIL "BASE64" {size} '
                        f'NIL ("ATTACHMENT" ("FILENAME" "{filename}")) NIL NIL) "MIXED" NIL NIL NIL)'
                    )
                return "OK", [f"* 1 FETCH (UID {uid} BODYSTRUCTURE {structure})".encode(), b")"]
            if "HEADER.FIELDS" in spec:
                self.header_fetches += 1
                msg = email.message_from_bytes(item["raw"], policy=default)
                headers = b"".join(
                    f"{key}: {msg.get(key)}\r\n".encode()
                    for key in ("Date", "From", "Subject", "Message-ID", "References", "In-Reply-To", "List-ID", "List-Unsubscribe", "Precedence", "Auto-Submitted")
                    if msg.get(key)
                ) + b"\r\n"
                meta = f"* 1 FETCH (UID {uid} FLAGS ({flags}) RFC822.SIZE {len(item['raw'])})".encode()
                response = [(meta, headers)]
                preview_match = re.search(r"BODY\.PEEK\[\]<0\.(\d+)>", spec)
                if preview_match:
                    self.partial_body_fetches += 1
                    limit = int(preview_match.group(1))
                    preview = item["raw"][:limit]
                    response.append((f"* 1 FETCH (UID {uid} BODY[]<0> {{{len(preview)}}})".encode(), preview))
                response.append(b")")
                return "OK", response
            attachment_match = re.search(r"BODY\.PEEK\[([0-9.]+)\]<0\.(\d+)>", spec)
            if attachment_match:
                self.attachment_fetches += 1
                parsed = email.message_from_bytes(item["raw"], policy=default)
                leaves = [part for part in parsed.walk() if not part.is_multipart()]
                top_level = int(attachment_match.group(1).split(".", 1)[0])
                source_payload = leaves[top_level - 1].get_payload(decode=False)
                payload = source_payload.encode("ascii") if isinstance(source_payload, str) else bytes(source_payload or b"")
                limit = int(attachment_match.group(2))
                payload = payload[:limit]
                return "OK", [(f"* 1 FETCH (UID {uid} BODY[{attachment_match.group(1)}]<0> {{{len(payload)}}})".encode(), payload), b")"]
            if "BODY.PEEK[]" in spec:
                self.full_body_fetches += 1
                return "OK", [(f"* 1 FETCH (UID {uid})".encode(), item["raw"]), b")"]
            return "OK", [f"* 1 FETCH (UID {uid} FLAGS ({flags}))".encode()]
        if command == "store":
            uid, operation, flag_blob = int(args[0]), args[1], args[2]
            flag = flag_blob.strip("()")
            if operation.startswith("+"):
                self.messages[folder][uid]["flags"].add(flag)
            else:
                self.messages[folder][uid]["flags"].discard(flag)
            return "OK", [b"stored"]
        if command == "expunge":
            uid = int(args[0])
            if "\\Deleted" in self.messages[folder][uid]["flags"]:
                del self.messages[folder][uid]
            return "OK", [b"expunged"]
        raise AssertionError(command)

    def append(self, folder, flags, internaldate, raw):
        folder = folder[1:-1] if folder.startswith('"') and folder.endswith('"') else folder
        uid = max(self.messages[folder], default=500) + 1
        self.messages[folder][uid] = {"raw": raw, "flags": {"\\Draft"}}
        return "OK", [f"[APPENDUID {self.folders[folder]['uidvalidity']} {uid}] done".encode()]

    def expunge(self):
        folder = self._selected_folder
        for uid in list(self.messages[folder]):
            if "\\Deleted" in self.messages[folder][uid]["flags"]:
                del self.messages[folder][uid]
        return "OK", [b"expunged"]


@pytest.fixture
def settings():
    return Settings(username="user@example.test", host="imap.example.test")


@pytest.fixture
def fake_factory():
    instances = []
    def factory(*args, **kwargs):
        if not instances:
            instances.append(FakeIMAP(*args, **kwargs))
        return instances[0]
    factory.instances = instances
    return factory


@pytest.fixture
def bridge(settings, fake_factory, tmp_path):
    trace = SafeTrace("read", root=tmp_path / "logs")
    return MailBridge(settings, "read", fake_factory, lambda _: "unit-secret", trace)
