# IMAP Plugin — Windows handoff

This package contains the provider-independent plugin, a pinned 64-bit Windows Python runtime, dependency copies, integrity hashes, installer, verifier, uninstaller, and the Codex installation skill.

When this package is handled by Codex, `CODEX_INSTALL.md` is the cross-platform entry instruction and `SKILL.md` is the Windows package-specific execution policy.

## Installation

1. Extract the ZIP to a new local folder.
2. Read `SKILL.md` completely.
3. Run `powershell.exe -NoLogo -NoProfile -File .\verify.ps1`.
4. Run `powershell.exe -NoLogo -NoProfile -STA -File .\install.ps1`.
5. Enter the IMAP and optional SMTP settings only in the native Windows form.
6. Require the final read-only doctor result to pass.
7. Start a new Codex task and confirm `setup_status` and `mail_health`.

Passwords or app passwords must never be placed in chat, shell commands, environment variables, or files.

## Compatibility

- Windows 10 or 11, 64-bit.
- Codex desktop or CLI installed for the current Windows user.
- A standards-based IMAP server using implicit TLS or mandatory STARTTLS.
- Username/password or app-password authentication.
- Optional SMTP using implicit TLS or mandatory STARTTLS.

OAuth-only authentication is not supported in version 0.1.0. Provider-specific mailbox capabilities determine whether Trash, Junk, drafts, restore, and sending are available.

## Rollback

Run `powershell.exe -NoLogo -NoProfile -File .\uninstall.ps1`. This removes Codex registration while preserving the program copy, local settings, and Windows credentials. Deleting those items requires a separate explicit user decision.
