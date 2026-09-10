#!/bin/sh
# Native macOS bootstrap. No system Python, package manager, or privilege change.
set -eu
repository=''
release='v0.2.0-beta.3'
codex=''
prepare_only=0
skip_setup=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository) repository=$2; shift 2 ;;
    --codex) codex=$2; shift 2 ;;
    --skip-setup) skip_setup=1; shift ;;
    --prepare-only) prepare_only=1; shift ;;
    *) echo 'Usage: install_from_release.sh --repository OWNER/REPO [--codex PATH] [--prepare-only]' >&2; exit 64 ;;
  esac
done
printf '%s\n' "$repository" | /usr/bin/grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' || { echo 'Invalid repository identity.' >&2; exit 64; }
[ "$(uname -s)" = Darwin ] || { echo 'Use install_from_release.ps1 on Windows.' >&2; exit 64; }
architecture=$(uname -m)
# Detect Apple Silicon even when the calling shell runs under Rosetta.
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then architecture=arm64; fi
case "$architecture" in arm64) ;; x86_64) echo 'Intel Mac package unavailable: the pinned cryptography runtime has no compatible prebuilt package. Nothing installed.' >&2; exit 64 ;; *) echo 'Unsupported macOS architecture.' >&2; exit 64 ;; esac
if [ "$prepare_only" = 0 ] && [ -z "$codex" ]; then
  for candidate in /Applications/Codex.app/Contents/Resources/codex "$HOME/Applications/Codex.app/Contents/Resources/codex"; do
    if [ -x "$candidate" ]; then
      [ -z "$codex" ] || { echo 'Multiple Codex apps found; Codex must pass its exact --codex path.' >&2; exit 69; }
      codex=$candidate
    fi
  done
  [ -n "$codex" ] || { echo 'Native Codex app not found; pass its exact --codex path.' >&2; exit 69; }
fi
if [ "$prepare_only" = 0 ]; then
  [ -f "$codex" ] && [ -x "$codex" ] || { echo 'Native Codex executable missing.' >&2; exit 69; }
  /usr/bin/file -b "$codex" | /usr/bin/grep -q 'Mach-O' || { echo 'Codex must be a native executable, not a shell shim.' >&2; exit 69; }
fi
umask 077
work=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp/}nexin-mail.XXXXXXXX")
printf 'Preserving download and diagnostics in %s\n' "$work"
asset="Nexin-Mail-0.2.0-macos-$architecture.zip"
base="https://github.com/$repository/releases/download/$release"
/usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 --output "$work/checksums.txt" "$base/SHA256SUMS-macos-$architecture.txt"
expected=$(/usr/bin/awk -v name="$asset" '$2 == name { count++; hash=$1 } END { if (count != 1) exit 1; print hash }' "$work/checksums.txt")
printf '%s\n' "$expected" | /usr/bin/grep -Eq '^[a-f0-9]{64}$' || { echo 'Invalid release checksum.' >&2; exit 65; }
/usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 --output "$work/$asset" "$base/$asset"
actual=$(/usr/bin/shasum -a 256 "$work/$asset" | /usr/bin/awk '{print $1}')
[ "$actual" = "$expected" ] || { echo 'Release checksum mismatch; nothing installed.' >&2; exit 65; }
# Validate all ZIP entry paths and reject links before extraction.
/usr/bin/unzip -Z -1 "$work/$asset" > "$work/entries.txt"
/usr/bin/awk '
  /^\// || /\\/ || /:/ || /(^|\/)\.\.?($|\/)/ || /\/$/ || /\/\// { exit 1 }
  { key=tolower($0); if (seen[key]++) exit 1; count++ }
  END { if (!count) exit 1 }
' "$work/entries.txt" || { echo 'Unsafe release archive paths.' >&2; exit 65; }
/usr/bin/unzip -Z -l "$work/$asset" > "$work/zip-modes.txt"
if /usr/bin/grep -Eq '^[lbcpds]' "$work/zip-modes.txt"; then echo 'Release archive contains non-regular entries.' >&2; exit 65; fi
/bin/mkdir "$work/package"
/usr/bin/ditto -x -k "$work/$asset" "$work/package"
runtime="$work/package/payload/runtime/python/bin/python3"
export PYTHONPATH="$work/package/payload/src"
export PYTHONDONTWRITEBYTECODE=1
"$runtime" -B -X utf8 -c 'import sys; from pathlib import Path; from nexin_mail.package import verify; verify(Path(sys.argv[1])); print("Package manifest verified")' "$work/package"
if [ "$prepare_only" = 1 ]; then printf 'Verified package prepared: %s\n' "$work/package"; exit 0; fi
export NEXIN_MAIL_CODEX="$codex"
set --
if [ "$skip_setup" = 1 ]; then set -- --skip-setup; fi
if [ "$architecture" = arm64 ] && [ "$(uname -m)" != arm64 ]; then
  exec /usr/bin/arch -arm64 /bin/sh "$work/package/install_macos.sh" "$@"
fi
exec /bin/sh "$work/package/install_macos.sh" "$@"
