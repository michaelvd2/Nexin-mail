#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer supports macOS only." >&2
  exit 64
fi
command -v codex >/dev/null 2>&1 || { echo "Codex CLI is required." >&2; exit 69; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3.12 is required." >&2; exit 69; }

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' || {
  echo "Python 3.12.x is required; no other Python version is accepted by this release." >&2
  exit 69
}
python3 "$source_root/scripts/privacy_scan.py" "$source_root"
python3 "$source_root/scripts/validate_structure.py"

program_base="$HOME/Library/Application Support/IMAP Plugin"
distribution="$program_base/distribution"
staging="$program_base/.distribution-new-$$"
backup="$program_base/backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
case "$staging" in
  "$program_base"/*) ;;
  *) echo "Refusing an installation path outside the IMAP Plugin directory." >&2; exit 73 ;;
esac
if [ -e "$staging" ]; then
  echo "The staging directory already exists; nothing was changed." >&2
  exit 73
fi

cleanup() {
  if [ -d "$staging" ]; then
    rm -rf -- "$staging"
  fi
}
trap cleanup EXIT INT TERM

payload="$staging/plugins/imap-plugin"
mkdir -p "$payload" "$staging/.agents/plugins"
cp -R "$source_root/.codex-plugin" "$source_root/skills" "$source_root/src" "$payload/"
mkdir -p "$payload/scripts" "$payload/runtime"
for file in autoconfigure.py configure.py doctor_macos.sh launch_macos.sh review_macos.py setup_macos.py setup_macos.sh; do
  cp "$source_root/scripts/$file" "$payload/scripts/$file"
done
for file in AGENTS.md CHANGELOG.md CODEX_INSTALL.md LICENSE PRIVACY.md README.md pyproject.toml requirements-runtime.lock; do
  cp "$source_root/$file" "$payload/$file"
done
cp -R "$source_root/docs" "$payload/"
cp "$source_root/handoff/marketplace.json" "$staging/.agents/plugins/marketplace.json"
cat > "$staging/release.json" <<'JSON'
{"product":"imap-plugin-macos-source-installer","version":"0.1.3","platform":"macos","marketplace":"imap-plugin-handoff"}
JSON

python3 -m venv "$payload/runtime/venv"
"$payload/runtime/venv/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes --requirement "$payload/requirements-runtime.lock"

PLUGIN_ROOT="$payload" "$payload/runtime/venv/bin/python" - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["PLUGIN_ROOT"]).resolve()
value = {
    "mcpServers": {
        "imap": {
            "title": "IMAP Plugin",
            "description": "Provider-independent local IMAP/SMTP connector with native macOS review for every change.",
            "cwd": str(root),
            "command": str(root / "runtime" / "venv" / "bin" / "python"),
            "args": ["-m", "imap_plugin.server"],
            "env": {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            "startup_timeout_sec": 20,
            "tool_timeout_sec": 360,
        }
    }
}
(root / ".mcp.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
PY

STAGING_ROOT="$staging" BACKEND_ROOT="$payload" python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

staging = Path(os.environ["STAGING_ROOT"]).resolve()
backend = Path(os.environ["BACKEND_ROOT"]).resolve()
files = []
for path in sorted(item for item in backend.rglob("*") if item.is_file()):
    relative = path.relative_to(staging).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
manifest = {
    "schema": 1,
    "product": "imap-plugin-installed-backend",
    "version": "0.1.3",
    "platform": "macos",
    "root": "plugins/imap-plugin",
    "files": files,
}
(staging / "backend-integrity.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
PY

if [ -d "$distribution" ]; then
  mkdir -p "$(dirname -- "$backup")"
  mv -- "$distribution" "$backup"
fi
mv -- "$staging" "$distribution"
trap - EXIT INT TERM

marketplace_root=$(codex plugin marketplace list --json | python3 -c '
import json, sys
data=json.load(sys.stdin)
for item in data.get("marketplaces", []):
    if item.get("name") == "imap-plugin-handoff":
        print(item.get("root", "")); break
')
if [ -n "$marketplace_root" ] && [ "$(cd -- "$marketplace_root" && pwd -P)" != "$(cd -- "$distribution" && pwd -P)" ]; then
  echo "A marketplace named imap-plugin-handoff already points elsewhere; the program copy is preserved but was not registered." >&2
  exit 73
fi
if [ -z "$marketplace_root" ]; then
  codex plugin marketplace add "$distribution" --json >/dev/null
fi
codex plugin add 'imap-plugin@imap-plugin-handoff' --json >/dev/null
"$distribution/plugins/imap-plugin/scripts/setup_macos.sh"
"$distribution/plugins/imap-plugin/scripts/doctor_macos.sh"

echo "IMAP Plugin is installed and its read-only connection passed. Start a new Codex task before using it."
