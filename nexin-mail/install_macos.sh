#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Nexin Mail: deze installer werkt alleen op macOS." >&2
  exit 64
fi
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -f "$root/payload/scripts/install_nexin_mail_macos.sh" ]; then
  script="$root/payload/scripts/install_nexin_mail_macos.sh"
elif [ -f "$root/scripts/install_nexin_mail_macos.sh" ]; then
  script="$root/scripts/install_nexin_mail_macos.sh"
else
  script="$root/../scripts/install_nexin_mail_macos.sh"
fi
NEXIN_MAIL_PACKAGE_ROOT="$root" exec /bin/sh "$script" "$@"
