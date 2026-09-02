# Operations

## Enrollment

On Windows, `scripts/enroll_gui.ps1` asks only for an email address and one masked password or app password, then stores the password in Windows Credential Manager after a successful IMAP check. On macOS, `scripts/setup_macos.py` provides the same two-field flow and stores the password in Keychain. Provider settings are discovered automatically; Codex may supply nonsecret official-provider hints after a safe domain-only lookup. Only nonsecret settings are written under `%LOCALAPPDATA%\imap-plugin` on Windows or `~/Library/Application Support/IMAP Plugin` on macOS.

IMAP supports implicit TLS and mandatory STARTTLS. SMTP supports the same two protected modes. Plaintext transport, IP-literal server targets, disabled certificate validation, and unverified hostnames are rejected.

The plugin does not register a scheduled task or launch agent and never polls the mailbox in the background.

## Capability gates

Setup and the platform doctor verify TLS, authentication, folders, SPECIAL-USE mappings, MOVE, UIDPLUS, and optional SMTP authentication without sending a message. Reading requires only a valid protected IMAP connection. Consequential features remain unavailable unless their exact prerequisites are proven.

- Safe Trash requires a verified Trash folder, MOVE, and UIDPLUS.
- Junk requires a verified Junk folder, MOVE, and UIDPLUS.
- Draft/save/send requires verified Drafts, Sent, and Trash folders plus safe MOVE.
- Sending additionally requires configured SMTP and a separately reviewed saved draft.

## Local state

Configuration and bounded metadata state stay under the platform application-data directory. Confirmed attachments are written only to the current user's `Downloads/IMAP Plugin`. Logs never accept message bodies, subjects, addresses, credentials, attachment bytes, or unsubscribe URLs.

## Recovery

- A stale or changed proposal must be reviewed again.
- An ambiguous SMTP result is never retried automatically.
- A reversible move can be restored only while its stable server references remain valid.
- A UIDVALIDITY change invalidates old message references and approvals.
- The platform uninstaller removes registration but preserves local data and credentials by design.

## Acceptance boundary

Automated tests use fake IMAP and SMTP transports and run on Windows and macOS CI. A production claim requires a separate clean-machine installation, read-only health verification, capability checks, rollback verification, and explicitly authorized tests using a dedicated mailbox on each platform. No live mailbox mutation is part of ordinary build verification.
