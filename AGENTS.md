# Codex guidance for Nexin Mail

This repository contains one Nexin Mail product: the unified backend in
`src/nexin_mail`, one plugin surface, and the bundled dashboard in
`components/imap-dashboard`. Keep the dashboard component and its license and
provenance intact. Do not require a separately installed IMAP plugin or
dashboard sibling.

The repository must never contain a real account, mailbox value, credential,
personal path, provider assumption, or customer-specific brand. If a task starts
with only this repository URL, do not download, install, open setup, or access
mail. Ask in the user's language for explicit confirmation; in Dutch ask:
“Zal ik Nexin Mail installeren en je mail instellen?” Proceed only after a clear
confirmation or an explicit installation request.

An explicit installation request includes private mailbox setup and verification.
Follow `CODEX_INSTALL.md` through the same resumable session; do not stop at
registration or ask for separate permission to connect the mailbox.

Use the complete verified platform package for customer installation. The root
`.mcp.json` is a source-checkout development entry for a local Python 3.12
environment; it does not make local stdio available to ChatGPT cloud. Installed
packages derive absolute host-specific registration outside immutable package
data. One server, `python -m nexin_mail.server`, serves both text tools and the
dashboard.

Never handle passwords in chat, commands, environment variables, logs, or files.
Keep native review, TLS verification, package hashes, manifest identity, and
platform capability gates intact. Never mutate a mailbox as an installation
test, add scheduled mailbox polling, or silently remove unknown registrations.

For source changes, run focused tests from `tests/`, then
`python3 scripts/privacy_scan.py .` and `python3 scripts/validate_structure.py`.
Keep Windows and macOS behavior aligned and preserve unrelated dirty work.
