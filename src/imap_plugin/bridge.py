from __future__ import annotations

import email
import base64
import binascii
import hashlib
import imaplib
import re
import quopri
import ssl
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default
from email.utils import make_msgid, parsedate_to_datetime
from typing import Any, Callable, Iterator

from .config import AccountConfig, Settings
from .contracts import ContextBundle, ContextSource, MessageRef
from .credentials import platform_store
from .mime import decode_value, decoded_body, decoded_text, security_signals
from .trace import SafeTrace, hash_folder


class MailError(RuntimeError):
    pass


class MailAuthenticationError(MailError):
    pass


class MailTlsError(MailError):
    pass


class MailLoginDisabledError(MailError):
    pass


class SizeLimitError(MailError):
    pass


class BoundError(MailError):
    pass


class CapabilityError(MailError):
    pass


LIST_RE = re.compile(rb"^\((?P<flags>[^)]*)\)\s+(?P<delim>\S+|NIL)\s+(?P<name>.+)$")
UID_RE = re.compile(rb"\bUID\s+(\d+)\b", re.I)
SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)", re.I)
FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)", re.I)
ADVERTISING_RE = re.compile(
    r"(?i)\b(reclame|advertentie|aanbieding|actie|korting|sale|deal|promo(?:tie)?|"
    r"nieuwsbrief|newsletter|marketing|shop|uitverkoop|voordeel)\b"
)
TRANSACTIONAL_RE = re.compile(
    r"(?i)\b(bestelling|order|factuur|invoice|betaling|payment|receipt|ontvangst|"
    r"wachtwoord|password|beveiliging|security|afspraak|booking|reservering)\b"
)
LIST_PREVIEW_BYTES = 12_288
LIST_PREVIEW_CHARS = 180


def _clean_text(value: str, field: str, limit: int = 320) -> str:
    if "\r" in value or "\n" in value or "\x00" in value:
        raise BoundError(f"{field} contains forbidden control characters")
    if len(value) > limit:
        raise BoundError(f"{field} exceeds {limit} characters")
    return value


def _clean_body(value: str, limit: int) -> str:
    if "\x00" in value:
        raise BoundError("body contains a forbidden null character")
    if len(value.encode("utf-8")) > limit:
        raise BoundError(f"body exceeds {limit} UTF-8 bytes")
    return value


def _date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BoundError("dates must be ISO YYYY-MM-DD") from exc


def _extract_bytes(data: Any) -> list[bytes]:
    found: list[bytes] = []
    if isinstance(data, bytes):
        found.append(data)
    elif isinstance(data, tuple):
        for item in data:
            found.extend(_extract_bytes(item))
    elif isinstance(data, list):
        for item in data:
            found.extend(_extract_bytes(item))
    return found


def _extract_literal(data: Any) -> bytes:
    if isinstance(data, tuple) and len(data) >= 2 and isinstance(data[1], bytes):
        return data[1]
    if isinstance(data, list):
        for item in data:
            literal = _extract_literal(item)
            if literal:
                return literal
    return b""


def _extract_literals(data: Any) -> list[bytes]:
    if isinstance(data, tuple) and len(data) >= 2 and isinstance(data[1], bytes):
        return [data[1]]
    if isinstance(data, (list, tuple)):
        literals: list[bytes] = []
        for item in data:
            literals.extend(_extract_literals(item))
        return literals
    return []


def _message_preview(raw: bytes) -> str:
    if not raw:
        return ""
    message = email.message_from_bytes(raw, policy=default)
    value, oversized = decoded_text(message, LIST_PREVIEW_BYTES * 4)
    if oversized or not value:
        return ""
    value = " ".join(value.split())
    if len(value) <= LIST_PREVIEW_CHARS:
        return value
    return value[: LIST_PREVIEW_CHARS - 1].rstrip() + "…"


def _imap_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _quote_mailbox(value: str) -> str:
    encoded = _encode_modified_utf7(value)
    return '"' + encoded.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _encode_modified_utf7(value: str) -> str:
    output: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        raw = "".join(pending).encode("utf-16-be")
        token = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        output.append("&" + token + "-")
        pending.clear()

    for char in value:
        if " " <= char <= "~":
            flush()
            output.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush()
    return "".join(output)


def _decode_modified_utf7(value: bytes) -> str:
    try:
        source = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MailError("mailbox name is not valid IMAP modified UTF-7") from exc
    output: list[str] = []
    index = 0
    while index < len(source):
        if source[index] != "&":
            output.append(source[index])
            index += 1
            continue
        end = source.find("-", index)
        if end < 0:
            raise MailError("mailbox name has invalid IMAP modified UTF-7")
        token = source[index + 1:end]
        if not token:
            output.append("&")
        else:
            encoded = token.replace(",", "/")
            encoded += "=" * ((4 - len(encoded) % 4) % 4)
            try:
                output.append(base64.b64decode(encoded, validate=True).decode("utf-16-be"))
            except (ValueError, UnicodeError) as exc:
                raise MailError("mailbox name has invalid IMAP modified UTF-7") from exc
        index = end + 1
    return "".join(output)


def _parse_bodystructure(raw: bytes) -> Any:
    if len(raw) > 262_144:
        raise SizeLimitError("BODYSTRUCTURE response exceeds the metadata ceiling")
    match = re.search(rb"\bBODYSTRUCTURE\s+", raw, re.I)
    if not match:
        raise MailError("BODYSTRUCTURE metadata is unavailable")
    source = raw.decode("latin-1")
    position = match.end()
    nodes = 0

    def skip() -> None:
        nonlocal position
        while position < len(source) and source[position].isspace():
            position += 1

    def parse(depth: int = 0) -> Any:
        nonlocal position, nodes
        if depth > 40 or nodes > 10_000:
            raise MailError("BODYSTRUCTURE is too deeply nested")
        nodes += 1
        skip()
        if position >= len(source):
            raise MailError("BODYSTRUCTURE ended unexpectedly")
        if source[position] == "(":
            position += 1
            result = []
            while True:
                skip()
                if position >= len(source):
                    raise MailError("BODYSTRUCTURE has an unclosed list")
                if source[position] == ")":
                    position += 1
                    return result
                result.append(parse(depth + 1))
        if source[position] == '"':
            position += 1
            chars: list[str] = []
            while position < len(source):
                char = source[position]
                position += 1
                if char == '"':
                    return "".join(chars)
                if char == "\\":
                    if position >= len(source):
                        raise MailError("BODYSTRUCTURE has an invalid quoted string")
                    chars.append(source[position])
                    position += 1
                else:
                    chars.append(char)
            raise MailError("BODYSTRUCTURE has an unclosed quoted string")
        start = position
        while position < len(source) and not source[position].isspace() and source[position] not in "()":
            position += 1
        atom = source[start:position]
        if not atom:
            raise MailError("BODYSTRUCTURE contains an invalid atom")
        if atom.casefold() == "nil":
            return None
        return int(atom) if atom.isdigit() else atom

    return parse()


def _bodystructure_attachments(structure: Any) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []

    def parameters(value: Any) -> dict[str, str]:
        if not isinstance(value, list):
            return {}
        result: dict[str, str] = {}
        for index in range(0, len(value) - 1, 2):
            key, item = value[index], value[index + 1]
            if isinstance(key, str) and isinstance(item, str):
                result[key.casefold()] = item
        return result

    def disposition(value: Any) -> tuple[str, dict[str, str]] | None:
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], str)
            and value[0].casefold() in {"attachment", "inline"}
        ):
            return value[0].casefold(), parameters(value[1] if len(value) > 1 else None)
        if isinstance(value, list):
            for item in value:
                found = disposition(item)
                if found:
                    return found
        return None

    def visit(node: Any, part_id: str = "1", depth: int = 0) -> None:
        if depth > 40 or not isinstance(node, list) or not node:
            return
        if isinstance(node[0], list):
            child_number = 0
            for child in node:
                if isinstance(child, list):
                    child_number += 1
                    child_part = f"{part_id}.{child_number}" if part_id else str(child_number)
                    visit(child, child_part, depth + 1)
                else:
                    break
            return
        if len(node) < 7 or not isinstance(node[0], str) or not isinstance(node[1], str):
            return
        media_type = f"{node[0].casefold()}/{node[1].casefold()}"
        body_parameters = parameters(node[2])
        found_disposition = disposition(node[7:])
        disposition_name = found_disposition[0] if found_disposition else ""
        disposition_parameters = found_disposition[1] if found_disposition else {}
        filename = disposition_parameters.get("filename") or body_parameters.get("name")
        if disposition_name == "attachment" or filename:
            decoded_name = decode_value(filename or "unnamed attachment")[:255]
            safe_name = "".join(char if ord(char) >= 32 and ord(char) != 127 else "�" for char in decoded_name)
            size = node[6] if isinstance(node[6], int) else None
            transfer_encoding = str(node[5]).casefold()[:32] if isinstance(node[5], str) else ""
            attachments.append({"part_id": part_id or "1", "name": safe_name, "mime_type": media_type[:127], "size": size, "transfer_encoding": transfer_encoding})
        if node[0].casefold() == "message" and node[1].casefold() == "rfc822":
            for child in node[7:]:
                if isinstance(child, list) and child and isinstance(child[0], (list, str)):
                    visit(child, f"{part_id}.1", depth + 1)

    visit(structure, "")
    if len(attachments) > 100:
        raise SizeLimitError("message has too many attachment metadata entries")
    return attachments


def _quote_search(value: str) -> str:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BoundError("non-ASCII IMAP search text is unsupported by this server profile") from exc
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _folder_id(account_id: str, folder: str) -> str:
    digest = hashlib.sha256((account_id + "\0" + folder).encode("utf-8")).hexdigest()
    return "folder_" + digest[:24]


class MailBridge:
    def __init__(
        self,
        settings: AccountConfig,
        profile: str = "read",
        client_factory: Callable[..., Any] | None = None,
        secret_reader: Callable[[str], str] | None = None,
        trace: SafeTrace | None = None,
    ) -> None:
        self.settings = settings
        self.profile = "operator" if profile in {"write", "operator"} else "read"
        self.client_factory = client_factory
        self.secret_reader = secret_reader or platform_store().read_secret
        self.trace = trace or SafeTrace(self.profile, settings.trace_max_bytes, settings.trace_files)
        self.last_successful_check: str | None = None
        self._header_cache_lock = threading.RLock()
        self._header_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.last_sync_status: dict[str, Any] | None = None

    @contextmanager
    def session(self) -> Iterator[Any]:
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if self.settings.imap_security == "implicit_tls":
            factory = self.client_factory or imaplib.IMAP4_SSL
            client = factory(
                self.settings.host,
                self.settings.port,
                ssl_context=context,
                timeout=self.settings.timeout_seconds,
            )
        else:
            factory = self.client_factory or imaplib.IMAP4
            client = factory(
                self.settings.host,
                self.settings.port,
                timeout=self.settings.timeout_seconds,
            )
        try:
            if self.settings.imap_security == "starttls":
                try:
                    status, _ = client.starttls(ssl_context=context)
                except imaplib.IMAP4.error as exc:
                    raise MailTlsError("IMAP STARTTLS negotiation failed") from exc
                if str(status).upper() != "OK":
                    raise MailTlsError("IMAP STARTTLS negotiation failed")
            if b"LOGINDISABLED" in getattr(client, "capabilities", ()):
                raise MailLoginDisabledError("IMAP password login is disabled")
            try:
                status, _ = client.login(self.settings.username, self.secret_reader(self.settings.credential_target))
            except imaplib.IMAP4.abort:
                raise
            except imaplib.IMAP4.error as exc:
                raise MailAuthenticationError("IMAP authentication failed") from exc
            if str(status).upper() != "OK":
                raise MailAuthenticationError("IMAP authentication failed")
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass

    @staticmethod
    def _ok(result: tuple[Any, Any], operation: str) -> Any:
        status, data = result
        if str(status).upper() != "OK":
            raise MailError(f"{operation} failed with status {status}")
        return data

    def _capabilities(self, client: Any) -> set[str]:
        capability_data = self._ok(client.capability(), "CAPABILITY")
        return {
            token.decode("ascii", "replace").upper()
            for raw in _extract_bytes(capability_data)
            for token in raw.split()
            if token.upper() != b"CAPABILITY"
        }

    def _run(self, operation: str, callback: Callable[[], dict[str, Any] | list[Any]]) -> Any:
        started = time.monotonic()
        try:
            value = callback()
            self.last_successful_check = datetime.now(timezone.utc).isoformat()
            self.trace.event(operation, started, "success", last_successful_check=self.last_successful_check)
            return value
        except Exception as exc:
            self.trace.event(operation, started, "error", error_class=type(exc).__name__)
            raise

    def tls_and_capabilities(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            with self.session() as client:
                capabilities = sorted(self._capabilities(client))
                boxes = self._mailboxes(client)
                return self._health_payload(client, capabilities, boxes)
        return self._run("tls_and_capabilities", action)

    def _health_payload(
        self,
        client: Any,
        capabilities: list[str],
        boxes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        special_use: dict[str, dict[str, Any]] = {}
        for special in ("\\Drafts", "\\Sent", "\\Trash", "\\Junk"):
            match = next((
                box for box in boxes
                if any(flag.casefold() == special.casefold() for flag in box["flags"])
            ), None)
            special_use[special[1:].lower()] = {
                "available": match is not None,
                "folder_id": match["folder_id"] if match else None,
            }
        cert = client.sock.getpeercert()
        subject = {key: value for group in cert.get("subject", ()) for key, value in group}
        issuer = {key: value for group in cert.get("issuer", ()) for key, value in group}
        return {
            "endpoint": f"{self.settings.host}:{self.settings.port}",
            "tls": {
                "verified": True,
                "hostname_checked": True,
                "subject_cn": subject.get("commonName"),
                "issuer_cn": issuer.get("commonName"),
                "not_after": cert.get("notAfter"),
            },
            "capabilities": capabilities,
            "idle": "IDLE" in capabilities,
            "notify": "NOTIFY" in capabilities,
            "operator_features": {
                "safe_move": "MOVE" in capabilities and "UIDPLUS" in capabilities,
                "drafts": special_use["drafts"]["available"],
                "sent": special_use["sent"]["available"],
                "bin": special_use["trash"]["available"] and "MOVE" in capabilities and "UIDPLUS" in capabilities,
                "junk": special_use["junk"]["available"] and "MOVE" in capabilities and "UIDPLUS" in capabilities,
                "send_configured": self.settings.send_configured,
            },
            "special_use": special_use,
            "account_id": self.settings.account_id,
        }

    @staticmethod
    def _parse_list_line(line: bytes) -> dict[str, Any]:
        match = LIST_RE.match(line)
        if not match:
            raise MailError("unrecognized LIST response")
        flags = [part.decode("ascii", "replace") for part in match.group("flags").split()]
        raw_name = match.group("name").strip()
        if raw_name.startswith(b'"') and raw_name.endswith(b'"'):
            raw_name = raw_name[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
        return {"name": _decode_modified_utf7(raw_name), "flags": flags}

    def _mailboxes(self, client: Any) -> list[dict[str, Any]]:
        lines = self._ok(client.list(), "LIST")
        boxes: list[dict[str, Any]] = []
        for line in lines or []:
            if not line:
                continue
            item = self._parse_list_line(line)
            status_data = self._ok(client.status(_quote_mailbox(item["name"]), "(MESSAGES UNSEEN UIDVALIDITY UIDNEXT)"), "STATUS")
            status_blob = b" ".join(_extract_bytes(status_data))
            for key in ("MESSAGES", "UNSEEN", "UIDVALIDITY", "UIDNEXT"):
                match = re.search(rb"\b" + key.encode() + rb"\s+(\d+)", status_blob, re.I)
                item[key.lower()] = int(match.group(1)) if match else None
            item["folder_id"] = _folder_id(self.settings.account_id, item["name"])
            boxes.append(item)
        return boxes

    def list_mailboxes(self) -> list[dict[str, Any]]:
        return self._run("list_mailboxes", lambda: self._list_mailboxes_action())

    def _list_mailboxes_action(self) -> list[dict[str, Any]]:
        with self.session() as client:
            return self._mailboxes(client)

    def _bounded_window(self, since: str | None, before: str | None) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        start = _date(since, today - timedelta(days=14))
        end = _date(before, today + timedelta(days=1))
        if start >= end:
            raise BoundError("since must be earlier than before")
        if (end - start).days > self.settings.max_days:
            raise BoundError(f"date window exceeds {self.settings.max_days} days")
        return start, end

    def _select(self, client: Any, folder: str, readonly: bool) -> None:
        _clean_text(folder, "folder", 255)
        self._ok(client.select(_quote_mailbox(folder), readonly=readonly), "SELECT")
        client._selected_folder = folder

    def _uidvalidity(self, client: Any, folder: str) -> int:
        status_data = self._ok(client.status(_quote_mailbox(folder), "(UIDVALIDITY)"), "STATUS")
        match = re.search(rb"\bUIDVALIDITY\s+(\d+)", b" ".join(_extract_bytes(status_data)), re.I)
        if not match or int(match.group(1)) <= 0:
            raise MailError("UIDVALIDITY is unavailable; stable message references are disabled")
        return int(match.group(1))

    def _message_ref(self, folder: str, uidvalidity: int, uid: int) -> MessageRef:
        return MessageRef(self.settings.account_id, _folder_id(self.settings.account_id, folder), uidvalidity, uid)

    def validate_message_location(self, reference: MessageRef, folder: str, uid: int) -> None:
        _clean_text(folder, "folder", 255)
        if (
            reference.account_id != self.settings.account_id
            or reference.folder_id != _folder_id(self.settings.account_id, folder)
            or reference.uid != uid
        ):
            raise MailError("stable message reference does not match the requested message")

    def resolve_message_reference(self, folder: str, uid: int) -> dict[str, Any]:
        if uid <= 0:
            raise BoundError("uid must be positive")

        def action() -> dict[str, Any]:
            with self.session() as client:
                self._select(client, folder, True)
                uidvalidity = self._uidvalidity(client, folder)
                flags = self._flags(client, uid)
                return {
                    "message_ref": self._message_ref(folder, uidvalidity, uid).as_dict(),
                    "flags": flags,
                }

        return self._run("resolve_message_reference", action)

    def _folder_for_id(self, client: Any, folder_id: str) -> dict[str, Any]:
        matches = [box for box in self._mailboxes(client) if box["folder_id"] == folder_id]
        if len(matches) != 1:
            raise MailError("folder reference is unavailable or ambiguous")
        return matches[0]

    def _bounded_uids(self, client: Any, start: date, end: date, extra: list[str] | None = None) -> list[str]:
        status_data = self._ok(client.status(_quote_mailbox(client._selected_folder), "(UIDNEXT)"), "STATUS")
        blob = b" ".join(_extract_bytes(status_data))
        match = re.search(rb"UIDNEXT\s+(\d+)", blob, re.I)
        uid_next = int(match.group(1)) if match else self.settings.max_scan + 1
        first = max(1, uid_next - self.settings.max_scan)
        criteria: list[str] = ["UID", f"{first}:*", "SINCE", _imap_date(start), "BEFORE", _imap_date(end)]
        criteria.extend(extra or [])
        data = self._ok(client.uid("search", None, *criteria), "UID SEARCH")
        raw = b" ".join(_extract_bytes(data))
        uids = list(dict.fromkeys(token.decode("ascii") for token in raw.split() if token.isdigit()))
        return uids[-self.settings.max_results:]

    def _header(self, client: Any, uid: str, uidvalidity: int | None = None) -> dict[str, Any]:
        data = self._ok(
            client.uid(
                "fetch",
                uid,
                "(BODY.PEEK[HEADER.FIELDS (DATE FROM SUBJECT MESSAGE-ID REFERENCES IN-REPLY-TO LIST-ID LIST-UNSUBSCRIBE PRECEDENCE AUTO-SUBMITTED)] "
                f"BODY.PEEK[]<0.{LIST_PREVIEW_BYTES}> FLAGS RFC822.SIZE)",
            ),
            "UID FETCH",
        )
        chunks = _extract_bytes(data)
        literals = _extract_literals(data)
        raw_header = literals[0] if literals else next(
            (chunk for chunk in chunks if b":" in chunk and (b"\r\n" in chunk or b"\n" in chunk)),
            b"",
        )
        raw_preview = literals[1] if len(literals) > 1 else b""
        meta = b" ".join(chunk for chunk in chunks if chunk is not raw_header)
        msg = email.message_from_bytes(raw_header, policy=default)
        size = SIZE_RE.search(meta)
        flags = FLAGS_RE.search(meta)
        folder = client._selected_folder
        stable_uidvalidity = uidvalidity or self._uidvalidity(client, folder)
        sender = decode_value(msg.get("From"))
        subject = decode_value(msg.get("Subject"))
        list_id = decode_value(msg.get("List-ID"))
        unsubscribe = decode_value(msg.get("List-Unsubscribe"))
        precedence = decode_value(msg.get("Precedence")).casefold()
        auto_submitted = decode_value(msg.get("Auto-Submitted")).casefold()
        combined = f"{sender}\n{subject}"
        reasons: list[str] = []
        if ADVERTISING_RE.search(combined):
            reasons.append("marketing_term")
        if list_id and unsubscribe:
            reasons.append("mailing_list_header")
        if precedence in {"bulk", "list"}:
            reasons.append("bulkheader")
        if auto_submitted and auto_submitted != "no" and unsubscribe:
            reasons.append("automatisch_verzonden")
        advertising = bool(reasons) and not bool(TRANSACTIONAL_RE.search(combined))
        return {
            "uid": int(uid),
            "message_ref": self._message_ref(folder, stable_uidvalidity, int(uid)).as_dict(),
            "date": decode_value(msg.get("Date")),
            "from": sender,
            "subject": subject,
            "message_id": decode_value(msg.get("Message-ID")),
            "in_reply_to": decode_value(msg.get("In-Reply-To")),
            "size": int(size.group(1)) if size else None,
            "flags": flags.group(1).decode("ascii", "replace").split() if flags else [],
            "preview": _message_preview(raw_preview),
            "category": "advertising" if advertising else None,
            "classification_reasons": reasons if advertising else [],
        }

    def _flags_for_uids(self, client: Any, uids: list[str]) -> dict[int, list[str]]:
        if not uids:
            return {}
        data = self._ok(client.uid("fetch", ",".join(uids), "(UID FLAGS)"), "UID FETCH")
        result: dict[int, list[str]] = {}
        for chunk in _extract_bytes(data):
            uid_match = UID_RE.search(chunk)
            flags_match = FLAGS_RE.search(chunk)
            if uid_match:
                result[int(uid_match.group(1))] = (
                    flags_match.group(1).decode("ascii", "replace").split() if flags_match else []
                )
        return result

    def _incremental_headers(
        self,
        client: Any,
        folder: str,
        start: date,
        end: date,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self._select(client, folder, True)
        uidvalidity = self._uidvalidity(client, folder)
        current_uids = self._bounded_uids(client, start, end)
        key = (folder, start.isoformat(), end.isoformat())
        now = datetime.now(timezone.utc).isoformat()

        with self._header_cache_lock:
            cached = self._header_cache.get(key)
            full_sync = cached is None or cached["uidvalidity"] != uidvalidity
            if full_sync:
                items = {
                    int(uid): self._header(client, uid, uidvalidity)
                    for uid in current_uids
                }
                fetched = len(current_uids)
                reused = 0
                removed = len(cached["items"]) if cached else 0
                mode = "full"
            else:
                previous_items = dict(cached["items"])
                current_ids = {int(uid) for uid in current_uids}
                missing = [uid for uid in current_uids if int(uid) not in previous_items]
                items = {
                    uid: item
                    for uid, item in previous_items.items()
                    if uid in current_ids
                }
                for uid in missing:
                    items[int(uid)] = self._header(client, uid, uidvalidity)
                for uid, flags in self._flags_for_uids(client, current_uids).items():
                    if uid in items:
                        items[uid] = {**items[uid], "flags": flags}
                fetched = len(missing)
                reused = len(current_uids) - fetched
                removed = len(previous_items) - len(previous_items.keys() & current_ids)
                mode = "unchanged" if fetched == 0 and removed == 0 else "incremental"

            self._header_cache[key] = {
                "uidvalidity": uidvalidity,
                "items": items,
                "last_used": time.monotonic(),
            }
            if len(self._header_cache) > 8:
                oldest = min(
                    (cache_key for cache_key in self._header_cache if cache_key != key),
                    key=lambda cache_key: self._header_cache[cache_key]["last_used"],
                    default=None,
                )
                if oldest is not None:
                    self._header_cache.pop(oldest, None)

            ordered = [items[int(uid)] for uid in current_uids if int(uid) in items]
            sync = {
                "mode": mode,
                "folder_id": _folder_id(self.settings.account_id, folder),
                "uidvalidity": uidvalidity,
                "highest_uid": int(current_uids[-1]) if current_uids else None,
                "known_headers": len(ordered),
                "fetched_headers": fetched,
                "reused_headers": reused,
                "removed_headers": removed,
                "persisted_mail_content": False,
                "synced_at": now,
            }
            self.last_sync_status = sync
            return ordered[-limit:], sync

    def list_message_headers(self, folder: str, since: str | None = None, before: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= self.settings.max_results:
            raise BoundError(f"limit must be 1..{self.settings.max_results}")
        start, end = self._bounded_window(since, before)
        def action() -> list[dict[str, Any]]:
            with self.session() as client:
                items, _ = self._incremental_headers(client, folder, start, end, limit)
                return items
        return self._run("list_message_headers", action)

    def list_messages(self, folder: str, since: str | None = None, before: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_message_headers(folder, since, before, limit)

    def search_messages(
        self,
        folder: str,
        since: str,
        before: str,
        sender: str | None = None,
        subject: str | None = None,
        text: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= self.settings.max_results:
            raise BoundError(f"limit must be 1..{self.settings.max_results}")
        start, end = self._bounded_window(since, before)
        extra: list[str] = []
        for key, value in (("FROM", sender), ("SUBJECT", subject), ("TEXT", text)):
            if value:
                extra.extend([key, _quote_search(_clean_text(value, key.lower()))])
        if not extra:
            raise BoundError("search requires sender, subject, or text in addition to the date window")
        def action() -> list[dict[str, Any]]:
            with self.session() as client:
                self._select(client, folder, True)
                uidvalidity = self._uidvalidity(client, folder)
                return [self._header(client, uid, uidvalidity) for uid in self._bounded_uids(client, start, end, extra)[-limit:]]
        return self._run("search_messages", action)

    def _message_bytes(self, client: Any, uid: int) -> bytes:
        if uid <= 0:
            raise BoundError("uid must be positive")
        ceiling = self.settings.max_message_bytes
        data = self._ok(client.uid("fetch", str(uid), f"(BODY.PEEK[]<0.{ceiling + 1}>)"), "UID FETCH")
        chunks = _extract_bytes(data)
        raw = _extract_literal(data) or max(chunks, key=len, default=b"")
        if len(raw) > ceiling:
            raise SizeLimitError(f"message exceeds the {ceiling}-byte in-memory response ceiling")
        return raw

    def _message_record(self, client: Any, folder: str, uid: int) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        self._select(client, folder, True)
        uidvalidity = self._uidvalidity(client, folder)
        raw = self._message_bytes(client, uid)
        msg = email.message_from_bytes(raw, policy=default)
        body, formatted_body, oversized = decoded_body(msg, self.settings.max_message_bytes)
        if oversized:
            raise SizeLimitError("decoded message exceeds the in-memory response ceiling")
        flags = self._flags(client, uid)
        record = {
            "folder": folder,
            "uid": uid,
            "message_ref": self._message_ref(folder, uidvalidity, uid).as_dict(),
            "date": decode_value(msg.get("Date")),
            "from": decode_value(msg.get("From")),
            "to": decode_value(msg.get("To")),
            "cc": decode_value(msg.get("Cc")),
            "subject": decode_value(msg.get("Subject")),
            "message_id": decode_value(msg.get("Message-ID")),
            "in_reply_to": decode_value(msg.get("In-Reply-To")),
            "references": decode_value(msg.get("References")),
            "flags": flags,
            "text": body,
            "formatted_body": formatted_body,
            "remote_content_fetched": False,
            "untrusted_content": True,
        }
        return record, security_signals(msg, self.settings.trusted_authserv_ids), raw

    def get_message(self, folder: str, uid: int) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            with self.session() as client:
                record, signals, _ = self._message_record(client, folder, uid)
                record["security_summary"] = {
                    "remote_url_count": signals["remote_url_count"],
                    "remote_image_count": len(signals.get("remote_image_https", [])),
                    "link_mismatch_count": signals["link_mismatch_count"],
                    "has_attachments": signals["has_attachments"],
                }
                return record
        return self._run("get_message", action)

    def get_message_with_security(self, folder: str, uid: int) -> tuple[dict[str, Any], dict[str, Any]]:
        def action() -> dict[str, Any]:
            with self.session() as client:
                record, signals, _ = self._message_record(client, folder, uid)
                return {"message": record, "signals": signals}
        result = self._run("get_message_with_security", action)
        return result["message"], result["signals"]

    def mail_view_bootstrap(self, folder: str = "INBOX", limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= self.settings.max_results:
            raise BoundError(f"limit must be 1..{self.settings.max_results}")
        _clean_text(folder, "folder", 255)
        start, end = self._bounded_window(None, None)

        def action() -> dict[str, Any]:
            with self.session() as client:
                capabilities = sorted(self._capabilities(client))
                boxes = self._mailboxes(client)
                target = next((box for box in boxes if box["name"] == folder), None)
                if target is None:
                    target = next((
                        box for box in boxes
                        if any(flag.casefold() == "\\inbox" for flag in box["flags"])
                    ), boxes[0] if boxes else None)
                if target is None:
                    raise MailError("no mailbox is available")
                folder_name = str(target["name"])
                messages, sync = self._incremental_headers(
                    client,
                    folder_name,
                    start,
                    end,
                    limit,
                )
                initial_message = None
                initial_signals = None
                if messages:
                    initial_message, initial_signals, _ = self._message_record(
                        client,
                        folder_name,
                        int(messages[-1]["uid"]),
                    )
                    initial_message["security_summary"] = {
                        "remote_url_count": initial_signals["remote_url_count"],
                        "remote_image_count": len(initial_signals.get("remote_image_https", [])),
                        "link_mismatch_count": initial_signals["link_mismatch_count"],
                        "has_attachments": initial_signals["has_attachments"],
                    }
                return {
                    "folder": folder_name,
                    "mailboxes": boxes,
                    "messages": messages,
                    "initial_message": initial_message,
                    "_initial_security_signals": initial_signals,
                    "health": self._health_payload(client, capabilities, boxes),
                    "sync": sync,
                }

        return self._run("mail_view_bootstrap", action)

    def current_state(self, reference: MessageRef) -> dict[str, Any]:
        if reference.account_id != self.settings.account_id:
            raise MailError("message reference belongs to a different account")
        def action() -> dict[str, Any]:
            with self.session() as client:
                box = self._folder_for_id(client, reference.folder_id)
                if box["uidvalidity"] != reference.uidvalidity:
                    raise MailError("UIDVALIDITY changed; the reviewed message reference is stale")
                self._select(client, box["name"], True)
                flags = self._flags(client, reference.uid)
                return {
                    "message_ref": reference.as_dict(),
                    "folder_id": reference.folder_id,
                    "uidvalidity": reference.uidvalidity,
                    "uid": reference.uid,
                    "flags": sorted(flags),
                }
        return self._run("current_state", action)

    def get_thread(self, folder: str, uid: int, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= min(20, self.settings.max_results):
            raise BoundError("thread limit must be 1..20")
        current = self.get_message(folder, uid)
        identifiers = {
            token for token in re.findall(r"<[^>]{1,500}>", " ".join([
                current.get("message_id", ""), current.get("in_reply_to", ""), current.get("references", "")
            ]))
        }
        today = datetime.now(timezone.utc).date()
        start, end = self._bounded_window(
            (today - timedelta(days=self.settings.max_days - 1)).isoformat(),
            (today + timedelta(days=1)).isoformat(),
        )
        candidates = self.list_message_headers(folder, start.isoformat(), end.isoformat(), min(limit, self.settings.max_results))
        if not identifiers:
            normalized = re.sub(r"(?i)^\s*(re|fw|fwd):\s*", "", current.get("subject", "")).casefold()
            return [item for item in candidates if re.sub(r"(?i)^\s*(re|fw|fwd):\s*", "", item.get("subject", "")).casefold() == normalized][:limit]
        result = []
        for item in candidates:
            item_ids = {item.get("message_id", ""), item.get("in_reply_to", "")}
            if identifiers.intersection(item_ids) or item.get("uid") == uid:
                result.append(item)
        return result[:limit]

    def collect_context(self, folder: str, uid: int, related_limit: int = 5) -> dict[str, Any]:
        if not 0 <= related_limit <= 5:
            raise BoundError("related_limit must be 0..5")
        current = self.get_message(folder, uid)
        current_ref = MessageRef.from_mapping(current["message_ref"])
        thread_items = self.get_thread(folder, uid, min(20, self.settings.max_results))
        thread_refs = tuple(MessageRef.from_mapping(item["message_ref"]) for item in thread_items)
        today = datetime.now(timezone.utc).date()
        headers = self.list_message_headers(
            folder,
            (today - timedelta(days=30)).isoformat(),
            (today + timedelta(days=1)).isoformat(),
            self.settings.max_results,
        )
        normalized_subject = re.sub(r"(?i)^\s*(re|fw|fwd):\s*", "", current.get("subject", "")).casefold()
        sender_domain = current.get("from", "").rsplit("@", 1)[-1].rstrip("> ").casefold()
        thread_set = set(thread_refs)
        related: list[ContextSource] = []
        for item in reversed(headers):
            ref = MessageRef.from_mapping(item["message_ref"])
            if ref == current_ref or ref in thread_set:
                continue
            item_subject = re.sub(r"(?i)^\s*(re|fw|fwd):\s*", "", item.get("subject", "")).casefold()
            item_domain = item.get("from", "").rsplit("@", 1)[-1].rstrip("> ").casefold()
            reason = None
            if normalized_subject and item_subject == normalized_subject:
                reason = "same normalized subject"
            elif sender_domain and item_domain == sender_domain:
                reason = "same sender domain within 31 days"
            if reason:
                related.append(ContextSource(ref, reason))
            if len(related) >= related_limit:
                break
        return ContextBundle(current_ref, thread_refs, tuple(related)).as_dict()

    def get_attachment_metadata(self, folder: str, uid: int) -> list[dict[str, Any]]:
        def action() -> list[dict[str, Any]]:
            with self.session() as client:
                self._select(client, folder, True)
                if uid <= 0:
                    raise BoundError("uid must be positive")
                data = self._ok(client.uid("fetch", str(uid), "(BODYSTRUCTURE)"), "UID FETCH BODYSTRUCTURE")
                raw = b" ".join(_extract_bytes(data))
                return _bodystructure_attachments(_parse_bodystructure(raw))
        return self._run("get_attachment_metadata", action)

    def fetch_attachment_bytes(
        self,
        reference: MessageRef,
        part_id: str,
        *,
        transfer_encoding: str = "",
        max_bytes: int = 25 * 1024 * 1024,
    ) -> bytes:
        if reference.account_id != self.settings.account_id:
            raise MailError("message reference belongs to a different account")
        if not re.fullmatch(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*", part_id):
            raise BoundError("invalid IMAP attachment part identifier")
        if not 1 <= max_bytes <= 25 * 1024 * 1024:
            raise BoundError("attachment download ceiling must be 1..25 MiB")

        def action() -> bytes:
            with self.session() as client:
                box = self._folder_for_id(client, reference.folder_id)
                if box["uidvalidity"] != reference.uidvalidity:
                    raise MailError("UIDVALIDITY changed; the reviewed message reference is stale")
                self._select(client, box["name"], True)
                data = self._ok(
                    client.uid("fetch", str(reference.uid), f"(BODY.PEEK[{part_id}]<0.{max_bytes + 1}>)"),
                    "UID FETCH attachment",
                )
                raw = _extract_literal(data) or max(_extract_bytes(data), key=len, default=b"")
                if len(raw) > max_bytes:
                    raise SizeLimitError("attachment exceeds the 25 MiB secure download ceiling")
                encoding = transfer_encoding.casefold()
                try:
                    if encoding == "base64":
                        decoded = base64.b64decode(b"".join(raw.split()), validate=True)
                    elif encoding == "quoted-printable":
                        decoded = quopri.decodestring(raw)
                    elif encoding in {"", "7bit", "8bit", "binary"}:
                        decoded = raw
                    else:
                        raise MailError("unsupported attachment transfer encoding")
                except (binascii.Error, ValueError) as exc:
                    raise MailError("attachment transfer encoding is invalid") from exc
                if len(decoded) > max_bytes:
                    raise SizeLimitError("decoded attachment exceeds the 25 MiB secure download ceiling")
                return decoded

        return self._run("fetch_attachment_bytes", action)

    def find_actionables(self, folder: str, since: str | None = None, before: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        headers = self.list_message_headers(folder, since, before, limit)
        cues = ("action", "reply", "urgent", "invoice", "betaling", "vraag", "follow", "?")
        result = []
        for item in headers:
            subject = item["subject"].lower()
            unread = "\\Seen" not in item["flags"]
            if unread or any(cue in subject for cue in cues):
                result.append({
                    "citation": {"folder": folder, "uid": item["uid"], "date": item["date"]},
                    "reason": "unread" if unread else "subject cue",
                    "subject": item["subject"],
                    "from": item["from"],
                    "untrusted_content": True,
                })
        return result

    def _require_write(self) -> None:
        if self.profile != "operator":
            raise MailError("operator action rejected by process-level read profile")

    def _flags(self, client: Any, uid: int) -> list[str]:
        data = self._ok(client.uid("fetch", str(uid), "(FLAGS)"), "UID FETCH")
        match = FLAGS_RE.search(b" ".join(_extract_bytes(data)))
        return match.group(1).decode("ascii", "replace").split() if match else []

    def _set_flag(self, folder: str, uid: int, flag: str, enabled: bool) -> dict[str, Any]:
        self._require_write()
        def action() -> dict[str, Any]:
            with self.session() as client:
                self._select(client, folder, False)
                previous = self._flags(client, uid)
                operation = "+FLAGS.SILENT" if enabled else "-FLAGS.SILENT"
                self._ok(client.uid("store", str(uid), operation, f"({flag})"), "UID STORE")
                resulting = self._flags(client, uid)
                return {"folder": folder, "uid": uid, "previous_flags": previous, "resulting_flags": resulting}
        return self._run("set_flag", action)

    def set_seen(self, folder: str, uid: int, seen: bool) -> dict[str, Any]:
        return self._set_flag(folder, uid, "\\Seen", seen)

    def set_flagged(self, folder: str, uid: int, flagged: bool) -> dict[str, Any]:
        return self._set_flag(folder, uid, "\\Flagged", flagged)

    def apply_flag(
        self,
        reference: MessageRef,
        flag: str,
        enabled: bool,
        expected_flags: list[str],
    ) -> dict[str, Any]:
        self._require_write()
        if flag not in {"\\Seen", "\\Flagged"}:
            raise BoundError("unsupported flag")
        if reference.account_id != self.settings.account_id:
            raise MailError("message reference belongs to a different account")
        def action() -> dict[str, Any]:
            with self.session() as client:
                box = self._folder_for_id(client, reference.folder_id)
                if box["uidvalidity"] != reference.uidvalidity:
                    raise MailError("UIDVALIDITY changed; approval is invalid")
                self._select(client, box["name"], False)
                previous = sorted(self._flags(client, reference.uid))
                if previous != sorted(expected_flags):
                    raise MailError("message flags changed after review; approval is invalid")
                operation = "+FLAGS.SILENT" if enabled else "-FLAGS.SILENT"
                self._ok(client.uid("store", str(reference.uid), operation, f"({flag})"), "UID STORE")
                resulting = sorted(self._flags(client, reference.uid))
                return {
                    "message_ref": reference.as_dict(),
                    "previous_flags": previous,
                    "resulting_flags": resulting,
                }
        return self._run("apply_flag", action)

    def _special_folder(self, client: Any, special_use: str) -> dict[str, Any]:
        for item in self._mailboxes(client):
            if any(flag.casefold() == special_use.casefold() for flag in item["flags"]):
                return item
        raise CapabilityError(f"SPECIAL-USE {special_use} mapping is not proven")

    def _draft_folder(self, client: Any) -> str:
        return self._special_folder(client, "\\Drafts")["name"]

    def save_draft(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        cc: str = "",
    ) -> dict[str, Any]:
        self._require_write()
        for field, value, limit in (("to", to, 1000), ("cc", cc, 1000), ("subject", subject, 500)):
            _clean_text(value, field, limit)
        _clean_body(body, self.settings.max_message_bytes)
        if in_reply_to:
            _clean_text(in_reply_to, "in_reply_to", 500)
        def action() -> dict[str, Any]:
            with self.session() as client:
                draft_folder = self._draft_folder(client)
                msg = EmailMessage()
                msg["From"] = self.settings.from_address
                msg["To"] = to
                if cc:
                    msg["Cc"] = cc
                msg["Subject"] = subject
                msg["Message-ID"] = make_msgid(domain="imap-plugin.invalid")
                if in_reply_to:
                    msg["In-Reply-To"] = in_reply_to
                    msg["References"] = in_reply_to
                msg.set_content(body)
                raw = msg.as_bytes(policy=default)
                if len(raw) > self.settings.max_message_bytes:
                    raise SizeLimitError("draft exceeds the in-memory ceiling")
                data = self._ok(client.append(_quote_mailbox(draft_folder), "\\Draft", None, raw), "APPEND")
                response = b" ".join(_extract_bytes(data))
                uid_match = re.search(rb"APPENDUID\s+(\d+)\s+(\d+)", response, re.I)
                if not uid_match:
                    raise MailError("draft was appended but its stable UID could not be proven")
                uidvalidity, uid = int(uid_match.group(1)), int(uid_match.group(2))
                return {
                    "folder": draft_folder,
                    "uid": uid,
                    "message_ref": self._message_ref(draft_folder, uidvalidity, uid).as_dict(),
                    "message_id": msg["Message-ID"],
                }
        return self._run("save_draft", action)

    def move_message(
        self,
        reference: MessageRef,
        *,
        destination_folder_id: str | None = None,
        destination_special_use: str | None = None,
        expected_flags: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_write()
        if reference.account_id != self.settings.account_id:
            raise MailError("message reference belongs to a different account")
        if (destination_folder_id is None) == (destination_special_use is None):
            raise BoundError("choose exactly one destination folder")
        def action() -> dict[str, Any]:
            with self.session() as client:
                capabilities = self._capabilities(client)
                if not {"MOVE", "UIDPLUS"}.issubset(capabilities):
                    raise CapabilityError("safe UID MOVE with UIDPLUS is unavailable; action disabled")
                source = self._folder_for_id(client, reference.folder_id)
                if source["uidvalidity"] != reference.uidvalidity:
                    raise MailError("UIDVALIDITY changed; the reviewed message reference is stale")
                destination = (
                    self._folder_for_id(client, str(destination_folder_id))
                    if destination_folder_id is not None
                    else self._special_folder(client, str(destination_special_use))
                )
                if source["folder_id"] == destination["folder_id"]:
                    raise BoundError("source and destination folders are identical")
                self._select(client, source["name"], False)
                previous_flags = sorted(self._flags(client, reference.uid))
                if expected_flags is not None and previous_flags != sorted(expected_flags):
                    raise MailError("message flags changed after review; approval is invalid")
                response_data = self._ok(
                    client.uid("MOVE", str(reference.uid), _quote_mailbox(destination["name"])),
                    "UID MOVE",
                )
                response = b" ".join(_extract_bytes(response_data))
                copy_uid = re.search(rb"COPYUID\s+(\d+)\s+\d+(?::\d+)?\s+(\d+)", response, re.I)
                destination_ref = None
                if copy_uid:
                    destination_ref = self._message_ref(
                        destination["name"], int(copy_uid.group(1)), int(copy_uid.group(2))
                    )
                return {
                    "source": reference.as_dict(),
                    "destination_folder_id": destination["folder_id"],
                    "destination": destination_ref.as_dict() if destination_ref else None,
                    "previous_flags": previous_flags,
                    "restore_available": destination_ref is not None,
                    "restore_details": {
                        "source_folder_id": source["folder_id"],
                        "destination_folder_id": destination["folder_id"],
                        "moved_ref": destination_ref.as_dict() if destination_ref else None,
                    },
                }
        return self._run("move_message", action)

    def restore_move(self, details: dict[str, Any], destination_folder_id: str | None = None) -> dict[str, Any]:
        self._require_write()
        moved = details.get("moved_ref")
        if not moved:
            raise MailError("the server did not provide a stable destination UID; automatic restore is unavailable")
        target = destination_folder_id or details.get("source_folder_id")
        if not target:
            raise BoundError("a restore destination is required")
        return self.move_message(MessageRef.from_mapping(moved), destination_folder_id=str(target))

    def append_sent_copy(self, raw: bytes) -> dict[str, Any]:
        self._require_write()
        if len(raw) > self.settings.max_message_bytes:
            raise SizeLimitError("sent copy exceeds the in-memory ceiling")
        def action() -> dict[str, Any]:
            with self.session() as client:
                sent = self._special_folder(client, "\\Sent")
                data = self._ok(client.append(_quote_mailbox(sent["name"]), "\\Seen", None, raw), "APPEND Sent")
                response = b" ".join(_extract_bytes(data))
                uid_match = re.search(rb"APPENDUID\s+(\d+)\s+(\d+)", response, re.I)
                return {
                    "folder_id": sent["folder_id"],
                    "uid": int(uid_match.group(2)) if uid_match else None,
                }
        return self._run("append_sent_copy", action)

    def read_draft(self, reference: MessageRef) -> dict[str, Any]:
        if reference.account_id != self.settings.account_id:
            raise MailError("draft reference belongs to a different account")
        def action() -> dict[str, Any]:
            with self.session() as client:
                box = self._folder_for_id(client, reference.folder_id)
                if not any(flag.casefold() == "\\drafts" for flag in box["flags"]):
                    raise MailError("send source must be in the verified Drafts folder")
                if box["uidvalidity"] != reference.uidvalidity:
                    raise MailError("UIDVALIDITY changed; draft review is stale")
                record, signals, raw = self._message_record(client, box["name"], reference.uid)
                parsed = email.message_from_bytes(raw, policy=default)
                if any(part.get_content_disposition() == "attachment" or part.get_filename() for part in parsed.walk()):
                    raise MailError("attachments are disabled in v1")
                record["raw_size"] = len(raw)
                return record
        return self._run("read_draft", action)

    def baseline(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            with self.session() as client:
                boxes = self._mailboxes(client)
                result = []
                for box in boxes:
                    flags = []
                    selectable = not any(flag.lower() == "\\noselect" for flag in box["flags"])
                    if selectable:
                        self._select(client, box["name"], True)
                        uid_next = box.get("uidnext") or 1
                        start = max(1, uid_next - min(25, self.settings.max_scan))
                        data = self._ok(client.uid("fetch", f"{start}:*", "(UID FLAGS)"), "UID FETCH")
                        for chunk in _extract_bytes(data):
                            uid = UID_RE.search(chunk)
                            value = FLAGS_RE.search(chunk)
                            if uid:
                                flags.append({"uid": int(uid.group(1)), "flags": sorted(value.group(1).decode("ascii", "replace").split()) if value else []})
                    result.append({"folder_hash": hash_folder(box["name"]), "selectable": selectable, "messages": box["messages"], "uidvalidity": box["uidvalidity"], "uidnext": box["uidnext"], "flags": flags})
                return {"folders": sorted(result, key=lambda item: item["folder_hash"])}
        return self._run("baseline", action)
