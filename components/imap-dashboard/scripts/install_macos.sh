#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer supports macOS only." >&2
  exit 64
fi
command -v codex >/dev/null 2>&1 || { echo "Codex CLI is required." >&2; exit 69; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3.12 is required to verify the installation." >&2; exit 69; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' || {
  echo "Python 3.12.x is required to verify the installation." >&2
  exit 69
}

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
program_root="$HOME/Library/Application Support/IMAP Plugin"
backend="$program_root/distribution/plugins/imap-plugin"
python="$backend/runtime/venv/bin/python"
doctor="$backend/scripts/doctor_macos.sh"
test -x "$python" || { echo "Install and verify the IMAP Plugin first." >&2; exit 69; }
test -x "$doctor" || { echo "The IMAP Plugin doctor is missing." >&2; exit 69; }

python3 "$source_root/scripts/privacy_scan.py" "$source_root"
python3 "$source_root/scripts/validate_structure.py"
python3 "$source_root/scripts/verify_backend.py" "$program_root"
"$doctor" >/dev/null
"$python" "$source_root/scripts/install_dashboard.py" --source-root "$source_root"
codex plugin add 'imap-dashboard@imap-plugin-handoff' --json >/dev/null

echo '{"status":"installed_and_verified","plugin":"imap-dashboard@imap-plugin-handoff","reused_existing_connection":true,"credentials_changed":false,"configuration_changed":false,"backend_connectivity":"pass"}'
