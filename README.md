# Nexin Mail

Nexin Mail gives Codex one local mail product: bounded text tools and a bundled
mail dashboard that use the same mailbox connection and state. The backend is
in `src/nexin_mail`; the dashboard component is kept in
`components/imap-dashboard` with its own license and provenance. It is part of
this repository and does not require a separately installed sibling plugin.

## What it does

- Find and read messages when you ask.
- Prepare replies and other changes for explicit native review.
- Show the same mailbox in the dashboard when the host supports it.
- Keep installation, account setup, read-only health, sending, and dashboard
  acceptance as separate steps.

The product has one lazy MCP server, `python -m nexin_mail.server`. Installing
the package does not read mail, send mail, or create credentials. Mail content
requested for Codex analysis can enter the host or model service; local viewing
does not imply that all analysis is local.

## Install on your computer

Give Codex this repository link and say **"Install Nexin Mail on this computer."**
Codex follows [CODEX_INSTALL.md](CODEX_INSTALL.md), detects the operating system
and architecture, downloads and verifies the matching complete package, and
registers it with the local native Codex app, and opens the private setup form.
Codex waits quietly while you fill it in, resumes after an interrupted wait,
checks the connection, and continues to the dashboard. Cancellation stops setup;
a failure returns a specific recovery step without retrying your login.
You do not need to choose a ZIP,
install Python, or run commands yourself. Enter account credentials only in the
private native setup window when you are ready to connect your mailbox.

The [cross-platform beta release](../../releases/tag/v0.2.0-beta.4) provides
Windows x64 and Apple Silicon Mac packages with their own checksums
and build provenance. This is an unsigned testing beta. Native OS prompts and
account setup can still require your input. The automatic GitHub **Source code**
archives are not installers. Intel Mac (no compatible prebuilt cryptography runtime), Linux, Windows ARM64,
and a remote ChatGPT cloud
session are not supported installation targets for this local plugin.

## Install with Codex

If you share only this repository URL, Codex should ask in Dutch:

**“Zal ik Nexin Mail installeren en je mail instellen?”**

A link alone is not permission to download, install, open setup, or access mail.
After an explicit confirmation, Codex follows [CODEX_INSTALL.md](CODEX_INSTALL.md)
and uses a verified platform package. A GitHub source ZIP and the repository's
development `.mcp.json` are not customer installers. The development entry is
for a local Python 3.12 checkout and does not make local stdio available to
ChatGPT cloud; release installers derive machine-specific registration outside
the immutable package data.

The private native setup asks for an email address and a password or app
password only in its masked window. Never place credentials in chat, commands,
environment variables, logs, configuration files, or this repository.

## Requirements and limits

The candidate package targets Windows 10/11 x64 and macOS 13 or newer. It is a
beta and is not yet a signed or notarized customer release. Microsoft OAuth,
provider capabilities, native OS registration, and visible dashboard behavior
still require platform-specific acceptance. Do not claim a connected mailbox
from package installation alone.

See [CODEX_INSTALL.md](CODEX_INSTALL.md), [PRIVACY.md](PRIVACY.md),
[docs/SECURITY.md](docs/SECURITY.md), [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [LICENSE](LICENSE).
