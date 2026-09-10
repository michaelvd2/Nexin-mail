# IMAP Dashboard

IMAP Dashboard puts your mailbox in a clear Codex side panel. It works with any standards-based IMAP mailbox supported by [IMAP Plugin](../imap-plugin), without a Google Drive download or a separate website account.

The Dashboard and IMAP Plugin remain two separate Codex plugins. Both stay available, while your mailbox login is entered only once.

## What it does

- Shows folders, recent messages, threads and attachments in one mailbox view.
- Keeps links and remote images blocked until you deliberately review them.
- Helps spot suspicious messages and important actions without treating email text as instructions.
- Lets you prepare replies and drafts.
- Can move, save, unsubscribe, download or send only after an exact confirmation on screen.
- Never permanently deletes mail and never retries a send automatically.

## Install with Codex

Copy this repository link into a new Codex task and say:

> Read `CODEX_INSTALL.md` and install IMAP Dashboard.

Codex does the platform checks and installs the right files for Windows or macOS. If IMAP Plugin is not installed yet, Codex installs it first and opens a private setup window. You enter only:

1. Your email address.
2. Your password or provider-issued app password.

Secure server settings are found automatically. The Dashboard then uses that same protected connection, so there is no second login form.

Windows users can also download `imap-dashboard.zip` from the [latest release](../../releases/latest). On macOS, let Codex follow the source installation in `CODEX_INSTALL.md`.

## Privacy and safety

- No hosted service, analytics, advertising or API key.
- No mailbox password, real email address, customer data or personal computer path is included in this repository or its release package.
- Passwords stay in Windows Credential Manager or macOS Keychain.
- Mail remains on your computer and mail server; the Dashboard does not create a second credential or configuration store.
- Opening the side panel is read-only and starts no background mailbox check.
- Attachments are never opened automatically.

See [Privacy](PRIVACY.md) and [Security](docs/SECURITY.md) for the complete boundaries.

## Current status

Windows and macOS are tested automatically. This is a beta and the installers are not yet signed or notarized. Use a dedicated test mailbox for the first clean-machine acceptance.

## Development

Contributor instructions are in [AGENTS.md](AGENTS.md). The production side panel is built from `web/` into the packaged HTML file under `src/imap_dashboard/ui/`.

## License

MIT. See [LICENSE](LICENSE).
