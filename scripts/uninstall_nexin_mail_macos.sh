#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Nexin Mail: deze uninstaller werkt alleen op macOS." >&2
  exit 64
fi
package_root=${NEXIN_MAIL_PACKAGE_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)}
runtime=""
for candidate in \
  "$package_root/payload/runtime/python/bin/python3" \
  "$package_root/payload/runtime/python/python3" \
  "$package_root/payload/runtime/python/python"; do
  if [ -f "$candidate" ] && [ -x "$candidate" ]; then runtime="$candidate"; break; fi
done
if [ -z "$runtime" ]; then
  echo "Nexin Mail: de private macOS-runtime ontbreekt; er is niets gewijzigd." >&2
  exit 70
fi
runtime_platform="$package_root/payload/runtime/python/.nexin-mail-platform"
if [ ! -f "$runtime_platform" ] || [ "$(cat "$runtime_platform")" != "macos-arm64" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "Nexin Mail: dit pakket is niet gebouwd voor deze macOS-architectuur; er is niets gewijzigd." >&2
  exit 70
fi
codex=${NEXIN_MAIL_CODEX:-$(command -v codex || true)}
if [ -z "$codex" ] || [ ! -f "$codex" ]; then
  echo "Nexin Mail: de native Codex CLI ontbreekt." >&2
  exit 69
fi
install_root=${NEXIN_MAIL_INSTALL_ROOT:-"$HOME/Library/Application Support/Nexin Mail"}
case "$install_root" in
  "$HOME"/*) ;;
  *) echo "Nexin Mail: installatie buiten de gebruikersmap geweigerd." >&2; exit 73 ;;
esac
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$package_root/payload/src"
exec "$runtime" -B -X utf8 -m nexin_mail.install uninstall \
  --install-root "$install_root" --codex "$codex" "$@"
