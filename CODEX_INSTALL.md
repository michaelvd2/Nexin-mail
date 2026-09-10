# Install Nexin Mail with Codex

This file applies when the user has explicitly asked to install Nexin Mail. If
the message contains only a repository URL or neutral context, ask first in the
user's language. For Dutch, ask exactly: **“Zal ik Nexin Mail installeren en je
mail instellen?”** A link alone is not authorization.

Read `AGENTS.md` and `docs/TROUBLESHOOTING.md` before changing the local system.
Use a complete, hash-verified platform package with its private Python runtime.
Do not treat a GitHub source ZIP, system Python, pip environment, or the source
`.mcp.json` as a customer installation. The package contains one plugin, one
lazy `nexin_mail.server`, and the bundled dashboard component.

The source `.mcp.json` is a local development entry only. It requires a local
Python 3.12 checkout and does not make local stdio available to ChatGPT cloud.
Installed packages generate absolute, machine-specific MCP registration as
derived state outside the immutable package manifest.

## Safety rules

- Never ask for, display, copy, or handle a mailbox password in chat, a command,
  an environment variable, a log, or a file.
- The user enters credentials personally in the masked native setup window.
- Do not disable TLS verification, Gatekeeper, antivirus, endpoint protection,
  download marks, or Codex safety controls.
- Installation is read-only. Do not send, draft, move, delete, unsubscribe, or
  download an attachment as an installation test.
- Preserve verified downloads, existing settings, credentials, backups, and
  unrelated marketplace or registry entries when a step fails.

## Release discovery

For Windows x64, use the explicitly published
[v0.2.0-beta.1 release](../../releases/tag/v0.2.0-beta.1):
`Nexin-Mail-0.2.0-windows-x64.zip`, `SHA256SUMS.txt`, and
`build-provenance.json`. Verify that the archive name and SHA256 agree with both
metadata files before extraction. This is an unsigned testing beta.

The release is a **prerelease**: GitHub's `/releases/latest` endpoint may return
404 even when it exists. Query `/releases/tags/v0.2.0-beta.1` or list releases
including prereleases. Never interpret a missing stable latest release as
proof that no installable beta exists. Do not select the automatic source ZIP
or tarball. This release only supplies Windows x64; a macOS package must be
verified separately before installation.

## Platform route

1. Confirm the operating system and architecture. Supported customer routes are
   Windows 10/11 x64 and macOS 13 or newer.
2. Verify the release identity and SHA256 before extraction. Extract to a new
   private directory and run the package's platform installer:
   `install.cmd` on Windows or `install_macos.sh` on macOS.
3. Pass the exact native Codex executable path when the installer supports
   `--codex`; do not guess from a shell shim, WSL, or an unrelated process.
4. Check the structured installer result. It proves package and registration
   gates only. Follow with `setup_status`, then use `open_setup` only after the
   user has authorized account setup.
5. Run the read-only health check. Open the dashboard once when the host
   supports it, and record visible dashboard acceptance separately from the
   installer and mailbox checks. Start a new Codex task if plugin discovery
   requires it.

If setup or registration fails, read `docs/SETUP_RECOVERY.md` and
`docs/TROUBLESHOOTING.md`, preserve the healthy state, and repair only the
demonstrated local cause. Never weaken a hash, manifest, TLS, native-review,
capability, or identity gate. Do not retry a possibly executed mail action.

## Development checks

For source changes, run focused tests from `tests/`, then run
`python3 scripts/privacy_scan.py .` and `python3 scripts/validate_structure.py`.
Keep Windows and macOS package behavior aligned. Do not add scheduled tasks,
launch agents, background mailbox polling, credentials, or provider-specific
assumptions.
