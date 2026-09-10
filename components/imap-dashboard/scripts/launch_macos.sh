#!/bin/sh
set -eu

dashboard_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
backend_root=$(CDPATH= cd -- "$dashboard_root/../imap-plugin" && pwd -P)
python="$backend_root/runtime/venv/bin/python"
test -f "$backend_root/.codex-plugin/plugin.json"
test -f "$backend_root/src/imap_plugin/server.py"
test -x "$python"
export PYTHONPATH="$dashboard_root/src:$backend_root/src"
export PYTHONDONTWRITEBYTECODE=1
exec "$python" -m imap_dashboard.server
