import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.prepare_release_assets import prepare


def package(path: Path, *, tampered=False):
    plugin = json.dumps({"name": "nexin-mail", "version": "0.2.0"}).encode()
    manifest = {"schema": 1, "product": "nexin-mail", "version": "0.2.0", "files": [
        {"path": "plugin.json", "bytes": len(plugin), "sha256": hashlib.sha256(plugin).hexdigest()}
    ]}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", plugin + (b" " if tampered else b""))
        archive.writestr("package-manifest.json", json.dumps(manifest))


@pytest.mark.parametrize("platform", ["windows-x64", "macos-arm64"])
def test_preserved_release_binds_bytes_and_source_without_local_paths(tmp_path, platform):
    archive = tmp_path / "candidate.zip"
    package(archive)
    output = tmp_path / "release"
    result = prepare(archive, platform, output, "a" * 40, "https://example.test/build/1")
    assert (output / result["archive"]).read_bytes() == archive.read_bytes()
    assert result["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(result)
    assert (output / f"SHA256SUMS-{platform}.txt").read_text().strip() == f'{result["sha256"]}  {result["archive"]}'


def test_corrupt_package_is_not_preserved_for_release(tmp_path):
    archive = tmp_path / "candidate.zip"
    package(archive, tampered=True)
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare(archive, "windows-x64", tmp_path / "release", "a" * 40, "https://example.test/build/1")
    assert not (tmp_path / "release").exists()


def test_unavailable_architecture_is_not_published(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        prepare(tmp_path / "unused.zip", "macos-x86_64", tmp_path / "release", "a" * 40, "https://example.test/build/1")
    assert not (tmp_path / "release").exists()
