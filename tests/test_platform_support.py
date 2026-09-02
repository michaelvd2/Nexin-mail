from __future__ import annotations

import platform
from pathlib import Path

import pytest

from imap_plugin.config import state_root
from imap_plugin.credentials import MacKeychainCredentialStore


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires macOS")
def test_macos_state_uses_application_support():
    path = state_root()
    assert path == Path.home() / "Library" / "Application Support" / "IMAP Plugin"


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires macOS")
def test_macos_keychain_frameworks_load_without_accessing_a_secret():
    store = MacKeychainCredentialStore()
    assert store._SERVICE == b"org.openai.codex.imap-plugin"
