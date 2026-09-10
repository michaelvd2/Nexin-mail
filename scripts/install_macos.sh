#!/bin/sh
set -eu

# Keep the source checkout and the immutable package on one installation path.
# This wrapper never creates a source venv or a legacy IMAP registration.
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if [ -f "$source_root/nexin-mail/install_macos.sh" ]; then
  exec /bin/sh "$source_root/nexin-mail/install_macos.sh" "$@"
fi
if [ -f "$source_root/../install_macos.sh" ]; then
  exec /bin/sh "$source_root/../install_macos.sh" "$@"
fi
echo "Nexin Mail: the verified package installer is missing; no changes were made." >&2
exit 70
