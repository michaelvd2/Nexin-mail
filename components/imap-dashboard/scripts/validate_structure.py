from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


REQUIRED = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODEX_INSTALL.md",
    "README.md",
    "PRIVACY.md",
    "scripts/install_dashboard.py",
    "scripts/git_history_privacy_scan.py",
    "scripts/launch.cmd",
    "scripts/launch_macos.sh",
    "scripts/package_owner_path_scan.py",
    "scripts/verify_backend.py",
    "scripts/verify_backend.ps1",
    "skills/imap-dashboard/SKILL.md",
    "src/imap_dashboard/server.py",
    "web/src/App.tsx",
)


def validate(root: Path) -> None:
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"missing required files: {missing}")
    plugin = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if plugin.get("name") != "imap-dashboard" or plugin.get("mcpServers") != "./.mcp.json":
        raise RuntimeError("invalid plugin manifest")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    package = json.loads((root / "web" / "package.json").read_text(encoding="utf-8"))
    init_text = (root / "src" / "imap_dashboard" / "__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'(?m)^__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$', init_text)
    if not init_version or {plugin.get("version"), project.get("version"), package.get("version"), init_version.group(1)} != {"0.1.2"}:
        raise RuntimeError("dashboard version declarations do not agree")
    mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp.get("mcpServers", {}).get("imap-dashboard", {})
    if server.get("command", "").casefold() != "cmd.exe" or server.get("cwd") != ".":
        raise RuntimeError("source MCP launcher is not portable for the Windows release")
    source = (root / "src" / "imap_dashboard" / "server.py").read_text(encoding="utf-8")
    required_fragments = (
        "from imap_plugin.bridge import MailBridge",
        "from imap_plugin.operator import MailOperator",
        '"allowInline": False',
        '"surface": "side-panel"',
    )
    if any(fragment not in source for fragment in required_fragments):
        raise RuntimeError("dashboard server does not enforce the existing IMAP Plugin connection or side panel")
    forbidden = ("class WindowsCredentialStore", "class MacKeychainCredentialStore", "DEFAULT_HOST =")
    if any(fragment in source for fragment in forbidden):
        raise RuntimeError("dashboard contains a duplicated connector or credential implementation")
    frontend = (root / "web" / "vite.config.ts").read_text(encoding="utf-8")
    if 'outDir: "../src/imap_dashboard/ui"' not in frontend:
        raise RuntimeError("frontend output does not target the packaged dashboard UI")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    action_refs = re.findall(r"(?m)^\s*-\s+uses:\s+[^@\s]+@([^\s#]+)", workflow)
    if not action_refs or any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in action_refs):
        raise RuntimeError("CI actions are not pinned to immutable commit hashes")
    if re.search(r"(?m)^\s+ref:\s+[0-9a-f]{40}\s*$", workflow) is None:
        raise RuntimeError("CI does not pin the sibling IMAP Plugin revision")
    if "--require-hashes" not in workflow or "--hash=sha256:" not in (root / "requirements-dev.lock").read_text(encoding="utf-8"):
        raise RuntimeError("Python test artifacts are not hash-locked")
    forbidden_labels = ("shared" + " backend", "shared" + "_backend", "shared" + "-backend")
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", "node_modules", "dist", "__pycache__"} for part in path.parts):
            continue
        if path.suffix.casefold() not in {".cmd", ".html", ".json", ".md", ".ps1", ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}:
            continue
        lowered = path.read_text(encoding="utf-8-sig").casefold()
        if any(label in lowered for label in forbidden_labels):
            raise RuntimeError(f"customer-facing retired label remains in {path.relative_to(root)}")


def main() -> None:
    root = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()).resolve()
    try:
        validate(root)
    except Exception as exc:
        print(f"dashboard structure failed: {exc}")
        raise SystemExit(1)
    print("dashboard plugin and existing-connection structure passed")


if __name__ == "__main__":
    main()
