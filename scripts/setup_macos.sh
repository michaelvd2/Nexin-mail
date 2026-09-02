#!/bin/sh
set -eu

plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python="$plugin_root/runtime/venv/bin/python"
if [ ! -x "$python" ]; then
  exit 70
fi
export PYTHONPATH="$plugin_root/src"
export PYTHONDONTWRITEBYTECODE=1
exec "$python" "$plugin_root/scripts/setup_macos.py"
