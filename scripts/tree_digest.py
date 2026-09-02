from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "receipts" / "build-tree.sha256"
INCLUDE = [
    ROOT / ".codex-plugin",
    ROOT / "src",
    ROOT / "scripts",
    ROOT / "skills",
    ROOT / "tests",
    ROOT / "docs",
]
FILES = [
    ROOT / ".mcp.json",
    ROOT / "AGENTS.md",
    ROOT / "CODEX_INSTALL.md",
    ROOT / "pyproject.toml",
    ROOT / "requirements-runtime.lock",
    ROOT / "requirements-dev.lock",
    ROOT / "README.md",
    ROOT / "LICENSE",
]


def main() -> None:
    paths = list(FILES)
    for directory in INCLUDE:
        paths.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    OUTPUT.write_text(digest.hexdigest() + "  imap-plugin-source-tree\n", encoding="ascii")
    print(digest.hexdigest())


if __name__ == "__main__":
    main()
