# IMAP Plugin

Use your existing email account in Codex on Windows or macOS.

IMAP Plugin connects Codex directly to an IMAP mailbox on your computer. It works with most email providers that offer IMAP, so it is not tied to Gmail, Outlook, or any other single provider.

## What can it do?

- Find and read emails when you ask.
- Show recent messages and email conversations.
- Help identify important messages, action points, newsletters, and possible phishing.
- Prepare replies and send one reviewed message at a time.
- Move messages safely to folders such as Trash or Junk after confirmation.
- Download attachments with safer filenames and operating-system security markers.
- Add the optional [IMAP Dashboard](../imap-dashboard) for a visual inbox in Codex.

Nothing happens automatically just because the plugin is installed or opened. Reading, changing, downloading, and sending happen only when requested, with an extra review step before consequential actions.

## Private by design

Setup asks only for your email address and password (or app password). The plugin finds secure provider settings and checks the connection for you. Your password is saved by Windows Credential Manager or macOS Keychain. It is not placed in plugin files, configuration files, logs, or the installation package.

The plugin has no advertising, analytics, telemetry, hosted mail relay, or separate cloud account. Email content is only retrieved when you ask Codex to work with it, and there are no scheduled background mailbox checks.

## Install with Codex

You do not need to understand the source code or run technical commands yourself.

1. Copy the URL of this GitHub page.
2. Open a new task in Codex.
3. Paste the URL and this instruction:

   **Read `CODEX_INSTALL.md` and install this plugin.**

4. Codex checks your computer, installs the right version, and opens a private setup window. Enter only your email address and password.
5. When installation is complete, start a fresh Codex task and ask it to check your mail connection.

Codex can repair common installation problems and verifies the connection without sending or changing email.

## Add the visual dashboard

The optional [IMAP Dashboard](../imap-dashboard) adds a side-panel inbox with folders, messages, actions, and highlights. Install IMAP Plugin first, then give Codex the dashboard link and say:

**Read `CODEX_INSTALL.md` and install IMAP Dashboard. Use my existing IMAP Plugin setup.**

The dashboard uses the same local mailbox connection and protected login. You enter your email details only once, and both plugins remain available in Codex.

## What do I need?

- Windows 10/11 or macOS 13 or newer.
- Codex desktop or Codex CLI.
- An email provider that supports IMAP with TLS.
- Your email address and password or provider-issued app password.

Secure IMAP and optional SMTP settings are detected automatically. Providers that require OAuth and do not allow an app password are not supported in version 0.1.1.

## Current release

Downloadable files and checksums are available on the [latest release page](../../releases/latest). The current version is a beta: Windows and macOS are tested automatically, but the installers are not yet signed or notarized. For a first test, using a dedicated test mailbox is recommended.

## More information

- [Installation instructions for Codex](CODEX_INSTALL.md)
- [Privacy and security](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Technical architecture](docs/ARCHITECTURE.md)
- [License](LICENSE)
