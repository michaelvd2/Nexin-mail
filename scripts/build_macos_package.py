"""Build a real, relocatable Nexin Mail package for macOS arm64.

The runtime is downloaded from the pinned python-build-standalone release and
is materialized without symlinks before the package builder sees it.  The
package therefore remains independent of Homebrew, a developer venv, and the
build machine's absolute paths.  This script intentionally builds only the
host's arm64 target; an Intel artifact needs its own upstream asset and proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request


PRODUCT_VERSION = "0.2.0"
PYTHON_VERSION = "3.12.14"
PBA_RELEASE = "20260901"
PBA_TARGET = "aarch64-apple-darwin"
PBA_ARCHIVE = f"cpython-{PYTHON_VERSION}+{PBA_RELEASE}-{PBA_TARGET}-install_only.tar.gz"
PBA_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PBA_RELEASE}/{PBA_ARCHIVE.replace('+', '%2B')}"
)
PBA_CHECKSUM_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PBA_RELEASE}/SHA256SUMS"
)
PBA_SHA256 = "3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76"
PBA_RELEASE_URL = f"https://github.com/astral-sh/python-build-standalone/releases/tag/{PBA_RELEASE}"
PBA_LICENSE_URL = "https://github.com/astral-sh/python-build-standalone/blob/main/LICENSE"
PYTHON_LICENSE_URL = "https://github.com/astral-sh/python-build-standalone/blob/main/LICENSE.cpython.txt"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _relative_member(name: str) -> tuple[str, ...]:
    """Validate an upstream archive name before it reaches the filesystem."""

    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("upstream archive contains an invalid path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("upstream archive contains traversal")
    return path.parts


def _link_target(relative: tuple[str, ...], target: str) -> tuple[str, ...]:
    if not isinstance(target, str) or not target or "\x00" in target or "\\" in target:
        raise ValueError("upstream archive contains an invalid link target")
    candidate = PurePosixPath(*relative[:-1], target)
    if candidate.is_absolute():
        raise ValueError("upstream archive contains an absolute link")
    parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("upstream archive link escapes its root")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise ValueError("upstream archive link has no target")
    return tuple(parts)


def safe_extract(archive: Path, destination: Path) -> Path:
    """Extract a trusted, hash-checked tarball while materializing safe links.

    The archive currently contains nine relative convenience symlinks in
    ``python/bin`` and ``python/lib/pkgconfig``.  They are copied as regular
    files after every target is checked to stay inside the extracted root.
    Hard links and special files are rejected because they add no value to the
    runtime and complicate ownership and rollback guarantees.
    """

    archive = archive.resolve(strict=True)
    destination = destination.resolve(strict=False)
    if destination.exists():
        raise ValueError("runtime extraction destination already exists")
    destination.mkdir(parents=True)
    files: dict[tuple[str, ...], tarfile.TarInfo] = {}
    directories: set[tuple[str, ...]] = set()
    links: dict[tuple[str, ...], tuple[str, ...]] = {}
    with tarfile.open(archive, mode="r:gz") as stream:
        members = stream.getmembers()
        seen: set[tuple[str, ...]] = set()
        for member in members:
            relative = _relative_member(member.name)
            if relative in seen:
                raise ValueError("upstream archive contains duplicate paths")
            seen.add(relative)
            if member.isdir():
                directories.add(relative)
            elif member.isfile():
                files[relative] = member
            elif member.issym():
                links[relative] = _link_target(relative, member.linkname)
            elif member.islnk() or member.isdev() or member.isfifo():
                raise ValueError("upstream archive contains an unsupported link or special file")
            else:
                raise ValueError("upstream archive contains an unsupported entry")

        all_paths = set(files) | directories | set(links)
        implicit_directories: set[tuple[str, ...]] = set(directories)
        for path in all_paths:
            implicit_directories.update(path[:index] for index in range(1, len(path)))
        for path in all_paths:
            for index in range(1, len(path)):
                parent = path[:index]
                if parent in files or parent in links:
                    raise ValueError("upstream archive path collides with a file or link")
        for path, target in links.items():
            if target not in all_paths and target not in implicit_directories:
                raise ValueError("upstream archive link target is missing")

        for relative in sorted(directories):
            (destination.joinpath(*relative)).mkdir(parents=True, exist_ok=True)
        for relative in sorted(files):
            target = destination.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            member = files[relative]
            extracted = stream.extractfile(member)
            if extracted is None:
                raise ValueError("upstream archive file could not be read")
            with extracted, target.open("xb") as output:
                shutil.copyfileobj(extracted, output)
            target.chmod(member.mode & 0o777)

    resolving: set[tuple[str, ...]] = set()

    def materialize(relative: tuple[str, ...]) -> None:
        if relative not in links:
            return
        if relative in resolving:
            raise ValueError("upstream archive contains a link cycle")
        resolving.add(relative)
        target = links[relative]
        materialize(target)
        source = destination.joinpath(*target)
        output = destination.joinpath(*relative)
        if source.is_symlink() or not source.exists():
            raise ValueError("upstream archive link target could not be materialized")
        if source.is_dir():
            shutil.copytree(source, output, symlinks=False)
        elif source.is_file():
            shutil.copyfile(source, output)
            output.chmod(stat.S_IMODE(source.stat().st_mode))
        else:
            raise ValueError("upstream archive link target is not a regular file")
        resolving.remove(relative)

    for relative in sorted(links):
        materialize(relative)
    if any(item.is_symlink() for item in destination.rglob("*")):
        raise ValueError("runtime extraction left a link behind")
    return destination


def _assert_plain_tree(root: Path) -> None:
    if root.is_symlink():
        raise ValueError(f"runtime path is a link: {root}")
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"runtime path is a link: {item}")
        if not item.is_file() and not item.is_dir():
            raise ValueError(f"runtime path is not a regular file or directory: {item}")


def ensure_upstream_archive(artifact_root: Path) -> Path:
    checksums = artifact_root / "SHA256SUMS"
    if checksums.exists():
        if not checksums.is_file() or checksums.is_symlink():
            raise ValueError("upstream checksum manifest is not a regular file")
    else:
        partial_checksums = artifact_root / ("SHA256SUMS." + str(os.getpid()) + ".part")
        if partial_checksums.exists():
            raise ValueError("stale upstream checksum download exists; inspect it before retrying")
        try:
            with urllib.request.urlopen(PBA_CHECKSUM_URL, timeout=120) as response, partial_checksums.open("xb") as output:
                shutil.copyfileobj(response, output)
            os.replace(partial_checksums, checksums)
        except Exception:
            partial_checksums.unlink(missing_ok=True)
            raise
    checksum_rows = checksums.read_text(encoding="utf-8").splitlines()
    expected_row = f"{PBA_SHA256}  {PBA_ARCHIVE}"
    if expected_row not in checksum_rows:
        raise ValueError("upstream checksum manifest does not attest the pinned runtime")
    archive = artifact_root / PBA_ARCHIVE
    if archive.exists():
        if not archive.is_file() or archive.is_symlink() or sha256(archive) != PBA_SHA256:
            raise ValueError("existing upstream runtime archive does not match its pinned hash")
    else:
        partial = artifact_root / (PBA_ARCHIVE + f".{os.getpid()}.part")
        if partial.exists():
            raise ValueError("stale runtime download exists; inspect it before retrying")
        try:
            with urllib.request.urlopen(PBA_URL, timeout=120) as response, partial.open("xb") as output:
                shutil.copyfileobj(response, output)
            if sha256(partial) != PBA_SHA256:
                raise ValueError("downloaded upstream runtime hash mismatch")
            os.replace(partial, archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    return archive


def _run(runtime: Path, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged.update(env or {})
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    merged.pop("PYTHONPATH", None)
    return subprocess.run([str(runtime), *args], cwd=str(runtime.parent.parent), env=merged,
                          check=True, capture_output=True, text=True, encoding="utf-8", timeout=300)


def install_locked_dependencies(runtime_root: Path, source_root: Path) -> dict[str, str]:
    runtime = runtime_root / "bin" / "python3.12"
    old_site = runtime_root / "lib" / "python3.12" / "site-packages"
    target_site = runtime_root / "lib" / "python3.12" / ".nexin-dependencies"
    if not runtime.is_file() or runtime.is_symlink() or not old_site.is_dir() or old_site.is_symlink():
        raise ValueError("standalone runtime does not have the expected Python layout")
    if target_site.exists():
        raise ValueError("dependency staging path already exists")
    lock = source_root / "requirements-runtime.lock"
    command = [
        "-B", "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
        "--only-binary=:all:", "--no-compile", "--require-hashes", "--target", str(target_site),
        "--requirement", str(lock),
    ]
    _run(runtime, command, env={"PIP_NO_INPUT": "1"})
    # ``pip --target`` may emit console launchers in a target-local ``bin``
    # directory.  Their shebangs point at this build machine, so remove only
    # those newly-created directories after checking they cannot escape the
    # dependency staging root.
    for launcher_dir in (target_site / "bin", target_site / "Scripts"):
        if launcher_dir.is_symlink():
            raise ValueError("dependency staging contains a launcher link")
        if launcher_dir.exists():
            if not launcher_dir.resolve(strict=True).is_relative_to(target_site.resolve(strict=True)):
                raise ValueError("dependency launcher path escaped staging root")
            shutil.rmtree(launcher_dir)
    backup = runtime_root / "lib" / "python3.12" / ".upstream-site-packages"
    if backup.exists():
        raise ValueError("upstream site-packages backup already exists")
    old_site.rename(backup)
    target_site.rename(old_site)
    shutil.rmtree(backup)
    for name in ("pip", "pip3", "pip3.12"):
        (runtime_root / "bin" / name).unlink(missing_ok=True)
    _assert_plain_tree(runtime_root)
    result = _run(runtime, [
        "-B", "-c",
        "import importlib.metadata; import mcp, msal; "
        "print(importlib.metadata.version('mcp')); print(msal.__version__)",
    ])
    versions = result.stdout.strip().splitlines()
    if len(versions) != 2:
        raise ValueError("runtime dependency probe returned an unexpected result")
    return {"mcp": versions[0], "msal": versions[1]}


def build(source_root: Path, artifact_root: Path) -> dict[str, object]:
    if sys.platform != "darwin" or platform_machine() != "arm64":
        raise RuntimeError("this route requires a macOS arm64 build host")
    source_root = source_root.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    archive = ensure_upstream_archive(artifact_root)
    extracted = artifact_root / "runtime-macos-arm64"
    safe_extract(archive, extracted)
    runtime_root = extracted / "python"
    runtime = runtime_root / "bin" / "python3.12"
    if not runtime.is_file() or runtime.is_symlink():
        raise ValueError("upstream runtime executable is missing")
    probe = _run(runtime, ["-B", "-c", "import platform,sys; print(sys.version.split()[0]); print(platform.machine())"])
    lines = probe.stdout.strip().splitlines()
    if lines != [PYTHON_VERSION, "arm64"]:
        raise ValueError(f"unexpected upstream runtime identity: {lines!r}")
    dependency_versions = install_locked_dependencies(runtime_root, source_root)
    marker = runtime_root / ".nexin-mail-platform"
    marker.write_text("macos-arm64\n", encoding="utf-8")
    package_root = artifact_root / f"nexin-mail-{PRODUCT_VERSION}-macos-arm64"
    if package_root.exists():
        raise ValueError("package output already exists; artifacts are immutable")
    command = [
        sys.executable, "-m", "nexin_mail.build", "--platform", "macos",
        "--source", str(source_root), "--runtime", str(runtime_root), "--output", str(package_root),
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root / "src")
    result = subprocess.run(command, cwd=str(source_root), env=environment, check=True,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    build_result = json.loads(result.stdout.strip().splitlines()[-1])
    built_archive = Path(str(build_result["archive"])).resolve(strict=True)
    package_manifest = json.loads((package_root / "package-manifest.json").read_text(encoding="utf-8"))
    provenance = {
        "schema": 1,
        "product": "nexin-mail",
        "package_version": PRODUCT_VERSION,
        "target": "macos-arm64",
        "python_version": PYTHON_VERSION,
        "python_architecture": "arm64",
        "upstream": {
            "project": "astral-sh/python-build-standalone",
            "release": PBA_RELEASE,
            "release_url": PBA_RELEASE_URL,
            "artifact": PBA_ARCHIVE,
            "artifact_url": PBA_URL,
            "artifact_sha256": PBA_SHA256,
            "checksum_url": PBA_CHECKSUM_URL,
            "license_url": PBA_LICENSE_URL,
            "python_license_url": PYTHON_LICENSE_URL,
        },
        "runtime_archive_bytes": archive.stat().st_size,
        "runtime_executable_sha256": sha256(runtime),
        "dependencies_lock_sha256": sha256(source_root / "requirements-runtime.lock"),
        "dependencies": dependency_versions,
        "package_archive": {
            "path": str(built_archive),
            "bytes": built_archive.stat().st_size,
            "sha256": sha256(built_archive),
        },
        "manifest_sha256": sha256(package_root / "package-manifest.json"),
        "manifest_files": len(package_manifest["files"]),
        "license_in_package": "payload/runtime/python/lib/python3.12/LICENSE.txt",
        "build_host": {"system": "Darwin", "machine": platform_machine()},
    }
    (artifact_root / "runtime-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def platform_machine() -> str:
    import platform
    return platform.machine()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.source, args.artifact_root)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "pass", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
