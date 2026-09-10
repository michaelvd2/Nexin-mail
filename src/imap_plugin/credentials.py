from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
from ctypes.util import find_library
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CredentialError(RuntimeError):
    pass


class CredentialNotFoundError(CredentialError):
    """The requested native credential target does not exist."""


@dataclass(frozen=True)
class CredentialMetadata:
    target: str
    credential_type: int
    persist: int
    blob_size: int
    last_written_utc: str


if os.name == "nt":
    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]


class WindowsCredentialStore:
    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialError("Windows Credential Manager is unavailable")
        self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]

    @staticmethod
    def _bounded_target(target: str) -> str:
        if not isinstance(target, str) or not target or len(target) > 256 or any(char in target for char in "\r\n\x00"):
            raise CredentialError("credential target must be a bounded single-line value")
        return target

    def write_secret(self, target: str, secret: str) -> CredentialMetadata:
        target = self._bounded_target(target)
        if not secret:
            raise CredentialError("empty secrets are rejected")
        raw = secret.encode("utf-16-le")
        if len(raw) > 5120:
            raise CredentialError("secret exceeds Credential Manager limit")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        cred = CREDENTIALW()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(raw)
        cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = None
        if not self._advapi.CredWriteW(ctypes.byref(cred), 0):
            raise CredentialError(f"CredWriteW failed with Windows error {ctypes.get_last_error()}")
        metadata = self.metadata(target)
        if metadata.persist != CRED_PERSIST_LOCAL_MACHINE:
            raise CredentialError(f"credential persistence is {metadata.persist}, expected 2")
        return metadata

    def read_secret(self, target: str) -> str:
        target = self._bounded_target(target)
        ptr = ctypes.POINTER(CREDENTIALW)()
        if not self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                raise CredentialNotFoundError("credential unavailable")
            raise CredentialError("credential unavailable")
        try:
            cred = ptr.contents
            if cred.Persist != CRED_PERSIST_LOCAL_MACHINE:
                raise CredentialError(f"unsafe credential persistence {cred.Persist}")
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(ptr)

    def metadata(self, target: str) -> CredentialMetadata:
        target = self._bounded_target(target)
        ptr = ctypes.POINTER(CREDENTIALW)()
        if not self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                raise CredentialNotFoundError("credential unavailable")
            raise CredentialError("credential unavailable")
        try:
            cred = ptr.contents
            ticks = (int(cred.LastWritten.dwHighDateTime) << 32) + int(cred.LastWritten.dwLowDateTime)
            unix_seconds = (ticks - 116444736000000000) / 10_000_000
            last_written = datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()
            return CredentialMetadata(target, int(cred.Type), int(cred.Persist), int(cred.CredentialBlobSize), last_written)
        finally:
            self._advapi.CredFree(ptr)

    def delete_secret(self, target: str) -> None:
        target = self._bounded_target(target)
        if self._advapi.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return
        if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND
            raise CredentialError("credential deletion failed")


class MacKeychainCredentialStore:
    """Current-user macOS Keychain storage without secrets in argv or files."""

    _SERVICE = b"org.openai.codex.imap-plugin"
    _ITEM_NOT_FOUND = -25300

    def __init__(self) -> None:
        if platform.system() != "Darwin":
            raise CredentialError("macOS Keychain is unavailable")
        security_path = find_library("Security") or "/System/Library/Frameworks/Security.framework/Security"
        core_foundation_path = find_library("CoreFoundation") or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        try:
            self._security = ctypes.CDLL(security_path)
            self._core_foundation = ctypes.CDLL(core_foundation_path)
        except OSError as exc:
            raise CredentialError("macOS Keychain frameworks are unavailable") from exc

        uint32 = ctypes.c_uint32
        void_p = ctypes.c_void_p
        self._security.SecKeychainFindGenericPassword.argtypes = [
            void_p, uint32, ctypes.c_char_p, uint32, ctypes.c_char_p,
            ctypes.POINTER(uint32), ctypes.POINTER(void_p), ctypes.POINTER(void_p),
        ]
        self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainAddGenericPassword.argtypes = [
            void_p, uint32, ctypes.c_char_p, uint32, ctypes.c_char_p, uint32, ctypes.c_char_p, ctypes.POINTER(void_p),
        ]
        self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainItemModifyAttributesAndData.argtypes = [void_p, void_p, uint32, ctypes.c_char_p]
        self._security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self._security.SecKeychainItemDelete.argtypes = [void_p]
        self._security.SecKeychainItemDelete.restype = ctypes.c_int32
        self._security.SecKeychainItemFreeContent.argtypes = [void_p, void_p]
        self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        self._core_foundation.CFRelease.argtypes = [void_p]

    @staticmethod
    def _bounded_target(target: str) -> bytes:
        if not target or len(target) > 256 or any(char in target for char in "\r\n\x00"):
            raise CredentialError("credential target must be a bounded single-line value")
        return target.encode("utf-8")

    def _find(self, target: str) -> tuple[int, bytes, ctypes.c_void_p]:
        account = self._bounded_target(target)
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = int(self._security.SecKeychainFindGenericPassword(
            None,
            len(self._SERVICE),
            self._SERVICE,
            len(account),
            account,
            ctypes.byref(length),
            ctypes.byref(data),
            ctypes.byref(item),
        ))
        if status != 0:
            return status, b"", item
        try:
            value = ctypes.string_at(data, length.value)
        finally:
            self._security.SecKeychainItemFreeContent(None, data)
        return 0, value, item

    def write_secret(self, target: str, secret: str) -> CredentialMetadata:
        if not secret:
            raise CredentialError("empty secrets are rejected")
        raw = secret.encode("utf-8")
        if len(raw) > 4096:
            raise CredentialError("secret exceeds the Keychain storage limit")
        account = self._bounded_target(target)
        status, _, item = self._find(target)
        if status == 0:
            try:
                update_status = int(self._security.SecKeychainItemModifyAttributesAndData(
                    item, None, len(raw), raw,
                ))
            finally:
                if item:
                    self._core_foundation.CFRelease(item)
            if update_status != 0:
                raise CredentialError(f"Keychain update failed with OSStatus {update_status}")
        elif status == self._ITEM_NOT_FOUND:
            created = ctypes.c_void_p()
            add_status = int(self._security.SecKeychainAddGenericPassword(
                None,
                len(self._SERVICE),
                self._SERVICE,
                len(account),
                account,
                len(raw),
                raw,
                ctypes.byref(created),
            ))
            if created:
                self._core_foundation.CFRelease(created)
            if add_status != 0:
                raise CredentialError(f"Keychain write failed with OSStatus {add_status}")
        else:
            raise CredentialError(f"Keychain lookup failed with OSStatus {status}")
        return self.metadata(target)

    def read_secret(self, target: str) -> str:
        status, value, item = self._find(target)
        if item:
            self._core_foundation.CFRelease(item)
        if status == self._ITEM_NOT_FOUND:
            raise CredentialNotFoundError("credential unavailable")
        if status != 0:
            raise CredentialError(f"Keychain read failed with OSStatus {status}")
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CredentialError("Keychain credential is not valid UTF-8") from exc

    def metadata(self, target: str) -> CredentialMetadata:
        status, value, item = self._find(target)
        if item:
            self._core_foundation.CFRelease(item)
        if status == self._ITEM_NOT_FOUND:
            raise CredentialNotFoundError("credential unavailable")
        if status != 0:
            raise CredentialError(f"Keychain lookup failed with OSStatus {status}")
        return CredentialMetadata(
            target=target,
            credential_type=CRED_TYPE_GENERIC,
            persist=CRED_PERSIST_LOCAL_MACHINE,
            blob_size=len(value),
            last_written_utc="",
        )

    def delete_secret(self, target: str) -> None:
        status, _, item = self._find(target)
        if status == self._ITEM_NOT_FOUND:
            return
        if status != 0:
            raise CredentialError("Keychain lookup failed")
        try:
            delete_status = int(self._security.SecKeychainItemDelete(item))
        finally:
            if item:
                self._core_foundation.CFRelease(item)
        if delete_status != 0:
            raise CredentialError("Keychain deletion failed")


class SecretBackend(Protocol):
    """The small native-keystore surface required by chunked persistence."""

    def write_secret(self, target: str, secret: str) -> CredentialMetadata: ...

    def read_secret(self, target: str) -> str: ...

    def delete_secret(self, target: str) -> None: ...


class ChunkedSecretStore:
    """Bounded, generation-based storage for opaque keystore values.

    Each generation is written to exact native credential targets and verified
    before the active pointer is switched. A previous pointer is retained
    during that switch so a failed or interrupted write can recover the last
    valid generation. The class never enumerates or deletes arbitrary native
    credentials.
    """

    VERSION = 1
    CHUNK_CHARS = 1024
    MAX_POINTER_CHARS = 512
    MAX_CHUNKS = 128
    _TARGET_RE = re.compile(r"^imap-plugin/oauth-cache/[A-Za-z0-9._-]{1,64}$")
    _GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")

    def __init__(
        self,
        backend: SecretBackend,
        target: str,
        *,
        chunk_chars: int = CHUNK_CHARS,
        max_chunks: int = MAX_CHUNKS,
    ) -> None:
        if not isinstance(target, str) or self._TARGET_RE.fullmatch(target) is None:
            raise CredentialError("chunked credential target is invalid")
        if not 128 <= int(chunk_chars) <= self.CHUNK_CHARS:
            raise CredentialError("chunk size is outside the safe bound")
        if not 1 <= int(max_chunks) <= self.MAX_CHUNKS:
            raise CredentialError("chunk count is outside the safe bound")
        self.backend = backend
        self.target = target
        self.chunk_chars = int(chunk_chars)
        self.max_chunks = int(max_chunks)
        self._index_target = f"{target}/index"
        self._previous_target = f"{target}/previous"
        if len(self._index_target) > 256 or len(self._previous_target) > 256:
            raise CredentialError("chunked credential target is too long")

    @staticmethod
    def _not_found(error: BaseException) -> bool:
        return isinstance(error, (CredentialNotFoundError, KeyError)) or "unavailable" in str(error).casefold()

    def _read_target(self, target: str) -> str:
        try:
            value = self.backend.read_secret(target)
        except Exception as exc:
            if self._not_found(exc):
                raise CredentialNotFoundError("credential unavailable") from exc
            raise
        if not isinstance(value, str):
            raise CredentialError("credential value is not text")
        return value

    def _write_target(self, target: str, value: str) -> None:
        try:
            self.backend.write_secret(target, value)
        except CredentialError:
            raise
        except Exception as exc:
            raise CredentialError("credential write failed") from exc

    def _delete_target(self, target: str) -> None:
        delete = getattr(self.backend, "delete_secret", None)
        if not callable(delete):
            return
        try:
            delete(target)
        except Exception as exc:
            if not self._not_found(exc):
                # Cleanup is best effort. The active verified generation is
                # already safe; retaining an owned old entry is preferable to
                # turning a successful write into an ambiguous state.
                return

    @staticmethod
    def _pointer_json(pointer: dict[str, Any]) -> str:
        return json.dumps(pointer, separators=(",", ":"), sort_keys=True)

    def _decode_pointer(self, value: str) -> dict[str, Any]:
        if not isinstance(value, str) or not 1 <= len(value) <= self.MAX_POINTER_CHARS:
            raise CredentialError("credential index is corrupt")
        try:
            pointer = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise CredentialError("credential index is corrupt") from exc
        if not isinstance(pointer, dict):
            raise CredentialError("credential index is corrupt")
        required = {"version", "generation", "chunks", "length", "sha256"}
        if set(pointer) != required or pointer.get("version") != self.VERSION:
            raise CredentialError("credential index is corrupt")
        generation = pointer.get("generation")
        chunks = pointer.get("chunks")
        length = pointer.get("length")
        digest = pointer.get("sha256")
        if (
            not isinstance(generation, str)
            or self._GENERATION_RE.fullmatch(generation) is None
            or type(chunks) is not int
            or not 1 <= chunks <= self.max_chunks
            or type(length) is not int
            or not 1 <= length <= self.max_chunks * self.chunk_chars
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise CredentialError("credential index is corrupt")
        return {
            "version": self.VERSION,
            "generation": generation,
            "chunks": chunks,
            "length": length,
            "sha256": digest,
        }

    def _chunk_target(self, generation: str, index: int) -> str:
        target = f"{self.target}/g-{generation}/p-{index:04d}"
        if len(target) > 256:
            raise CredentialError("chunk target is too long")
        return target

    def _payload_for_pointer(self, pointer: dict[str, Any]) -> str:
        chunks = []
        for index in range(pointer["chunks"]):
            chunk = self._read_target(self._chunk_target(pointer["generation"], index))
            if not 1 <= len(chunk) <= self.chunk_chars:
                raise CredentialError("credential chunk exceeds its bounded size")
            chunks.append(chunk)
        payload = "".join(chunks)
        try:
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except UnicodeEncodeError as exc:
            raise CredentialError("credential chunks failed integrity validation") from exc
        if len(payload) != pointer["length"] or digest != pointer["sha256"]:
            raise CredentialError("credential chunks failed integrity validation")
        return payload

    def _pointer_payload(self, target: str) -> tuple[dict[str, Any], str]:
        raw = self._read_target(target)
        pointer = self._decode_pointer(raw)
        return pointer, self._payload_for_pointer(pointer)

    def read(self) -> str:
        active_error: CredentialError | None = None
        try:
            return self._pointer_payload(self._index_target)[1]
        except CredentialNotFoundError:
            pass
        except CredentialError as exc:
            active_error = exc
        try:
            return self._pointer_payload(self._previous_target)[1]
        except CredentialNotFoundError:
            if active_error is not None:
                raise active_error
            raise CredentialNotFoundError("credential unavailable")
        except CredentialError:
            if active_error is not None:
                raise active_error
            raise

    def read_optional(self) -> str | None:
        try:
            return self.read()
        except CredentialNotFoundError:
            return None

    def _current_pointer(self) -> dict[str, Any] | None:
        try:
            raw = self._read_target(self._index_target)
        except CredentialNotFoundError:
            return None
        try:
            pointer = self._decode_pointer(raw)
            self._payload_for_pointer(pointer)
            return pointer
        except CredentialError as active_error:
            # A process may have switched the pointer and stopped before all
            # new chunks were durable. Reuse the verified previous generation
            # for the next rotation instead of leaving repair permanently
            # blocked on a corrupt active pointer.
            try:
                previous, _ = self._pointer_payload(self._previous_target)
                return previous
            except CredentialError:
                raise active_error

    def _cleanup_generation(self, pointer: dict[str, Any]) -> None:
        for index in range(pointer["chunks"]):
            self._delete_target(self._chunk_target(pointer["generation"], index))

    def write(self, payload: str) -> None:
        if not isinstance(payload, str) or not payload:
            raise CredentialError("empty credential payload is rejected")
        if len(payload) > self.max_chunks * self.chunk_chars:
            raise CredentialError("credential payload exceeds the bounded keystore capacity")
        old_pointer = self._current_pointer()
        if old_pointer is not None:
            old_index = self._pointer_json(old_pointer)
            self._write_target(self._previous_target, old_index)
            if self._read_target(self._previous_target) != old_index:
                raise CredentialError("previous credential pointer could not be verified")

        generation = secrets.token_hex(16)
        if old_pointer is not None and generation == old_pointer["generation"]:
            raise CredentialError("credential generation collision")
        chunks = [payload[index:index + self.chunk_chars] for index in range(0, len(payload), self.chunk_chars)]
        try:
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except UnicodeEncodeError as exc:
            raise CredentialError("credential payload is not valid UTF-8") from exc
        pointer = {
            "version": self.VERSION,
            "generation": generation,
            "chunks": len(chunks),
            "length": len(payload),
            "sha256": digest,
        }
        written_targets: list[str] = []
        try:
            for index, chunk in enumerate(chunks):
                target = self._chunk_target(generation, index)
                written_targets.append(target)
                self._write_target(target, chunk)
            for index, chunk in enumerate(chunks):
                if self._read_target(self._chunk_target(generation, index)) != chunk:
                    raise CredentialError("credential chunk could not be verified")
            # Include the active pointer before the write: a backend can
            # report an interruption after its native write has taken effect.
            written_targets.append(self._index_target)
            self._write_target(self._index_target, self._pointer_json(pointer))
            if self.read() != payload:
                raise CredentialError("credential pointer switch could not be verified")
        except Exception:
            for target in written_targets:
                self._delete_target(target)
            raise

        if old_pointer is not None:
            self._cleanup_generation(old_pointer)
        self._delete_target(self._previous_target)

    def metadata(self) -> CredentialMetadata:
        payload = self.read()
        return CredentialMetadata(
            target=self.target,
            credential_type=CRED_TYPE_GENERIC,
            persist=CRED_PERSIST_LOCAL_MACHINE,
            blob_size=len(payload.encode("utf-8")),
            last_written_utc="",
        )


# Descriptive compatibility alias for callers that prefer the storage role.
CredentialChunkStore = ChunkedSecretStore


def platform_store() -> WindowsCredentialStore | MacKeychainCredentialStore:
    if os.name == "nt":
        return WindowsCredentialStore()
    if platform.system() == "Darwin":
        return MacKeychainCredentialStore()
    raise CredentialError("no proven native credential backend is available on this platform")


def masked_enroll(target: str) -> CredentialMetadata:
    first = getpass.getpass("Mailbox password (masked, local only): ")
    second = getpass.getpass("Confirm mailbox password: ")
    if first != second:
        raise CredentialError("entries did not match")
    return platform_store().write_secret(target, first)
