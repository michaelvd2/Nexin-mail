from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "nexin-mail"
    assert manifest["version"] == "0.2.0"
    assert manifest.get("skills") == "./skills/"
    assert manifest.get("mcpServers") == "./.mcp.json"
    mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert set(mcp["mcpServers"]) == {"mail"}
    server = mcp["mcpServers"]["mail"]
    assert server["command"] == "python"
    assert server["args"][-2:] == ["-m", "nexin_mail.server"]
    assert not Path(server["command"]).is_absolute()
    for required in ("AGENTS.md", "CODEX_INSTALL.md", "README.md", "PRIVACY.md"):
        assert (ROOT / required).is_file(), f"required repository instruction is missing: {required}"
    assert (ROOT / "docs" / "TROUBLESHOOTING.md").is_file()
    assert (ROOT / "docs" / "SETUP_RECOVERY.md").is_file()
    for required in (
        "autoconfigure.py",
        "install_macos.sh",
        "uninstall_macos.sh",
        "setup_macos.py",
        "review_macos.py",
        "launch.cmd",
        "launch_macos.sh",
    ):
        assert (ROOT / "scripts" / required).is_file(), f"macOS support file is missing: {required}"
    installer_text = (ROOT / "scripts" / "install_macos.sh").read_text(encoding="utf-8")
    assert "imap-plugin" not in installer_text
    assert "nexin-mail/install_macos.sh" in installer_text
    skill = (ROOT / "skills" / "nexin-mail" / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", skill, re.DOTALL)
    assert match, "skill frontmatter is missing"
    assert re.search(r"(?m)^name:\s*nexin-mail\s*$", match.group(1))
    assert re.search(r"(?m)^description:\s*\S.+$", match.group(1))
    assert skill == (ROOT / "nexin-mail" / "skills" / "nexin-mail" / "SKILL.md").read_text(encoding="utf-8")
    assert (ROOT / "src" / "nexin_mail" / "server.py").is_file()
    assert (ROOT / "nexin-mail" / "plugin.json").is_file()
    assert (ROOT / "components" / "imap-dashboard" / "LICENSE").is_file()
    for document in ("README.md", "CODEX_INSTALL.md", "AGENTS.md"):
        text = (ROOT / document).read_text(encoding="utf-8")
        assert "Nexin Mail" in text
        assert "../imap-dashboard" not in text
        assert "Install IMAP Plugin first" not in text
        assert "optional IMAP Dashboard" not in text
    assert "imap" not in json.dumps(mcp).casefold()
    print("plugin and skill structure passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
