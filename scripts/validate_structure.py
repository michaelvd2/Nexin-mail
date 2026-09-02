from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "imap-plugin"
    assert manifest.get("skills") == "./skills/"
    assert manifest.get("mcpServers") == "./.mcp.json"
    assert (ROOT / ".mcp.json").is_file()
    for required in ("AGENTS.md", "CODEX_INSTALL.md", "README.md", "PRIVACY.md"):
        assert (ROOT / required).is_file(), f"required repository instruction is missing: {required}"
    assert (ROOT / "docs" / "TROUBLESHOOTING.md").is_file()
    for required in ("install_macos.sh", "uninstall_macos.sh", "setup_macos.py", "review_macos.py"):
        assert (ROOT / "scripts" / required).is_file(), f"macOS support file is missing: {required}"
    skill = (ROOT / "skills" / "imap-plugin" / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", skill, re.DOTALL)
    assert match, "skill frontmatter is missing"
    assert re.search(r"(?m)^name:\s*imap-plugin\s*$", match.group(1))
    assert re.search(r"(?m)^description:\s*\S.+$", match.group(1))
    print("plugin and skill structure passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
