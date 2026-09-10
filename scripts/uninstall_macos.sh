#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This uninstaller supports macOS only." >&2
  exit 64
fi
command -v codex >/dev/null 2>&1 || { echo "Codex CLI is required." >&2; exit 69; }

program_base="$HOME/Library/Application Support/IMAP Plugin"
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if [ -f "$source_root/package-manifest.json" ] && [ -f "$source_root/uninstall_macos.sh" ]; then
  exec /bin/sh "$source_root/uninstall_macos.sh" "$@"
fi
distribution="$program_base/distribution"
marketplace_root=$(codex plugin marketplace list --json | python3 -c '
import json, sys
data=json.load(sys.stdin)
for item in data.get("marketplaces", []):
    if item.get("name") == "imap-plugin-handoff":
        print(item.get("root", "")); break
')
if [ -n "$marketplace_root" ]; then
  expected=$(cd -- "$distribution" && pwd -P)
  actual=$(cd -- "$marketplace_root" && pwd -P)
  if [ "$actual" != "$expected" ] || [ ! -f "$actual/release.json" ]; then
    echo "The matching marketplace has an unexpected identity; nothing was removed." >&2
    exit 73
  fi
  codex plugin remove 'imap-plugin@imap-plugin-handoff' --json >/dev/null
  codex plugin marketplace remove 'imap-plugin-handoff' --json >/dev/null
fi

echo "IMAP Plugin was unregistered. The program copy, mailbox settings, Keychain items, downloads, and backups were preserved."
