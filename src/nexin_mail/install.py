"""Safe local installation, update, rollback, migration, and removal.

The installer never starts a mailbox setup and never stops a running server.
It verifies a release before copying it, keeps every verified payload under
its manifest hash, and treats the Codex registry as derived state.  Registry
switches use a small journal so an interrupted two-file switch can be repaired
on the next invocation without replacing an unknown registration.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import uuid
from typing import Any, Callable

from . import __version__
from .diagnostics import event, report, save_report
from .package import (
    MCP_SERVER_NAME,
    PackageError,
    digest,
    registration,
    verify,
)

PRODUCT = "nexin-mail"
MARKETPLACE_NAME = "nexin-mail"
LEGACY_MARKETPLACE_NAME = "imap-plugin-handoff"
REGISTRY_SCHEMA = 2
_REPARSE_POINT = 0x400
_HASH_LENGTH = 64
_HASH_CHARS = frozenset("0123456789abcdef")
_MACOS_METADATA_NAME = ".DS_Store"
_SAFE_MODE_BITS = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
Runner = Callable[..., str]


class InstallError(RuntimeError):
    """A typed, non-secret installer failure."""

    def __init__(self, code: str, stage: str):
        self.code, self.stage = code, stage
        super().__init__(code)


def _is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def _absolute(path: Path | str) -> Path:
    # abspath is intentional: this preserves a link in the input so it can be
    # rejected by _assert_no_links before resolve() follows it.
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_links(path: Path | str, *, error: str = "installation_conflict", stage: str = "registration") -> Path:
    """Reject symlink/reparse components in an installation-owned path."""

    value = _absolute(path)
    current = value
    while True:
        if current.is_symlink() or _is_reparse(current):
            raise InstallError(error, stage)
        if current.parent == current:
            break
        current = current.parent
    return value


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _HASH_LENGTH and not (set(value) - _HASH_CHARS)


def _same_path(left: Path | str, right: Path | str) -> bool:
    """Compare a Codex path without resolving through an untrusted link."""

    left_text, right_text = os.fspath(left), os.fspath(right)
    if ntpath.isabs(left_text) or ntpath.isabs(right_text):
        return ntpath.normcase(ntpath.normpath(left_text)) == ntpath.normcase(ntpath.normpath(right_text))
    return os.path.normcase(os.path.abspath(left_text)) == os.path.normcase(os.path.abspath(right_text))


def _path_under(candidate: Path | str, root: Path | str) -> bool:
    candidate_text, root_text = os.fspath(candidate), os.fspath(root)
    if ntpath.isabs(candidate_text) or ntpath.isabs(root_text):
        candidate_norm = ntpath.normcase(ntpath.normpath(candidate_text)).rstrip("\\/")
        root_norm = ntpath.normcase(ntpath.normpath(root_text)).rstrip("\\/")
        return candidate_norm == root_norm or candidate_norm.startswith(root_norm + "\\")
    candidate_norm = os.path.normcase(os.path.abspath(candidate_text)).rstrip(os.sep)
    root_norm = os.path.normcase(os.path.abspath(root_text)).rstrip(os.sep)
    return candidate_norm == root_norm or candidate_norm.startswith(root_norm + os.sep)


def _write_atomic_bytes(target: Path, content: bytes) -> None:
    target = _absolute(target)
    _assert_no_links(target.parent)
    if target.exists() and (target.is_symlink() or _is_reparse(target)):
        raise InstallError("installation_conflict", "registration")
    temporary = target.parent / (f".{target.name}.tmp-{uuid.uuid4().hex}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor != -1:
                os.close(descriptor)
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise InstallError("filesystem_failed", "registration") from exc


def _write_atomic_json(target: Path, value: dict[str, Any]) -> None:
    _write_atomic_bytes(target, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _read_json(path: Path, *, stage: str = "registration") -> Any:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        if path.is_symlink() or _is_reparse(path) or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise InstallError("installation_conflict", stage) from exc


def run(command: list[str], *, timeout: int = 90) -> str:
    """Run a native command without a shell and return bounded-use stdout.

    Callers inspect only structured JSON or exact sentinels.  Stderr is never
    relayed into a report or exception because it could contain private data.
    """

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise InstallError("codex_failed", "host")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallError("codex_failed", "host") from exc
    if result.returncode:
        raise InstallError("codex_failed", "host")
    return result.stdout


def codex_identity(codex: Path | str, config_root: Path | str | None = None) -> dict[str, str | bool | None]:
    """Return a minimal native-host identity after rejecting WSL paths."""

    raw = os.fspath(codex)
    folded = raw.casefold()
    config_value = config_root if config_root is not None else os.environ.get("CODEX_CONFIG_DIR") or os.environ.get("CODEX_HOME")
    config_raw = os.fspath(config_value) if config_value is not None else None
    wsl_markers = ("\\\\wsl$", "/mnt/", "wsl.exe")
    if any(marker in folded for marker in wsl_markers) or os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        raise InstallError("codex_config_mismatch", "host")
    if config_raw is not None:
        config_folded = config_raw.casefold()
        if not config_raw or any(marker in config_folded for marker in wsl_markers):
            raise InstallError("codex_config_mismatch", "host")
        if not ntpath.isabs(config_raw) and not Path(config_raw).is_absolute():
            raise InstallError("codex_config_mismatch", "host")
        config_path = _absolute(config_raw)
        config_text: str | None = str(config_path)
    else:
        config_text = None
    return {"executable": str(_absolute(codex)), "config_root": config_text, "native": True}


def preflight(codex: str | None = None, *, config_root: str | None = None) -> Path:
    """Check platform, architecture, executable identity, and host context."""

    if sys.platform != "win32":
        raise InstallError("platform_unsupported", "host")
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine()
    if arch.casefold() not in {"amd64", "x86_64"}:
        raise InstallError("architecture_unverified", "host")
    candidate = codex or shutil.which("codex.exe")
    if not candidate or not Path(candidate).is_file():
        raise InstallError("codex_missing", "host")
    candidate_path = _absolute(candidate)
    if candidate_path.suffix.casefold() != ".exe":
        raise InstallError("codex_unsupported", "host")
    _assert_no_links(candidate_path, error="codex_config_mismatch", stage="host")
    try:
        codex_identity(candidate_path, config_root)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError("codex_config_mismatch", "host") from exc
    return candidate_path


def preflight_macos(codex: str | None = None, *, config_root: str | None = None) -> Path:
    """Check the native macOS Codex executable without assuming a shell shim."""

    if sys.platform != "darwin":
        raise InstallError("platform_unsupported", "host")
    candidate = codex or shutil.which("codex")
    if not candidate or not Path(candidate).is_file():
        raise InstallError("codex_missing", "host")
    candidate_path = _absolute(candidate)
    if candidate_path.suffix.casefold() in {".cmd", ".bat", ".ps1", ".sh"}:
        raise InstallError("codex_unsupported", "host")
    _assert_no_links(candidate_path, error="codex_config_mismatch", stage="host")
    codex_identity(candidate_path, config_root)
    return candidate_path


def read_marketplaces(output: str) -> list[dict[str, str]]:
    """Parse only the small Codex marketplace projection used by the installer."""

    try:
        data = json.loads(output)
        rows = data["marketplaces"]
        if not isinstance(rows, list) or len(rows) > 64:
            raise ValueError
        clean: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - {"name", "root", "marketplaceSource"}:
                raise ValueError
            name, root = row.get("name"), row.get("root")
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ValueError
            if not isinstance(root, str) or not root or "\x00" in root or len(root) > 4_096:
                raise ValueError
            if "marketplaceSource" in row:
                source = row["marketplaceSource"]
                if not isinstance(source, dict) or set(source) != {"sourceType", "source"}:
                    raise ValueError
                source_type, source_value = source["sourceType"], source["source"]
                if (
                    not isinstance(source_type, str) or not source_type or "\x00" in source_type or len(source_type) > 64
                    or not isinstance(source_value, str) or not source_value or "\x00" in source_value or len(source_value) > 4_096
                ):
                    raise ValueError
            clean.append({"name": name, "root": root})
        return clean
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InstallError("codex_unsupported", "host") from exc


def _copy_verified_tree(source: Path, target: Path) -> None:
    """Copy a verified tree without following links or preserving host paths."""

    source = _absolute(source)
    target = _absolute(target)
    _assert_no_links(target.parent)
    if source.is_symlink() or _is_reparse(source) or not source.is_dir():
        raise InstallError("package_invalid", "package")
    target.mkdir(parents=True, exist_ok=False)
    try:
        paths = sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix().casefold())
        for item in paths:
            relative = item.relative_to(source)
            destination = target / relative
            if item.is_symlink() or _is_reparse(item):
                raise InstallError("package_invalid", "package")
            if item.is_dir():
                destination.mkdir()
                destination.chmod(stat.S_IMODE(item.stat().st_mode) & _SAFE_MODE_BITS)
            elif item.is_file():
                if item.name == _MACOS_METADATA_NAME:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, destination)
                destination.chmod(stat.S_IMODE(item.stat().st_mode) & _SAFE_MODE_BITS)
            else:
                raise InstallError("package_invalid", "package")
    except OSError as exc:
        raise InstallError("filesystem_failed", "package") from exc


def _validate_owner(owner: Any) -> dict[str, Any]:
    if not isinstance(owner, dict):
        raise ValueError
    allowed = {"schema", "product", "package_hash", "previous_package_hash", "history"}
    if set(owner) - allowed:
        raise ValueError
    if owner.get("product") != PRODUCT or not _is_hash(owner.get("package_hash")):
        raise ValueError
    schema = owner.get("schema", 1)
    if type(schema) is not int or schema not in {1, REGISTRY_SCHEMA}:
        raise ValueError
    previous = owner.get("previous_package_hash")
    if previous is not None and not _is_hash(previous):
        raise ValueError
    history = owner.get("history", [owner["package_hash"]])
    if not isinstance(history, list) or not 1 <= len(history) <= 64 or any(not _is_hash(item) for item in history):
        raise ValueError
    if history[-1] != owner["package_hash"]:
        raise ValueError
    if len(set(history)) != len(history):
        raise ValueError
    if previous is not None and (previous == owner["package_hash"] or previous not in history):
        raise ValueError
    return {
        "schema": REGISTRY_SCHEMA,
        "product": PRODUCT,
        "package_hash": owner["package_hash"],
        "previous_package_hash": previous,
        "history": history,
    }


def _owner_path(registry: Path) -> Path:
    return registry / "nexin-mail-owner.json"


def _read_owner(registry: Path) -> dict[str, Any] | None:
    if not registry.exists():
        return None
    if registry.is_symlink() or _is_reparse(registry) or not registry.is_dir():
        raise InstallError("installation_conflict", "registration")
    marker = _owner_path(registry)
    if not marker.is_file():
        raise InstallError("installation_conflict", "registration")
    try:
        return _validate_owner(_read_json(marker))
    except (InstallError, ValueError) as exc:
        if isinstance(exc, InstallError):
            raise
        raise InstallError("installation_conflict", "registration") from exc


def _verify_package_at(path: Path, expected_hash: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or _is_reparse(path) or not path.is_dir():
            raise PackageError("invalid installed payload")
        manifest = path / "package-manifest.json"
        if digest(manifest) != expected_hash:
            raise PackageError("installed manifest changed")
        return verify(path)
    except (OSError, PackageError) as exc:
        raise InstallError("package_invalid", "package") from exc


def _stage_package(package: Path, destination: Path, package_hash: str, events: list[dict[str, Any]]) -> tuple[Path, bool]:
    packages = destination / "packages"
    try:
        _assert_no_links(packages)
        packages.mkdir(parents=True, exist_ok=True)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError("filesystem_failed", "package") from exc
    installed = packages / package_hash
    if installed.exists():
        _verify_package_at(installed, package_hash)
        events.append(event("package", "verified", "none", "stage_package"))
        return installed, False
    staging = packages / (".staging-" + uuid.uuid4().hex)
    try:
        _copy_verified_tree(package, staging)
        _verify_package_at(staging, package_hash)
        staging.rename(installed)
    except InstallError:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except OSError:
            pass
        raise InstallError("filesystem_failed", "package") from exc
    events.append(event("package", "verified", "none", "stage_package"))
    return installed, True


def _marketplace_rows(rows: list[dict[str, str]], name: str) -> list[dict[str, str]]:
    return [row for row in rows if row["name"] == name]


def _registry_relative_owned(relative: str) -> bool:
    return (
        relative in {
            "nexin-mail-owner.json", ".switch.json", ".agents", ".agents/plugins",
            ".agents/plugins/marketplace.json", "plugins", f"plugins/{PRODUCT}",
            f"plugins/{PRODUCT}/.codex-plugin", f"plugins/{PRODUCT}/skills",
            f"plugins/{PRODUCT}/.mcp.json", f"plugins/{PRODUCT}/.codex-plugin/plugin.json",
        }
        or relative.startswith(f"plugins/{PRODUCT}/skills/")
    )


def _registry_layout_is_known(registry: Path) -> bool:
    try:
        for item in registry.rglob("*"):
            if item.is_symlink() or _is_reparse(item):
                return False
            if not _registry_relative_owned(item.relative_to(registry).as_posix()):
                return False
    except OSError:
        return False
    return True


def _registry_is_ours(registry: Path, destination: Path) -> bool:
    """Check generated registry identity before any uninstall deletion."""

    owner = _read_owner(registry)
    if owner is None:
        return False
    wrapper = registry / "plugins" / PRODUCT
    plugin_path = wrapper / ".codex-plugin" / "plugin.json"
    marketplace_path = registry / ".agents" / "plugins" / "marketplace.json"
    try:
        plugin = _read_json(plugin_path)
        marketplace = _read_json(marketplace_path)
        active_plugin = _read_json(destination / "packages" / owner["package_hash"] / "plugin.json")
    except InstallError:
        return False
    if not isinstance(plugin, dict) or plugin != active_plugin:
        return False
    if not isinstance(marketplace, dict) or marketplace != _expected_marketplace():
        return False
    if not _mcp_shape_is_ours(registry / "plugins" / PRODUCT / ".mcp.json", destination):
        return False
    try:
        known_skill_files: set[str] = set()
        for package_hash in owner["history"]:
            skills_root = destination / "packages" / package_hash / "skills"
            if not skills_root.is_dir() or skills_root.is_symlink() or _is_reparse(skills_root):
                return False
            for item in skills_root.rglob("*"):
                if item.is_symlink() or _is_reparse(item):
                    return False
                if item.is_file():
                    known_skill_files.add(f"plugins/{PRODUCT}/skills/{item.relative_to(skills_root).as_posix()}")
        installed_skills = registry / "plugins" / PRODUCT / "skills"
        if not installed_skills.is_dir() or installed_skills.is_symlink() or _is_reparse(installed_skills):
            return False
        for item in installed_skills.rglob("*"):
            if item.is_file() and item.relative_to(registry).as_posix() not in known_skill_files:
                return False
    except OSError:
        return False
    # Uninstall is allowed to remove only files this installer can have
    # generated.  An unexpected file in the registry is treated as foreign.
    if not _registry_layout_is_known(registry):
        return False
    return True


def _mcp_shape_is_ours(path: Path, destination: Path) -> bool:
    try:
        value = _read_json(path)
    except InstallError:
        return False
    if not isinstance(value, dict) or set(value) != {"mcpServers"} or not isinstance(value["mcpServers"], dict):
        return False
    # A pre-update registry may contain the old dashboard entry.  It is still
    # ours when every command points into this installation's packages tree.
    names = set(value["mcpServers"])
    if not names or not names <= {MCP_SERVER_NAME, "dashboard"}:
        return False
    for config in value["mcpServers"].values():
        if not isinstance(config, dict) or not isinstance(config.get("command"), str) or not isinstance(config.get("cwd"), str):
            return False
        # Windows uses python.exe; a packaged macOS runtime may expose either
        # python or python3.  Compare the basename so both slash conventions
        # are handled while rejecting arbitrary executables.
        if ntpath.basename(config["command"]).casefold() not in {"python.exe", "python", "python3"}:
            return False
        packages_root = destination / "packages"
        if not _path_under(config["command"], packages_root) or not _path_under(config["cwd"], packages_root):
            return False
    return True


def _expected_marketplace() -> dict[str, Any]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Nexin Mail"},
        "plugins": [{
            "name": PRODUCT,
            "source": {"source": "local", "path": "./plugins/nexin-mail"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }],
    }


def _sync_skills(source: Path, target: Path) -> None:
    """Refresh generated skill files while preserving unknown files for review."""

    try:
        for item in sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix().casefold()):
            relative = item.relative_to(source)
            destination = target / relative
            if item.is_symlink() or _is_reparse(item):
                raise InstallError("package_invalid", "package")
            if item.is_dir():
                if destination.exists() and (destination.is_symlink() or _is_reparse(destination) or not destination.is_dir()):
                    raise InstallError("installation_conflict", "registration")
                destination.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                if destination.exists() and (destination.is_symlink() or _is_reparse(destination)):
                    raise InstallError("installation_conflict", "registration")
                content = item.read_bytes()
                if not destination.exists() or destination.read_bytes() != content:
                    _write_atomic_bytes(destination, content)
            else:
                raise InstallError("package_invalid", "package")
    except OSError as exc:
        raise InstallError("filesystem_failed", "registration") from exc


def _write_owner(registry: Path, active: str, previous: str | None, history: list[str]) -> dict[str, Any]:
    if not _is_hash(active) or (previous is not None and not _is_hash(previous)):
        raise InstallError("registration_failed", "registration")
    compact = [item for item in history if _is_hash(item) and item != active]
    compact.append(active)
    if len(compact) > 64:
        compact = compact[-64:]
    value = {
        "schema": REGISTRY_SCHEMA,
        "product": PRODUCT,
        "package_hash": active,
        "previous_package_hash": previous,
        "history": compact,
    }
    _write_atomic_json(_owner_path(registry), value)
    return value


def _journal_value(from_owner: dict[str, Any] | None, to_owner: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": 1,
        "product": PRODUCT,
        "from_owner": from_owner,
        "to_owner": to_owner,
    }


def _validate_journal(value: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"schema", "product", "from_owner", "to_owner"} or type(value["schema"]) is not int or value["schema"] != 1 or value["product"] != PRODUCT:
        raise ValueError
    from_owner = None if value["from_owner"] is None else _validate_owner(value["from_owner"])
    to_owner = _validate_owner(value["to_owner"])
    return from_owner, to_owner


def _write_registry_files(registry: Path, destination: Path, package_root: Path, metadata: dict[str, Any], owner: dict[str, Any], *, allow_legacy_mcp: bool = True) -> None:
    wrapper = registry / "plugins" / PRODUCT
    plugin_path = wrapper / ".codex-plugin" / "plugin.json"
    mcp_path = wrapper / ".mcp.json"
    marketplace_path = registry / ".agents" / "plugins" / "marketplace.json"
    for path in (registry, wrapper, plugin_path.parent, marketplace_path.parent):
        _assert_no_links(path)
    wrapper.mkdir(parents=True, exist_ok=True)
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    expected_mcp = registration(package_root / "payload", metadata["version"])
    if mcp_path.exists() and not _mcp_shape_is_ours(mcp_path, destination):
        raise InstallError("installation_conflict", "registration")
    source_plugin = package_root / "plugin.json"
    try:
        expected_plugin = _read_json(source_plugin)
    except InstallError:
        raise InstallError("package_invalid", "package")
    expected_existing_plugin = expected_plugin
    marker_path = _owner_path(registry)
    if marker_path.exists():
        existing_owner = _read_owner(registry)
        if existing_owner is None:
            raise InstallError("installation_conflict", "registration")
        if existing_owner["package_hash"] != owner["package_hash"]:
            try:
                expected_existing_plugin = _read_json(
                    destination / "packages" / existing_owner["package_hash"] / "plugin.json"
                )
            except InstallError:
                raise InstallError("package_invalid", "package")
    if plugin_path.exists():
        try:
            plugin_value = _read_json(plugin_path)
        except InstallError:
            raise
        if plugin_value != expected_existing_plugin:
            raise InstallError("installation_conflict", "registration")
    if marketplace_path.exists():
        try:
            marketplace_value = _read_json(marketplace_path)
        except InstallError:
            raise
        if marketplace_value != _expected_marketplace():
            raise InstallError("installation_conflict", "registration")
    if marker_path.exists():
        existing_owner = _read_owner(registry)
        if existing_owner is None or (
            existing_owner["package_hash"] not in owner["history"]
            and owner["package_hash"] not in existing_owner["history"]
        ):
            raise InstallError("installation_conflict", "registration")
    _write_atomic_json(mcp_path, expected_mcp)
    # The plugin manifest and marketplace description are derived metadata;
    # they may change with a package version but are still written atomically.
    try:
        _write_atomic_bytes(plugin_path, source_plugin.read_bytes())
    except OSError as exc:
        raise InstallError("filesystem_failed", "registration") from exc
    source_skills = package_root / "skills"
    target_skills = wrapper / "skills"
    if not source_skills.is_dir() or source_skills.is_symlink() or _is_reparse(source_skills):
        raise InstallError("package_invalid", "package")
    if target_skills.exists():
        _assert_no_links(target_skills)
    if not target_skills.exists():
        try:
            _copy_verified_tree(source_skills, target_skills)
        except InstallError:
            raise
    else:
        _sync_skills(source_skills, target_skills)
    _write_atomic_json(marketplace_path, _expected_marketplace())
    _write_atomic_json(_owner_path(registry), owner)


def _recover_registry(registry: Path, destination: Path) -> dict[str, Any] | None:
    """Complete or repair a journaled switch using only owned packages."""

    _assert_no_links(registry)
    if not registry.exists():
        return None
    journal_path = registry / ".switch.json"
    if journal_path.exists():
        try:
            from_owner, to_owner = _validate_journal(_read_json(journal_path))
        except (InstallError, ValueError) as exc:
            raise InstallError("installation_conflict", "registration") from exc
        marker = _owner_path(registry)
        if marker.is_symlink() or _is_reparse(marker):
            raise InstallError("installation_conflict", "registration")
        current = _read_owner(registry) if marker.exists() else None
        if current is None and from_owner is not None:
            raise InstallError("installation_conflict", "registration")
        if current is None and not _registry_layout_is_known(registry):
            raise InstallError("installation_conflict", "registration")
        if current is None:
            # A first-install process may have been interrupted before its
            # owner marker was atomically written.  With no prior owner, the
            # journal's verified target is the only safe recovery candidate.
            chosen = to_owner
        elif current["package_hash"] == to_owner["package_hash"]:
            chosen = to_owner
        elif from_owner is not None and current["package_hash"] == from_owner["package_hash"]:
            chosen = from_owner
        else:
            raise InstallError("installation_conflict", "registration")
        package_root = destination / "packages" / chosen["package_hash"]
        metadata = _verify_package_at(package_root, chosen["package_hash"])
        _write_registry_files(registry, destination, package_root, metadata, chosen)
        try:
            journal_path.unlink()
        except OSError as exc:
            raise InstallError("filesystem_failed", "registration") from exc
        return chosen
    return _read_owner(registry)


def _switch_registry(registry: Path, destination: Path, package_root: Path, metadata: dict[str, Any], current: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    target_hash = digest(package_root / "package-manifest.json")
    if current is not None and current["package_hash"] == target_hash:
        _write_registry_files(registry, destination, package_root, metadata, current)
        return current, False
    previous_hash = current["package_hash"] if current else None
    history = list(current.get("history", [])) if current else []
    history = [item for item in history if item != target_hash]
    history.append(target_hash)
    new_owner = {
        "schema": REGISTRY_SCHEMA,
        "product": PRODUCT,
        "package_hash": target_hash,
        "previous_package_hash": previous_hash,
        "history": history[-64:],
    }
    registry.mkdir(parents=True, exist_ok=True)
    journal = registry / ".switch.json"
    if journal.exists():
        raise InstallError("installation_conflict", "registration")
    _write_atomic_json(journal, _journal_value(current, new_owner))
    try:
        _write_registry_files(registry, destination, package_root, metadata, new_owner)
        journal.unlink()
    except InstallError:
        # The journal remains if recovery may be needed after a process
        # interruption.  A normal error is repaired immediately where safe.
        try:
            if current is not None:
                old_root = destination / "packages" / current["package_hash"]
                old_metadata = _verify_package_at(old_root, current["package_hash"])
                _write_registry_files(registry, destination, old_root, old_metadata, current)
                journal.unlink(missing_ok=True)
            else:
                journal.unlink(missing_ok=True)
        except (InstallError, OSError):
            pass
        raise
    except OSError as exc:
        raise InstallError("filesystem_failed", "registration") from exc
    return new_owner, current is not None


def _register_with_codex(codex: Path, registry: Path, had_marketplace: bool, runner: Runner) -> None:
    try:
        if not had_marketplace:
            runner([str(codex), "plugin", "marketplace", "add", str(registry), "--json"])
        runner([str(codex), "plugin", "add", f"{PRODUCT}@{MARKETPLACE_NAME}", "--json"])
        rows = read_marketplaces(runner([str(codex), "plugin", "marketplace", "list", "--json"]))
        matching = _marketplace_rows(rows, MARKETPLACE_NAME)
        if len(matching) != 1 or not _same_path(matching[0]["root"], registry):
            raise ValueError
    except (InstallError, ValueError) as exc:
        raise InstallError("registration_failed", "registration") from exc


def _prepare_package(package: Path, events: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    try:
        metadata = verify(package)
        package_hash = digest(package / "package-manifest.json")
    except (PackageError, OSError) as exc:
        raise InstallError("package_invalid", "package") from exc
    events.append(event("package", "verified", "none", "verify_package"))
    return metadata, package_hash


def _package_runtime(package: Path) -> Path:
    candidates = (
        package / "payload" / "runtime" / "python" / "python.exe",
        package / "payload" / "runtime" / "python" / "python",
        package / "payload" / "runtime" / "python" / "bin" / "python3",
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink() and not _is_reparse(candidate):
            return candidate
    raise InstallError("runtime_missing", "runtime")


def _install(package: Path, destination: Path, codex: Path, events: list[dict[str, Any]], runner: Runner, *, allow_legacy: bool = False) -> dict[str, Any]:
    metadata, package_hash = _prepare_package(package, events)
    python = _package_runtime(package)
    check = "import nexin_mail.server; print('nexin-mail-runtime-ready')"
    try:
        if runner([str(python), "-B", "-X", "utf8", "-c", check], timeout=60).strip() != "nexin-mail-runtime-ready":
            raise ValueError
    except (InstallError, ValueError) as exc:
        raise InstallError("runtime_failed", "runtime") from exc
    events.append(event("runtime", "verified", "none", "check_runtime"))
    try:
        rows = read_marketplaces(runner([str(codex), "plugin", "marketplace", "list", "--json"]))
    except InstallError:
        raise
    destination = _assert_no_links(destination)
    registry = destination / "registry"
    existing = _marketplace_rows(rows, MARKETPLACE_NAME)
    if len(existing) > 1:
        raise InstallError("installation_conflict", "registration")
    if existing and not _same_path(existing[0]["root"], registry):
        raise InstallError("installation_conflict", "registration")
    if _marketplace_rows(rows, LEGACY_MARKETPLACE_NAME) and not allow_legacy:
        raise InstallError("installation_conflict", "registration")
    try:
        destination.mkdir(parents=True, exist_ok=True)
        _assert_no_links(registry)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError("filesystem_failed", "registration") from exc
    current = _recover_registry(registry, destination)
    if current is not None:
        active_root = destination / "packages" / current["package_hash"]
        _verify_package_at(active_root, current["package_hash"])
        # Do not update a registry that has acquired an unexpected file or
        # metadata shape since the last verified switch.
        if not _registry_is_ours(registry, destination):
            raise InstallError("installation_conflict", "registration")
    installed, newly_staged = _stage_package(package, destination, package_hash, events)
    if current is not None and current["package_hash"] != package_hash:
        # The new payload is staged before the registry can move.  The old
        # package remains available even when registration later fails.
        events.append(event("package", "attempted", "update_staged", "stage_update"))
    owner, switched = _switch_registry(registry, destination, installed, metadata, current)
    events.append(event("host", "verified", "none", "check_host"))
    try:
        _register_with_codex(codex, registry, bool(existing), runner)
    except InstallError:
        if switched and current is not None:
            try:
                old_root = destination / "packages" / current["package_hash"]
                old_metadata = _verify_package_at(old_root, current["package_hash"])
                _switch_registry(registry, destination, old_root, old_metadata, owner)
            except (InstallError, OSError):
                pass
        raise
    events.append(event("registration", "verified", "none", "register_plugin"))
    events.extend([
        event("setup", "not_checked", "setup_pending"),
        event("mailbox", "not_checked", "mailbox_pending"),
        event("dashboard", "not_checked"),
    ])
    return {
        "product": PRODUCT,
        "version": metadata["version"],
        "package": "verified",
        "package_hash": package_hash,
        "update": "updated" if current is not None and current["package_hash"] != package_hash else "unchanged" if current is not None else "installed",
        "registration": "verified",
        "mailbox": "not_checked",
        "dashboard": "not_checked",
        "next_step": "Start een nieuwe Codex-taak en laat Nexin Mail de beveiligde mailboxsetup openen.",
    }


def install(
    package: Path,
    destination: Path,
    codex: Path,
    events: list[dict[str, Any]],
    runner: Runner = run,
    *,
    migrate_legacy: bool = False,
    migration_confirmed: bool = False,
) -> dict[str, Any]:
    """Install a new release or update an owned installation in place."""

    if migrate_legacy:
        return migrate_legacy_install(package, destination, codex, events, runner=runner, confirmed=migration_confirmed)
    return _install(_absolute(package), _absolute(destination), _absolute(codex), events, runner)


def _legacy_is_owned(row: dict[str, str]) -> bool:
    root = _absolute(row["root"])
    try:
        _assert_no_links(root)
        release = _read_json(root / "release.json")
        plugin = _read_json(root / "plugins" / "imap-plugin" / ".codex-plugin" / "plugin.json")
    except (InstallError, OSError):
        return False
    return (
        isinstance(release, dict)
        and release.get("product") in {"imap-plugin-windows-handoff", "imap-plugin-macos-source-installer", "imap-plugin-installed-backend"}
        and isinstance(plugin, dict)
        and plugin.get("name") == "imap-plugin"
    )


def migrate_legacy_install(
    package: Path,
    destination: Path,
    codex: Path,
    events: list[dict[str, Any]],
    *,
    runner: Runner = run,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Migrate an exact legacy marketplace only after explicit confirmation."""

    if not confirmed:
        raise InstallError("migration_confirmation_required", "registration")
    try:
        rows = read_marketplaces(runner([str(codex), "plugin", "marketplace", "list", "--json"]))
    except InstallError:
        raise
    legacy = _marketplace_rows(rows, LEGACY_MARKETPLACE_NAME)
    if len(legacy) != 1 or not _legacy_is_owned(legacy[0]):
        raise InstallError("installation_conflict", "registration")
    result = _install(_absolute(package), _absolute(destination), _absolute(codex), events, runner, allow_legacy=True)
    try:
        current_rows = read_marketplaces(runner([str(codex), "plugin", "marketplace", "list", "--json"]))
        current_legacy = _marketplace_rows(current_rows, LEGACY_MARKETPLACE_NAME)
        if len(current_legacy) != 1 or not _same_path(current_legacy[0]["root"], legacy[0]["root"]) or not _legacy_is_owned(current_legacy[0]):
            raise ValueError
        runner([str(codex), "plugin", "remove", f"imap-plugin@{LEGACY_MARKETPLACE_NAME}", "--json"])
        runner([str(codex), "plugin", "marketplace", "remove", LEGACY_MARKETPLACE_NAME, "--json"])
        after = read_marketplaces(runner([str(codex), "plugin", "marketplace", "list", "--json"]))
        if _marketplace_rows(after, LEGACY_MARKETPLACE_NAME):
            raise ValueError
    except (InstallError, ValueError) as exc:
        raise InstallError("migration_failed", "registration") from exc
    events.append(event("registration", "verified", "migration_completed", "migrate_legacy"))
    result["migration"] = "completed"
    return result


def _select_rollback_hash(owner: dict[str, Any], target_hash: str | None) -> str:
    if target_hash is not None:
        if not _is_hash(target_hash) or target_hash not in owner["history"]:
            raise InstallError("rollback_unavailable", "registration")
        return target_hash
    previous = owner.get("previous_package_hash")
    if _is_hash(previous):
        return previous
    history = owner.get("history", [])
    if len(history) >= 2:
        return history[-2]
    raise InstallError("rollback_unavailable", "registration")


def rollback(
    destination: Path,
    codex: Path | None = None,
    events: list[dict[str, Any]] | None = None,
    *,
    runner: Runner = run,
    target_hash: str | None = None,
) -> dict[str, Any]:
    """Switch registration to a previously verified payload, preserving both."""

    events = events if events is not None else []
    destination = _assert_no_links(destination)
    registry = destination / "registry"
    current = _recover_registry(registry, destination)
    if current is None:
        raise InstallError("rollback_unavailable", "registration")
    current_root = destination / "packages" / current["package_hash"]
    _verify_package_at(current_root, current["package_hash"])
    if not _registry_is_ours(registry, destination):
        raise InstallError("installation_conflict", "registration")
    selected = _select_rollback_hash(current, target_hash)
    if selected == current["package_hash"]:
        raise InstallError("rollback_unavailable", "registration")
    old_root = current_root
    target_root = destination / "packages" / selected
    old_metadata = _verify_package_at(old_root, current["package_hash"])
    target_metadata = _verify_package_at(target_root, selected)
    history = [item for item in current["history"] if item != selected]
    history.append(selected)
    new_owner = {
        "schema": REGISTRY_SCHEMA,
        "product": PRODUCT,
        "package_hash": selected,
        "previous_package_hash": current["package_hash"],
        "history": history,
    }
    _write_atomic_json(registry / ".switch.json", _journal_value(current, new_owner))
    try:
        _write_registry_files(registry, destination, target_root, target_metadata, new_owner)
        (registry / ".switch.json").unlink()
    except (InstallError, OSError) as exc:
        raise InstallError("rollback_failed", "registration") from exc
    if codex is not None:
        try:
            rows = read_marketplaces(runner([str(_absolute(codex)), "plugin", "marketplace", "list", "--json"]))
            matching = _marketplace_rows(rows, MARKETPLACE_NAME)
            if len(matching) > 1 or (matching and not _same_path(matching[0]["root"], registry)):
                raise ValueError
            _register_with_codex(_absolute(codex), registry, bool(matching), runner)
        except (InstallError, ValueError) as exc:
            try:
                _write_registry_files(registry, destination, old_root, old_metadata, current)
                (registry / ".switch.json").unlink(missing_ok=True)
            except (InstallError, OSError):
                pass
            if isinstance(exc, InstallError):
                raise
            raise InstallError("registration_failed", "registration") from exc
    events.append(event("registration", "verified", "rollback_completed", "rollback"))
    return {
        "product": PRODUCT,
        "version": target_metadata["version"],
        "status": "rolled_back",
        "package_hash": selected,
        "registration": "verified" if codex is not None else "not_checked",
        "mailbox": "not_checked",
        "dashboard": "not_checked",
    }


def _remove_owned_registry(registry: Path, destination: Path) -> None:
    if not _registry_is_ours(registry, destination):
        raise InstallError("installation_conflict", "registration")
    try:
        for item in registry.rglob("*"):
            if item.is_symlink() or _is_reparse(item):
                raise InstallError("installation_conflict", "registration")
        shutil.rmtree(registry)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError("filesystem_failed", "registration") from exc


def uninstall(
    destination: Path,
    codex: Path | None = None,
    events: list[dict[str, Any]] | None = None,
    *,
    runner: Runner = run,
) -> dict[str, Any]:
    """Remove only this install's derived registration; preserve data and packages."""

    events = events if events is not None else []
    destination = _assert_no_links(destination)
    registry = destination / "registry"
    _assert_no_links(registry)
    if not registry.exists():
        events.append(event("registration", "not_checked", "uninstall_not_registered", "uninstall"))
        return {"product": PRODUCT, "status": "not_registered", "registration": "not_checked", "credentials": "preserved", "settings": "preserved", "packages": "preserved"}
    owner = _read_owner(registry)
    if owner is None or not _registry_is_ours(registry, destination):
        raise InstallError("installation_conflict", "registration")
    if codex is not None:
        try:
            rows = read_marketplaces(runner([str(_absolute(codex)), "plugin", "marketplace", "list", "--json"]))
            matching = _marketplace_rows(rows, MARKETPLACE_NAME)
            if len(matching) > 1 or (matching and not _same_path(matching[0]["root"], registry)):
                raise ValueError
            if matching:
                runner([str(_absolute(codex)), "plugin", "remove", f"{PRODUCT}@{MARKETPLACE_NAME}", "--json"])
                runner([str(_absolute(codex)), "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"])
                remaining = read_marketplaces(runner([str(_absolute(codex)), "plugin", "marketplace", "list", "--json"]))
                if _marketplace_rows(remaining, MARKETPLACE_NAME):
                    raise ValueError
        except (InstallError, ValueError) as exc:
            raise InstallError("registration_failed", "registration") from exc
    _remove_owned_registry(registry, destination)
    events.append(event("registration", "verified", "uninstall_completed", "uninstall"))
    return {
        "product": PRODUCT,
        "status": "unregistered",
        "registration": "verified" if codex is not None else "not_checked",
        "credentials": "preserved",
        "settings": "preserved",
        "packages": "preserved",
    }


def _destination_from_args(args: argparse.Namespace) -> Path:
    if args.install_root:
        return _absolute(args.install_root)
    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        raise InstallError("platform_unsupported", "host")
    return _absolute(Path(local) / "Nexin Mail")


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexin Mail installeren zonder systeem-Python")
    parser.add_argument("action", nargs="?", choices=("install", "rollback", "uninstall"), default="install")
    parser.add_argument("--package", type=Path)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--codex", help="Expliciet pad naar de bedoelde native codex.exe")
    parser.add_argument("--migrate-legacy", action="store_true")
    parser.add_argument("--confirm-migration", action="store_true")
    parser.add_argument("--target-hash")
    args = parser.parse_args()
    events: list[dict[str, Any]] = []
    destination: Path | None = None
    result: dict[str, Any]
    exit_code = 1
    try:
        destination = _destination_from_args(args)
        codex: Path | None = None
        if sys.platform == "win32":
            codex = preflight(args.codex)
        elif sys.platform == "darwin":
            codex = preflight_macos(args.codex)
        elif args.action in {"install", "rollback", "uninstall"}:
            raise InstallError("platform_unsupported", "host")
        if args.action == "install":
            if args.package is None:
                raise InstallError("package_invalid", "package")
            result = install(args.package, destination, codex or Path("codex.exe"), events, migrate_legacy=args.migrate_legacy, migration_confirmed=args.confirm_migration)
        elif args.action == "rollback":
            result = rollback(destination, codex, events, target_hash=args.target_hash)
        else:
            result = uninstall(destination, codex, events)
        exit_code = 0
    except InstallError as exc:
        events.append(event(exc.stage, "blocked", exc.code))
        result = {"status": "blocked", "code": exc.code, "stage": exc.stage}
    except (OSError, PackageError):
        events.append(event("package", "blocked", "filesystem_failed"))
        result = {"status": "blocked", "code": "filesystem_failed"}
    if destination is not None:
        try:
            result["diagnostic_report"] = "saved_locally" if save_report(destination / "diagnostics", report(__version__, events)) else "not_saved"
        except (OSError, ValueError, InstallError):
            result["diagnostic_report"] = "not_saved"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
