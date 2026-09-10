#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Nexin Mail: deze uninstaller werkt alleen op macOS." >&2
  exit 64
fi
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -f "$root/payload/scripts/uninstall_nexin_mail_macos.sh" ]; then
  script="$root/payload/scripts/uninstall_nexin_mail_macos.sh"
elif [ -f "$root/scripts/uninstall_nexin_mail_macos.sh" ]; then
  script="$root/scripts/uninstall_nexin_mail_macos.sh"
else
  script="$root/../scripts/uninstall_nexin_mail_macos.sh"
fi
NEXIN_MAIL_PACKAGE_ROOT="$root" exec /bin/sh "$script" "$@"
