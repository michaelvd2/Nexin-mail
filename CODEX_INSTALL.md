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

A normal request to install Nexin Mail includes connecting the mailbox. Continue
into the private account form automatically; do not require a separate request
to connect it. Registration or process exit code 0 is not completed installation.
The installer reports `installation_complete=false` until the mailbox connection
is verified. Follow the same setup session through its bounded waits. Only a
`ready` result with `mail_connection=verified` completes account setup; then open
the dashboard once. Cancellation, failure, and explicit `--skip-setup` leave
installation incomplete. Tell the user that state, never "installed and ready".

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

## Automatic installation owned by Codex

The user supplies the repository link and installation consent. Codex owns
platform detection, package selection, checksum verification, extraction,
native executable discovery, registration, and reading the result. Do not hand
those technical steps back to the user as a ZIP-and-command checklist.

Read the source bootstrap from the same repository before running it. Derive
`OWNER/REPO` from the user's exact GitHub repository URL or its verified origin;
never substitute another repository. Use the repository's default-branch source
for these bootstrap scripts, not an earlier plugin cache. The current bootstrap
selects the explicit [v0.2.0-beta.4 release](../../releases/tag/v0.2.0-beta.4).
GitHub's `/releases/latest` excludes prereleases: use the tag endpoint or list
including prereleases. No stable latest release does not mean no beta exists.

- **macOS:** run `/bin/sh scripts/install_from_release.sh --repository OWNER/REPO`.
  The script detects Apple Silicon (including Rosetta) and finds the
  native app in `/Applications` or the user's Applications folder.
- **Windows:** run `scripts/install_from_release.ps1 -Repository OWNER/REPO`
  from the authorized native PowerShell environment. It detects x64 and looks
  for the native executable on PATH and in installed Codex app packages.
- If discovery is missing or ambiguous, Codex inspects the actual installed app
  location and passes `--codex PATH` (macOS) or `-Codex PATH` (Windows). Do not
  ask the user to find executable paths. Do not choose a Node shim, WSL binary,
  another app, or an unrelated process. If no native app is installed, explain
  that concrete prerequisite.
- Respect native execution policy. Do not use ExecutionPolicy Bypass, remove
  download marks, or disable OS protections. If policy prevents execution,
  report its exact reason and retain the verified package for an allowed route.

Both scripts need only built-in OS tools before the package's private Python
runtime is available. They download the exact platform asset and its dedicated
SHA256SUMS file over HTTPS, verify the hash and archive paths before extraction,
then verify the package manifest and run the existing guarded installer.
`--skip-setup` or `-SkipSetup` explicitly stops after registration. Otherwise
installation starts the private setup session; an existing account gets a
read-only connection check without reopening the form.
`--prepare-only` or `-PrepareOnly` downloads and verifies without registering;
this is a diagnostic mode, not successful installation.

The release asset names are `Nexin-Mail-0.2.0-PLATFORM.zip`,
`SHA256SUMS-PLATFORM.txt`, and `build-provenance-PLATFORM.json`, where PLATFORM is
`windows-x64` or `macos-arm64`. Preserve downloaded evidence on
failure. Intel Mac is explicitly unsupported because the pinned cryptography
runtime has no compatible prebuilt package; do not downgrade it or improvise
a source build on the customer machine. Never select a source ZIP or improvise
a package for Linux, Windows ARM64, or a remote cloud host. This is an unsigned testing beta.

## Platform route

1. Confirm the operating system and architecture. Supported customer routes are
   Windows 10/11 x64 and macOS 13 or newer.
2. Run the automatic route above. It selects and verifies the complete package
   before invoking its platform installer. Do not require manual extraction.
3. Pass the exact native Codex executable path when the installer supports
   `--codex`; do not guess from a shell shim, WSL, or an unrelated process.
4. Read `setup_session` in the installer result. It includes the session ID,
   exact installed-runtime `wait_command` argument array and `pythonpath`.
   The command includes the exact session directory, so a new task can resume
   even if its environment differs; preserve those arguments.
   Invoke that command with the given PYTHONPATH through the host's yielding
   process tool. Do not concatenate arguments into a shell string. Wait up to
   50 seconds per call, then resume the same session while it is pending. This
   waiting uses no model work between results. Stay active; do not ask the user
   to type done, repeatedly announce waiting, restart setup, or finalize while
   the form is pending. Host/tool timeout means resume the receipt, not failure.
5. If the plugin tools are already available, `wait_setup(session_id,
   timeout_seconds=50)` provides the same bounded wait. `setup_status` exposes
   the saved session after host interruption. `open_setup` reuses an existing
   session; `new_attempt=true` is only for an explicitly requested fresh attempt
   after the previous attempt has ended and the recovery condition is met.
6. Follow the returned `next_action`: `ready` means the read-only connection
   check passed; call `render_mail_view` once and verify visible dashboard
   acceptance. `cancelled` means stop. `failed` includes a typed recovery guide:
   diagnose that cause and do not repeat an unchanged login attempt. For
   `interrupted`, inspect the existing setup owner/window; never open a second
   possibly live form. A persisted session cannot by itself prove the window
   was displayed or accepted by the user.
7. A plugin-discovery limitation does not block waiting: use the exact installed
   runtime command from the receipt. If a fresh task is needed to render the
   dashboard, identify that remaining host step; never rerun installation or
   lose track of the user's active popup.

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
