"""Build one reproducible platform distribution from pinned source inputs.

This is a build-machine entrypoint.  Customers receive the assembled private
runtime and do not need Python, pip, Node, or a compiler.  Signing is kept as a
separate, explicit release gate; a hash manifest provides integrity only.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tomllib
import zipfile
from typing import Any

from . import __version__
from .package import digest, verify

PRODUCT = "nexin-mail"
WINDOWS_PYTHON_VERSION = "3.12.14"
MACOS_PYTHON_VERSION = "3.12.14"
PYTHON_VERSION = MACOS_PYTHON_VERSION
_REPARSE_POINT = 0x400
_SKIP_NAMES = {"__pycache__", ".pytest_cache", ".DS_Store"}


def _is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def _assert_plain_tree(root: Path) -> None:
    if root.is_symlink() or _is_reparse(root):
        raise ValueError("Links and reparse points are not valid build inputs")
    try:
        for item in root.rglob("*"):
            if item.is_symlink() or _is_reparse(item):
                raise ValueError(f"Build input contains a link: {item.name}")
    except OSError as exc:
        raise ValueError("Build input could not be inspected") from exc


def _copy_tree(source: Path, target: Path) -> None:
    source = Path(source)
    if source.is_symlink() or _is_reparse(source):
        raise ValueError("Links and reparse points are not valid build inputs")
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Build input is unavailable") from exc
    _assert_plain_tree(source)
    target.mkdir(parents=True, exist_ok=False)
    try:
        paths = sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix().casefold())
        for item in paths:
            if any(part in _SKIP_NAMES for part in item.relative_to(source).parts) or item.suffix.casefold() == ".pyc":
                continue
            relative = item.relative_to(source)
            destination = target / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, destination)
                destination.chmod(stat.S_IMODE(item.stat().st_mode))
            else:
                raise ValueError(f"Unsupported build input: {item.name}")
    except OSError as exc:
        raise ValueError("Build input could not be copied") from exc


def _read_project_version(path: Path) -> str:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        version = data["project"]["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot read component metadata: {path.name}") from exc
    if not isinstance(version, str):
        raise ValueError(f"Component version is invalid: {path.name}")
    return version


def _source_module_version(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ValueError("Nexin Mail source version is unreadable") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__" and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return node.value.value
    raise ValueError("Nexin Mail source version is missing")


def verify_source_versions(source: Path) -> dict[str, Any]:
    """Check package, source, and component versions before copying anything."""

    try:
        sources = json.loads((source / "nexin-mail" / "sources.json").read_text(encoding="utf-8"))
        plugin = json.loads((source / "nexin-mail" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source version metadata is missing or invalid") from exc
    if not isinstance(sources, dict) or sources.get("product") != PRODUCT or sources.get("version") != __version__:
        raise ValueError("Nexin Mail package version mismatch")
    if not isinstance(plugin, dict) or plugin.get("name") != PRODUCT or plugin.get("version") != sources["version"]:
        raise ValueError("Plugin and source versions differ")
    source_version = _source_module_version(source / "src" / "nexin_mail" / "__init__.py")
    if source_version != sources["version"]:
        raise ValueError("Nexin Mail module and source versions differ")
    components = sources.get("components")
    if not isinstance(components, dict):
        raise ValueError("Component source metadata is missing")
    expected = {
        "imap-plugin": source / "pyproject.toml",
        "imap-dashboard": source / "components" / "imap-dashboard" / "pyproject.toml",
    }
    for name, project in expected.items():
        row = components.get(name)
        if not isinstance(row, dict) or not isinstance(row.get("version"), str):
            raise ValueError(f"Component source metadata is missing: {name}")
        actual = _read_project_version(project)
        if actual != row["version"]:
            raise ValueError(f"Component version mismatch: {name}")
    return sources


def _manifest(output: Path, version: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    try:
        paths = sorted(output.rglob("*"), key=lambda item: item.relative_to(output).as_posix().casefold())
        for path in paths:
            if path.name == "package-manifest.json" or not path.is_file():
                continue
            if path.is_symlink() or _is_reparse(path):
                raise ValueError("Build output contains a link")
            relative = path.relative_to(output).as_posix()
            files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    except OSError as exc:
        raise ValueError("Build output could not be hashed") from exc
    if not files:
        raise ValueError("Build output is empty")
    return {"schema": 1, "product": PRODUCT, "version": version, "files": files}


def _runtime_layout(runtime: Path) -> tuple[str, Path]:
    """Return the platform and executable for a complete plain runtime."""

    candidates = (
        ("windows", runtime / "python.exe"),
        ("macos", runtime / "bin" / "python3.12"),
    )
    for platform_name, executable in candidates:
        if executable.is_file() and not executable.is_symlink() and not _is_reparse(executable):
            return platform_name, executable
    raise ValueError("Complete pinned private runtime required")


def assemble(source: Path, runtime: Path, output: Path) -> Path:
    """Assemble and verify a fresh immutable package directory."""

    source = Path(source)
    runtime = Path(runtime)
    if source.is_symlink() or runtime.is_symlink() or _is_reparse(source) or _is_reparse(runtime):
        raise ValueError("Build roots may not be links or reparse points")
    try:
        source = source.resolve(strict=True)
        runtime = runtime.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Build root is unavailable") from exc
    if output.is_symlink() or _is_reparse(output):
        raise ValueError("Build output may not be a link or reparse point")
    output = output.resolve(strict=False)
    if output.exists():
        raise ValueError("Use a new output directory; existing artifacts are preserved")
    try:
        if output.is_relative_to(source):
            raise ValueError("Build output must be outside the source tree")
    except OSError as exc:
        raise ValueError("Build output path could not be checked") from exc
    sources = verify_source_versions(source)
    runtime_platform, _ = _runtime_layout(runtime)
    if runtime_platform == "windows":
        # Accept the legacy embedded layout used by the original fixture and
        # the current standalone build.  The latter carries a full Lib tree;
        # neither path permits links or a build-machine venv.
        if (runtime / "python312._pth").is_file():
            required_runtime = (
                "python.exe", "python312.dll", "python312.zip", "python312._pth",
                "Lib/site-packages/mcp/__init__.py",
            )
        else:
            required_runtime = (
                "python.exe", "python3.dll", "python312.dll", "Lib/os.py",
                "Lib/site-packages/mcp/__init__.py",
            )
    else:
        required_runtime = (
            "bin/python3.12", "lib/python3.12/os.py",
            "lib/python3.12/site-packages/mcp/__init__.py",
        )
    for name in required_runtime:
        candidate = runtime / name
        if not candidate.is_file() or candidate.is_symlink() or _is_reparse(candidate):
            raise ValueError(f"Complete pinned private {runtime_platform} runtime required")
    dashboard = source / "components" / "imap-dashboard"
    ui_entry = dashboard / "src" / "imap_dashboard" / "ui" / "mail-app.html"
    if not ui_entry.is_file() or ui_entry.is_symlink() or _is_reparse(ui_entry):
        raise ValueError("Prebuilt dashboard required")
    try:
        ui_text = ui_entry.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("Prebuilt dashboard could not be read") from exc
    # A customer package must carry one deterministic HTML asset.  External
    # script/style references would silently reintroduce a network or Node
    # dependency at install time.
    if "<script src=" in ui_text or "<link href=" in ui_text or "<link rel=\"stylesheet\"" in ui_text:
        raise ValueError("Dashboard is not a self-contained asset")
    _assert_plain_tree(runtime)
    output.mkdir(parents=True)
    payload = output / "payload"
    payload.mkdir()
    for name in ("imap_plugin", "nexin_mail"):
        _copy_tree(source / "src" / name, payload / "src" / name)
    _copy_tree(dashboard / "src" / "imap_dashboard", payload / "src" / "imap_dashboard")
    _copy_tree(runtime, payload / "runtime" / "python")
    _copy_tree(source / "scripts", payload / "scripts")
    for name in ("LICENSE",):
        shutil.copyfile(source / name, output / name)
    shutil.copyfile(source / "nexin-mail" / "sources.json", output / "sources.json")
    for name in ("plugin.json", "install.cmd", "uninstall.cmd", "rollback.cmd", "install_macos.sh", "uninstall_macos.sh", "INSTALLATIE.md"):
        path = source / "nexin-mail" / name
        if path.is_file():
            shutil.copyfile(path, output / name)
    _copy_tree(source / "nexin-mail" / "skills", output / "skills")
    manifest = _manifest(output, sources["version"])
    (output / "package-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify(output)
    return output


def create_archive(output: Path, archive: Path | None = None) -> Path:
    """Write a timestamp-independent ZIP of a verified package directory."""

    output = output.resolve(strict=True)
    verify(output)
    archive = Path(archive) if archive is not None else output.with_suffix(".zip")
    if archive.is_symlink() or _is_reparse(archive):
        raise ValueError("Archive output may not be a link or reparse point")
    archive = archive.resolve(strict=False)
    if archive.exists():
        raise ValueError("Archive already exists")
    if archive.is_relative_to(output):
        raise ValueError("Archive must be outside the package directory")
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
            for path in sorted((item for item in output.rglob("*") if item.is_file()), key=lambda item: item.relative_to(output).as_posix()):
                relative = path.relative_to(output).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                # Preserve the executable bit required by the macOS shell
                # entrypoints after ZIP extraction.  Windows batch files and
                # all data/code files remain ordinary non-executable files.
                mode = 0o100755 if path.suffix.casefold() == ".sh" or path.stat().st_mode & 0o111 else 0o100644
                info.external_attr = mode << 16
                info.flag_bits = 0x800
                stream.writestr(info, path.read_bytes())
    except OSError as exc:
        try:
            archive.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError("Archive could not be written") from exc
    return archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("windows", "macos"), default="windows")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.platform == "windows" and sys.platform != "win32":
        parser.error("Build and verify the real Windows runtime on Windows")
    if args.platform == "macos" and sys.platform != "darwin":
        parser.error("Build and verify the real macOS runtime on macOS")
    runtime = args.runtime.resolve()
    runtime_executable = runtime / "python.exe" if args.platform == "windows" else runtime / "bin" / "python3.12"
    expected_version = WINDOWS_PYTHON_VERSION if args.platform == "windows" else MACOS_PYTHON_VERSION
    try:
        probe = subprocess.run(
            [str(runtime_executable), "-B", "-c", "import sys; print(sys.version.split()[0])"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Pinned runtime could not be executed") from exc
    if probe.stdout.strip() != expected_version:
        raise ValueError("Unexpected runtime version")
    output = assemble(args.source.resolve(), runtime, args.output.resolve())
    packaged_runtime = output / "payload" / "runtime" / "python"
    packaged_executable = packaged_runtime / "python.exe" if args.platform == "windows" else packaged_runtime / "bin" / "python3.12"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(output / "payload" / "src")
    subprocess.run(
        [str(packaged_executable), "-B", "-c", "import nexin_mail.server, nexin_mail.install"],
        cwd=str(output),
        env=environment,
        check=True,
        timeout=60,
        shell=False,
    )
    archive = create_archive(output)
    print(json.dumps({
        "product": PRODUCT,
        "archive": str(archive),
        "sha256": digest(archive),
        "signing": "not_attested",
        "publisher_authenticity": "not_attested",
        f"{args.platform}_customer_acceptance": "not_checked",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
