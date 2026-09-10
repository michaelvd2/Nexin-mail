from pathlib import Path
import io
import os
import stat
import tarfile

import pytest

from nexin_mail.build import assemble
from nexin_mail.package import verify
from scripts.build_macos_package import safe_extract


def test_standalone_windows_runtime_layout_is_accepted(tmp_path):
    source = Path(__file__).resolve().parents[2]
    runtime = tmp_path / "runtime"
    for name in ("python.exe", "python3.dll", "python312.dll", "Lib/os.py", "Lib/site-packages/mcp/__init__.py"):
        item = runtime / name
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"standalone runtime fixture")
    output = assemble(source, runtime, tmp_path / "bundle")
    assert verify(output)["product"] == "nexin-mail"


def _tar_member(name, data=None, *, mode=0o644, linkname=None):
    member = tarfile.TarInfo(name)
    member.mode = mode
    if linkname is not None:
        member.type = tarfile.SYMTYPE
        member.linkname = linkname
    else:
        member.size = len(data or b"")
    return member, data


def test_macos_upstream_links_are_materialized_as_regular_files(tmp_path):
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name in ("python", "python/bin"):
            member = tarfile.TarInfo(name + "/")
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            stream.addfile(member)
        member, data = _tar_member("python/bin/python3.12", b"runtime", mode=0o755)
        stream.addfile(member, io.BytesIO(data))
        member, data = _tar_member("python/bin/python3", linkname="python3.12")
        stream.addfile(member)
    root = safe_extract(archive, tmp_path / "extracted")
    target = root / "python" / "bin" / "python3"
    assert target.read_bytes() == b"runtime"
    assert not target.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE((target.parent / "python3.12").stat().st_mode)
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_macos_upstream_traversal_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        member, data = _tar_member("../escape", b"blocked")
        stream.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="traversal"):
        safe_extract(archive, tmp_path / "extracted")
    assert not (tmp_path / "escape").exists()
