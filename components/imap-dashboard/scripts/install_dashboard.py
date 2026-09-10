from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DASHBOARD_ENTRY = {
    "name": "imap-dashboard",
    "source": {"source": "local", "path": "./plugins/imap-dashboard"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
    "category": "Productivity",
}
COPY_DIRECTORIES = (".codex-plugin", "docs", "skills", "src")
COPY_FILES = (
    ".mcp.json",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODEX_INSTALL.md",
    "LICENSE",
    "PRIVACY.md",
    "README.md",
    "pyproject.toml",
)
LAUNCH_FILES = ("launch.cmd", "launch_macos.sh")


class InstallError(RuntimeError):
    pass


def application_root() -> Path:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise InstallError("LOCALAPPDATA is unavailable")
        return Path(base) / "IMAP Plugin"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "IMAP Plugin"
    raise InstallError("only Windows and macOS are supported")


def _resolved_child(parent: Path, child: Path) -> Path:
    parent = parent.resolve()
    child = child.resolve()
    if child.parent != parent:
        raise InstallError(f"installation target escaped {parent}")
    return child


def backend_paths(program_root: Path) -> tuple[Path, Path, Path]:
    distribution = program_root / "distribution"
    backend = distribution / "plugins" / "imap-plugin"
    manifest = backend / ".codex-plugin" / "plugin.json"
    if not manifest.is_file():
        raise InstallError("the shared IMAP Plugin backend is not installed")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if value.get("name") != "imap-plugin":
        raise InstallError("the sibling backend has an unknown plugin identity")
    if not (backend / "src" / "imap_plugin" / "server.py").is_file():
        raise InstallError("the sibling backend source is incomplete")
    if platform.system() == "Windows":
        python = backend / "runtime" / "python" / "python.exe"
    else:
        python = backend / "runtime" / "venv" / "bin" / "python"
    if not python.is_file():
        raise InstallError("the sibling backend runtime is missing")
    if Path(sys.executable).resolve() != python.resolve():
        raise InstallError("the dashboard installer must run with the sibling backend runtime")
    return distribution, backend, python


def _write_platform_manifest(stage: Path, destination: Path, backend: Path, python: Path) -> None:
    if platform.system() != "Darwin":
        return
    value = {
        "mcpServers": {
            "imap-dashboard": {
                "type": "stdio",
                "title": "IMAP Dashboard",
                "description": "Mailbox side-panel UI using the installed IMAP Plugin connection and native credential store.",
                "cwd": str(destination),
                "command": str(python),
                "args": ["-m", "imap_dashboard.server"],
                "env": {
                    "PYTHONPATH": os.pathsep.join((str(destination / "src"), str(backend / "src"))),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                "startup_timeout_sec": 20,
                "tool_timeout_sec": 360,
            }
        }
    }
    (stage / ".mcp.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _copy_payload(source: Path, stage: Path) -> None:
    for name in COPY_DIRECTORIES:
        origin = source / name
        if not origin.exists():
            raise InstallError(f"dashboard source is missing {name}")
        shutil.copytree(origin, stage / name)
    for name in COPY_FILES:
        origin = source / name
        if not origin.is_file():
            raise InstallError(f"dashboard source is missing {name}")
        shutil.copy2(origin, stage / name)
    scripts = stage / "scripts"
    scripts.mkdir()
    for name in LAUNCH_FILES:
        origin = source / "scripts" / name
        if not origin.is_file():
            raise InstallError(f"dashboard source is missing scripts/{name}")
        shutil.copy2(origin, scripts / name)


def _verified_marketplace(distribution: Path) -> tuple[Path, dict[str, Any]]:
    path = distribution / ".agents" / "plugins" / "marketplace.json"
    if not path.is_file():
        raise InstallError("the IMAP Plugin marketplace manifest is missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("name") != "imap-plugin-handoff" or not isinstance(data.get("plugins"), list):
        raise InstallError("the installed marketplace has an unknown identity")
    backend_entries = [entry for entry in data["plugins"] if entry.get("name") == "imap-plugin"]
    if len(backend_entries) != 1 or backend_entries[0].get("source") != {
        "source": "local",
        "path": "./plugins/imap-plugin",
    }:
        raise InstallError("the installed marketplace does not contain the expected backend entry")
    return path, data


def _updated_marketplace(data: dict[str, Any]) -> dict[str, Any]:
    plugins = [entry for entry in data["plugins"] if entry.get("name") != "imap-dashboard"]
    plugins.append(DASHBOARD_ENTRY)
    return {**data, "plugins": plugins}


def _verify_imports(stage: Path, backend: Path) -> None:
    sys.path[:0] = [str(stage / "src"), str(backend / "src")]
    for name in ("imap_plugin.bridge", "imap_plugin.operator", "imap_dashboard.server"):
        importlib.import_module(name)


def install(source: Path, program_root: Path) -> dict[str, Any]:
    source = source.resolve()
    distribution, backend, python = backend_paths(program_root)
    plugins = distribution / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    destination = _resolved_child(plugins, plugins / "imap-dashboard")
    stage = _resolved_child(plugins, plugins / f".imap-dashboard-new-{os.getpid()}")
    if stage.exists():
        raise InstallError("dashboard staging directory already exists")
    marketplace_path, marketplace = _verified_marketplace(distribution)
    backup: Path | None = None
    installed_new = False
    marketplace_backup = marketplace_path.read_bytes()
    try:
        stage.mkdir()
        _copy_payload(source, stage)
        _write_platform_manifest(stage, destination, backend, python)
        _verify_imports(stage, backend)
        if destination.exists():
            backups = program_root / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = backups / f"imap-dashboard-{stamp}-{os.getpid()}"
            shutil.move(str(destination), str(backup))
        shutil.move(str(stage), str(destination))
        installed_new = True
        updated = _updated_marketplace(marketplace)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=marketplace_path.parent, delete=False
        ) as handle:
            json.dump(updated, handle, indent=2)
            handle.write("\n")
            temporary_marketplace = Path(handle.name)
        temporary_marketplace.replace(marketplace_path)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if installed_new and destination.exists():
            shutil.rmtree(destination)
        if backup is not None and backup.exists() and not destination.exists():
            shutil.move(str(backup), str(destination))
        marketplace_path.write_bytes(marketplace_backup)
        raise
    receipt = {
        "status": "installed",
        "plugin": "imap-dashboard@imap-plugin-handoff",
        "version": "0.1.2",
        "reused_existing_connection": True,
        "backend_plugin": "imap-plugin",
        "dashboard": str(destination),
        "backup": str(backup) if backup else None,
        "credentials_changed": False,
        "configuration_changed": False,
    }
    receipt_path = program_root / "dashboard-install-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {**receipt, "receipt": str(receipt_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(install(args.source_root, application_root()), indent=2))


if __name__ == "__main__":
    main()
