from __future__ import annotations

import ctypes
import base64
import hashlib
import json
import os
import platform
import secrets
import sqlite3
import threading
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .contracts import Classification, MessageRef


class StateError(RuntimeError):
    pass


class Protector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDataProtector:
    """Current-user DPAPI protection; secrets never cross the MCP boundary."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise StateError("Windows DPAPI is required for protected operator state")
        self._crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _blob(value: bytes) -> tuple[DATA_BLOB, Any]:
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    def protect(self, value: bytes) -> bytes:
        source, keepalive = self._blob(value)
        entropy, entropy_keepalive = self._blob(b"imap-plugin-state-v1")
        output = DATA_BLOB()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), "IMAP Plugin protected state", ctypes.byref(entropy),
            None, None, 0, ctypes.byref(output),
        ):
            raise StateError(f"CryptProtectData failed with Windows error {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, value: bytes) -> bytes:
        source, keepalive = self._blob(value)
        entropy, entropy_keepalive = self._blob(b"imap-plugin-state-v1")
        output = DATA_BLOB()
        description = wintypes.LPWSTR()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy),
            None, None, 0, ctypes.byref(output),
        ):
            raise StateError(f"CryptUnprotectData failed with Windows error {ctypes.get_last_error()}")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if description:
                self._kernel32.LocalFree(description)
            self._kernel32.LocalFree(output.pbData)


class TestProtector:
    """Explicit test-only protector; construction is blocked outside test mode."""

    __test__ = False

    def __init__(self) -> None:
        if os.environ.get("IMAP_PLUGIN_TEST_MODE") != "1":
            raise StateError("test protector is disabled outside explicit test mode")

    def protect(self, value: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(b"imap-plugin-test-key-32-bytes!!!").encrypt(nonce, value, b"test-state-v1")

    def unprotect(self, value: bytes) -> bytes:
        if len(value) < 29:
            raise StateError("invalid test-protected value")
        try:
            return AESGCM(b"imap-plugin-test-key-32-bytes!!!").decrypt(value[:12], value[12:], b"test-state-v1")
        except InvalidTag as exc:
            raise StateError("invalid test-protected value") from exc


class MacKeychainDataProtector:
    """AES-GCM state protection whose key lives in the current user's Keychain."""

    _TARGET = "imap-plugin/state-key"
    _AAD = b"imap-plugin-state-v1"

    def __init__(self) -> None:
        if platform.system() != "Darwin":
            raise StateError("macOS Keychain state protection is unavailable")
        from .credentials import CredentialError, platform_store

        store = platform_store()
        try:
            encoded = store.read_secret(self._TARGET)
        except CredentialError:
            encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
            store.write_secret(self._TARGET, encoded)
        try:
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise StateError("the Keychain state key is invalid") from exc
        if len(key) != 32:
            raise StateError("the Keychain state key has an invalid length")
        self._cipher = AESGCM(key)

    def protect(self, value: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, value, self._AAD)

    def unprotect(self, value: bytes) -> bytes:
        if len(value) < 29:
            raise StateError("protected state is truncated")
        try:
            return self._cipher.decrypt(value[:12], value[12:], self._AAD)
        except InvalidTag as exc:
            raise StateError("protected state authentication failed") from exc


def platform_protector() -> Protector:
    if os.environ.get("IMAP_PLUGIN_TEST_MODE") == "1":
        return TestProtector()
    if os.name == "nt":
        return WindowsDataProtector()
    if platform.system() == "Darwin":
        return MacKeychainDataProtector()
    raise StateError("no proven native state protector is available on this platform")


def _hash(namespace: str, value: str) -> str:
    return hashlib.sha256((namespace + "\0" + value).encode("utf-8")).hexdigest()


class MetadataStore:
    def __init__(self, path: Path, protector: Protector | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.protector = protector or platform_protector()
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    protected_value BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS classifications (
                    ref_hash TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    version TEXT NOT NULL,
                    classified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS classification_cache (
                    ref_hash TEXT NOT NULL,
                    classifier TEXT NOT NULL,
                    label TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    version TEXT NOT NULL,
                    input_digest TEXT NOT NULL,
                    classified_at TEXT NOT NULL,
                    PRIMARY KEY(ref_hash, classifier)
                );
                CREATE TABLE IF NOT EXISTS classification_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_hash TEXT NOT NULL,
                    classifier TEXT NOT NULL,
                    label TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    version TEXT NOT NULL,
                    input_digest TEXT NOT NULL,
                    classified_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS classification_history_recent
                    ON classification_history(classifier, classified_at DESC);
                CREATE TABLE IF NOT EXISTS assistant_cache (
                    ref_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    protected_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY(ref_hash, action, prompt_version)
                );
                CREATE INDEX IF NOT EXISTS assistant_cache_expiry
                    ON assistant_cache(expires_at);
                CREATE TABLE IF NOT EXISTS moves (
                    receipt_id TEXT PRIMARY KEY,
                    account_hash TEXT NOT NULL,
                    ref_hash TEXT NOT NULL,
                    protected_details BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    restored_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sends (
                    message_digest TEXT PRIMARY KEY,
                    outcome TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    attempted_at TEXT NOT NULL
                );
                """
            )

    def _put_protected_json(self, key: str, value: Mapping[str, Any]) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        protected = self.protector.protect(raw)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO settings(key, protected_value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET protected_value=excluded.protected_value, updated_at=excluded.updated_at",
                (key, protected, now),
            )

    def _get_protected_json(self, key: str, default: Mapping[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT protected_value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return dict(default)
        return dict(json.loads(self.protector.unprotect(row[0]).decode("utf-8")))

    def save_pack_settings(self, value: Mapping[str, bool]) -> None:
        allowed = {"core", "phishing", "priority", "cleanup", "setup_completed"}
        if set(value) != allowed or value.get("core") is not True:
            raise StateError("feature-pack settings must include always-enabled core")
        self._put_protected_json("feature_packs", {key: bool(value[key]) for key in sorted(allowed)})

    def load_pack_settings(self) -> dict[str, bool]:
        value = self._get_protected_json(
            "feature_packs",
            {"core": True, "phishing": False, "priority": False, "cleanup": False, "setup_completed": False},
        )
        return {key: bool(value.get(key, False)) for key in ("core", "phishing", "priority", "cleanup", "setup_completed")}

    def save_priority_rules(self, rules: Mapping[str, Any]) -> None:
        self._put_protected_json("priority_rules", rules)

    def load_priority_rules(self) -> dict[str, Any]:
        return self._get_protected_json("priority_rules", {})

    @staticmethod
    def _classification_scope(classifier: str, input_digest: str) -> tuple[str, str]:
        if classifier not in {"phishing", "priority"}:
            raise StateError("unsupported classification cache")
        if len(input_digest) != 64:
            raise StateError("classification input digest must be SHA-256")
        try:
            int(input_digest, 16)
        except ValueError as exc:
            raise StateError("classification input digest must be SHA-256") from exc
        return classifier, input_digest.casefold()

    def load_classification(
        self,
        message_ref: MessageRef,
        *,
        classifier: str,
        version: str,
        input_digest: str,
    ) -> Classification | None:
        classifier, input_digest = self._classification_scope(classifier, input_digest)
        ref_hash = _hash("message-ref-v1", json.dumps(message_ref.as_dict(), sort_keys=True))
        with self._connect() as db:
            row = db.execute(
                "SELECT label,reason_codes,version,classified_at "
                "FROM classification_cache WHERE ref_hash=? AND classifier=? AND version=? AND input_digest=?",
                (ref_hash, classifier, version, input_digest),
            ).fetchone()
        if row is None:
            return None
        try:
            reason_codes = tuple(str(value) for value in json.loads(row[1]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateError("classification cache contains invalid reason codes") from exc
        return Classification(
            message_ref=message_ref,
            label=str(row[0]),
            reason_codes=reason_codes,
            explanation=self._cached_explanation(classifier, str(row[0]), reason_codes),
            version=str(row[2]),
            timestamp=str(row[3]),
        )

    @staticmethod
    def _cached_explanation(classifier: str, label: str, reason_codes: tuple[str, ...]) -> str:
        reasons = ", ".join(value.replace("_", " ") for value in reason_codes)
        if classifier == "phishing":
            if reasons:
                return f"Advisory only. The local check flagged: {reasons}."
            return "Advisory only. The local check found no obvious indicators; this does not guarantee that the message is safe."
        detail = f": {reasons}" if reasons else ""
        return f"Local advisory priority ({label}) based on the approved rules{detail}. The message is not hidden or moved."

    def save_classification(
        self,
        classification: Classification,
        *,
        classifier: str,
        input_digest: str,
    ) -> None:
        classifier, input_digest = self._classification_scope(classifier, input_digest)
        ref_hash = _hash("message-ref-v1", json.dumps(classification.message_ref.as_dict(), sort_keys=True))
        reason_codes = json.dumps(sorted(set(classification.reason_codes)), separators=(",", ":"))
        with self._lock, self._connect() as db:
            previous = db.execute(
                "SELECT label,reason_codes,version,input_digest "
                "FROM classification_cache WHERE ref_hash=? AND classifier=?",
                (ref_hash, classifier),
            ).fetchone()
            current = (
                classification.label,
                reason_codes,
                classification.version,
                input_digest,
            )
            db.execute(
                "INSERT INTO classification_cache(ref_hash,classifier,label,reason_codes,version,input_digest,classified_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(ref_hash,classifier) DO UPDATE SET "
                "label=excluded.label,reason_codes=excluded.reason_codes,"
                "version=excluded.version,input_digest=excluded.input_digest,classified_at=excluded.classified_at",
                (ref_hash, classifier, *current, classification.timestamp),
            )
            if previous != current:
                db.execute(
                    "INSERT INTO classification_history(ref_hash,classifier,label,reason_codes,version,input_digest,classified_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (ref_hash, classifier, *current, classification.timestamp),
                )
            cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
            db.execute("DELETE FROM classification_history WHERE classified_at<?", (cutoff,))
            db.execute(
                "DELETE FROM classification_history WHERE event_id NOT IN "
                "(SELECT event_id FROM classification_history ORDER BY event_id DESC LIMIT 10000)"
            )

    def classification_cache_stats(self) -> dict[str, Any]:
        with self._connect() as db:
            current = int(db.execute("SELECT COUNT(*) FROM classification_cache").fetchone()[0])
            history = int(db.execute("SELECT COUNT(*) FROM classification_history").fetchone()[0])
            assistant = int(db.execute("SELECT COUNT(*) FROM assistant_cache").fetchone()[0])
        return {
            "current_classifications": current,
            "history_events": history,
            "encrypted_assistant_results": assistant,
            "history_retention_days": 365,
            "history_max_events": 10000,
            "assistant_result_retention_days": 30,
            "assistant_result_max_entries": 500,
            "stores_mail_content": False,
            "assistant_results_protected_with_native_keystore": True,
            "reference_storage": "sha256",
        }

    @staticmethod
    def _assistant_scope(action: str, prompt_version: str) -> tuple[str, str]:
        if action not in {"summary", "actions"}:
            raise StateError("unsupported assistant cache action")
        if (
            not prompt_version
            or len(prompt_version) > 80
            or any(char in prompt_version for char in "\r\n\x00")
        ):
            raise StateError("invalid assistant prompt version")
        return action, prompt_version

    def save_assistant_result(
        self,
        message_ref: MessageRef,
        *,
        action: str,
        prompt_version: str,
        result: str,
        sources: list[MessageRef],
    ) -> dict[str, Any]:
        action, prompt_version = self._assistant_scope(action, prompt_version)
        if not result.strip() or "\x00" in result or len(result) > 20000:
            raise StateError("Assistant result must be 1..20000 characters without null bytes")
        if len(result.encode("utf-8")) > 65536:
            raise StateError("Assistant result exceeds the encrypted cache ceiling")
        if len(sources) > 6:
            raise StateError("Assistant cache is limited to six stable sources")
        payload = {
            "result": result,
            "sources": [source.as_dict() for source in sources],
        }
        protected = self.protector.protect(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(days=30)).isoformat()
        ref_hash = _hash("message-ref-v1", json.dumps(message_ref.as_dict(), sort_keys=True))
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO assistant_cache(ref_hash,action,prompt_version,protected_payload,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(ref_hash,action,prompt_version) DO UPDATE SET "
                "protected_payload=excluded.protected_payload,created_at=excluded.created_at,expires_at=excluded.expires_at",
                (ref_hash, action, prompt_version, protected, created_at, expires_at),
            )
            db.execute("DELETE FROM assistant_cache WHERE expires_at<?", (created_at,))
            db.execute(
                "DELETE FROM assistant_cache WHERE rowid NOT IN "
                "(SELECT rowid FROM assistant_cache ORDER BY created_at DESC LIMIT 500)"
            )
        return {"created_at": created_at, "expires_at": expires_at}

    def load_assistant_result(
        self,
        message_ref: MessageRef,
        *,
        action: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        action, prompt_version = self._assistant_scope(action, prompt_version)
        ref_hash = _hash("message-ref-v1", json.dumps(message_ref.as_dict(), sort_keys=True))
        with self._connect() as db:
            row = db.execute(
                "SELECT protected_payload,created_at,expires_at FROM assistant_cache "
                "WHERE ref_hash=? AND action=? AND prompt_version=?",
                (ref_hash, action, prompt_version),
            ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(str(row[2])) <= datetime.now(timezone.utc):
            with self._lock, self._connect() as db:
                db.execute(
                    "DELETE FROM assistant_cache WHERE ref_hash=? AND action=? AND prompt_version=?",
                    (ref_hash, action, prompt_version),
                )
            return None
        try:
            payload = dict(json.loads(self.protector.unprotect(row[0]).decode("utf-8")))
            result = str(payload["result"])
            sources = [MessageRef.from_mapping(value) for value in payload.get("sources", [])]
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateError("encrypted assistant cache entry is invalid") from exc
        if not result.strip() or len(result) > 20000 or len(sources) > 6:
            raise StateError("encrypted assistant cache entry exceeds its bounds")
        return {
            "result": result,
            "sources": [source.as_dict() for source in sources],
            "created_at": str(row[1]),
            "expires_at": str(row[2]),
        }

    def record_move(self, account_id: str, source: MessageRef, details: Mapping[str, Any]) -> str:
        receipt_id = secrets.token_hex(12)
        protected = self.protector.protect(json.dumps(details, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO moves(receipt_id,account_hash,ref_hash,protected_details,created_at) VALUES(?,?,?,?,?)",
                (
                    receipt_id,
                    _hash("account-v1", account_id),
                    _hash("message-ref-v1", json.dumps(source.as_dict(), sort_keys=True)),
                    protected,
                    now,
                ),
            )
        return receipt_id

    def get_move(self, receipt_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT protected_details, restored_at FROM moves WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        if row is None:
            raise StateError("restore receipt is unknown")
        if row[1] is not None:
            raise StateError("restore receipt was already used")
        return dict(json.loads(self.protector.unprotect(row[0]).decode("utf-8")))

    def mark_restored(self, receipt_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE moves SET restored_at=? WHERE receipt_id=? AND restored_at IS NULL", (now, receipt_id)
            )
            if cursor.rowcount != 1:
                raise StateError("restore receipt is unavailable")

    def send_outcome(self, digest: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT outcome FROM sends WHERE message_digest=?", (digest,)).fetchone()
        return str(row[0]) if row else None

    def record_send_attempt(self, digest: str, outcome: str, correlation_id: str) -> None:
        if outcome not in {"attempting", "sent", "ambiguous", "failed_known"}:
            raise StateError("invalid send outcome")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            existing = db.execute("SELECT outcome FROM sends WHERE message_digest=?", (digest,)).fetchone()
            if existing and existing[0] in {"attempting", "sent", "ambiguous"}:
                raise StateError("duplicate or ambiguous send is blocked")
            db.execute(
                "INSERT INTO sends(message_digest,outcome,correlation_id,attempted_at) VALUES(?,?,?,?) "
                "ON CONFLICT(message_digest) DO UPDATE SET outcome=excluded.outcome,"
                "correlation_id=excluded.correlation_id,attempted_at=excluded.attempted_at",
                (digest, outcome, correlation_id, now),
            )

    def update_send_outcome(self, digest: str, outcome: str) -> None:
        if outcome not in {"sent", "ambiguous", "failed_known"}:
            raise StateError("invalid final send outcome")
        with self._lock, self._connect() as db:
            cursor = db.execute("UPDATE sends SET outcome=? WHERE message_digest=?", (outcome, digest))
            if cursor.rowcount != 1:
                raise StateError("send attempt ledger entry is missing")

    def sends_since(self, minutes: int = 10) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM sends WHERE attempted_at>=? AND outcome IN ('attempting','sent','ambiguous')",
                (cutoff,),
            ).fetchone()
        return int(row[0])
