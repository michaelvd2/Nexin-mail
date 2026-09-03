from __future__ import annotations

import platform
from pathlib import Path

import pytest

from imap_plugin.config import state_root
from imap_plugin.credentials import MacKeychainCredentialStore


def _requirement_blocks(path: Path) -> list[str]:
    blocks: list[str] = []
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        blocks.append(current)
        current = ""
    assert not current
    return blocks


def test_dependency_locks_are_exact_and_hash_anchored():
    root = Path(__file__).parents[1]
    for lock_name in ("requirements-runtime.lock", "requirements-dev.lock"):
        blocks = _requirement_blocks(root / lock_name)
        assert blocks
        assert all("==" in block and "--hash=sha256:" in block for block in blocks)


def test_customer_installers_require_hashes_before_installing_code():
    root = Path(__file__).parents[1]
    macos = (root / "scripts" / "install_macos.sh").read_text(encoding="utf-8")
    windows = (root / "scripts" / "build_runtime.ps1").read_text(encoding="utf-8")
    assert "--require-hashes" in macos
    assert windows.count("--require-hashes") >= 2


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires macOS")
def test_macos_state_uses_application_support():
    path = state_root()
    assert path == Path.home() / "Library" / "Application Support" / "IMAP Plugin"


@pytest.mark.skipif(platform.system() != "Darwin", reason="requires macOS")
def test_macos_keychain_frameworks_load_without_accessing_a_secret():
    store = MacKeychainCredentialStore()
    assert store._SERVICE == b"org.openai.codex.imap-plugin"
