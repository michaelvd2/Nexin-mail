# IMAP Plugin

IMAP Plugin is a provider-independent Codex plugin for connecting one mailbox locally on Windows or macOS. The user supplies the server, port, username, authentication secret, and TLS mode; no provider, domain, account, or mailbox is built in.

> **Beta:** Windows and macOS run in CI, and the Windows handoff is self-verifying. The installers are not yet signed or notarized, and live clean-machine acceptance is still required on each platform. Use a dedicated test mailbox until that acceptance is complete.

## Compatibility

- Windows 10/11 x64, or macOS 13 or newer.
- Codex desktop or CLI installed for the current user.
- A standards-based IMAP server using implicit TLS or mandatory STARTTLS.
- Username/password or provider-issued app-password authentication.
- Optional SMTP using implicit TLS or mandatory STARTTLS.

OAuth-only providers are not supported in version 0.1.0. Read operations work across ordinary IMAP folders. Actions such as safe Trash, Junk, drafts, restore, and sending remain unavailable unless the server proves the required capabilities and SPECIAL-USE folders.

## Capabilities

- Bounded folder listing, recent-message listing, search, message and thread reading.
- Local advisory phishing, priority, cleanup, and advertising classification.
- Exact native review before every mailbox or settings change.
- Reversible move-to-Trash only; no permanent delete or expunge.
- Reviewed single-message drafting and sending when SMTP and safe mailbox capabilities are available.
- Reviewed attachment download with safe naming, a Windows Mark of the Web or macOS quarantine marker, and an operating-system scan when available.
- Guarded RFC 8058 and browser-based unsubscribe workflows.

## Privacy and safety

Mail content is treated as untrusted data. Passwords are entered only in a masked local form and stored in Windows Credential Manager or macOS Keychain. Configuration files contain server settings but never passwords, tokens, or mailbox content. The plugin has no hosted backend, telemetry, analytics, or automatic sending.

See [Security](docs/SECURITY.md) and [Operations](docs/OPERATIONS.md) for the exact boundaries.

## Let Codex install it

Give Codex the URL of this repository and say: **“Read `CODEX_INSTALL.md` and install this plugin.”** Codex detects Windows or macOS, verifies the relevant files, runs the platform installer, pauses for the user's private masked password entry, and completes a read-only acceptance check.

See [CODEX_INSTALL.md](CODEX_INSTALL.md) for the complete cross-platform instruction.
Codex-specific repository guidance lives in [AGENTS.md](AGENTS.md), with bounded repair steps in [Troubleshooting](docs/TROUBLESHOOTING.md).

## Optional dashboard

[IMAP Dashboard](../imap-dashboard) is a separate, optional Codex plugin that adds a side-panel mailbox interface. Install the IMAP Plugin backend first, then give Codex the dashboard repository URL and ask it to read `CODEX_INSTALL.md` and install the dashboard.

The dashboard reuses this plugin's local connector, configuration, protected credential identity, state, and action engine. Mailbox details are entered only once: the dashboard never asks for, copies, or stores a second password. Both plugins remain installed and independently available in Codex.

## Install on Windows

1. Download `imap-plugin-windows-x64.zip` from the [latest GitHub Release](../../releases/latest).
2. Extract the archive to a new folder.
3. Run `verify.ps1` from that extracted folder.
4. Run `install.ps1` and enter the mailbox settings only in the native setup window.
5. Start a new Codex task and call `setup_status` followed by `mail_health`.

The included `SKILL.md` gives a receiving Codex task the same installation and safety instructions. `uninstall.ps1` removes Codex registration while preserving local mailbox settings and credentials unless the user separately requests their deletion.

## Install on macOS

The macOS source installer is intentionally explicit while the notarized release archive is still pending:

```sh
./scripts/install_macos.sh
```

It requires Python 3.12, creates an isolated local environment under `~/Library/Application Support/IMAP Plugin`, installs the pinned dependencies, writes a local platform launcher, registers the plugin, opens the masked Keychain-backed setup, and runs the read-only doctor. `scripts/uninstall_macos.sh` unregisters the plugin but preserves settings, Keychain items, downloads, and backups. Do not pipe an installer from the web directly into a shell; download or clone the repository and inspect it first.

## Development

Windows:

```powershell
powershell.exe -NoLogo -NoProfile -File .\scripts\build_runtime.ps1
.\runtime\python\python.exe -m pytest tests
powershell.exe -NoLogo -NoProfile -File .\scripts\build_handoff.ps1
```

Portable checks on Windows or macOS:

```sh
python -m pip install -r requirements-runtime.lock -r requirements-dev.lock
PYTHONPATH=src IMAP_PLUGIN_TEST_MODE=1 python -m pytest tests
python scripts/privacy_scan.py .
python scripts/validate_structure.py
```

The Windows build produces a self-contained archive with a pinned Python runtime, file manifest, installer, verifier, and rollback script. macOS currently uses the source installer and needs live signing/notarization acceptance before a prebuilt release is claimed.

## License

MIT. See [LICENSE](LICENSE).
