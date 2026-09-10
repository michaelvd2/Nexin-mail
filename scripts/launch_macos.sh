#!/bin/sh
set -eu

plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
python="${NEXIN_MAIL_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1; then
  exit 70
fi
export PYTHONPATH="$plugin_root/src"
export PYTHONDONTWRITEBYTECODE=1
if ! "$python" -B -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 70)'; then
  exit 70
fi
exec "$python" -B -X utf8 -m nexin_mail.server
