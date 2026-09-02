from __future__ import annotations

import ctypes
import getpass
import os
import platform
from ctypes.util import find_library
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CredentialError(RuntimeError):
    pass


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
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]

    def write_secret(self, target: str, secret: str) -> CredentialMetadata:
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
        ptr = ctypes.POINTER(CREDENTIALW)()
        if not self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            raise CredentialError(f"credential unavailable for target {target}")
        try:
            cred = ptr.contents
            if cred.Persist != CRED_PERSIST_LOCAL_MACHINE:
                raise CredentialError(f"unsafe credential persistence {cred.Persist}")
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(ptr)

    def metadata(self, target: str) -> CredentialMetadata:
        ptr = ctypes.POINTER(CREDENTIALW)()
        if not self._advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
            raise CredentialError(f"credential unavailable for target {target}")
        try:
            cred = ptr.contents
            ticks = (int(cred.LastWritten.dwHighDateTime) << 32) + int(cred.LastWritten.dwLowDateTime)
            unix_seconds = (ticks - 116444736000000000) / 10_000_000
            last_written = datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()
            return CredentialMetadata(target, int(cred.Type), int(cred.Persist), int(cred.CredentialBlobSize), last_written)
        finally:
            self._advapi.CredFree(ptr)


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
            raise CredentialError(f"credential unavailable for target {target}")
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
            raise CredentialError(f"credential unavailable for target {target}")
        if status != 0:
            raise CredentialError(f"Keychain lookup failed with OSStatus {status}")
        return CredentialMetadata(
            target=target,
            credential_type=CRED_TYPE_GENERIC,
            persist=CRED_PERSIST_LOCAL_MACHINE,
            blob_size=len(value),
            last_written_utc="",
        )


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
