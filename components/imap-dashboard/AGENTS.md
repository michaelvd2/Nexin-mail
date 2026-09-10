# Codex repository instructions

This repository contains `imap-dashboard`, an optional second Codex plugin. It must remain a thin UI layer over the separately installed `imap-plugin` backend.

- Never add IMAP or SMTP credentials, mailbox addresses, provider defaults, real messages, private hosts, personal paths, or account-specific branding.
- Never create a dashboard-specific credential target or configuration file. The only supported runtime is the sibling `imap-plugin` installation.
- Keep the dashboard side-panel-only. Opening it is read-only and must not trigger mailbox actions or AI work.
- Preserve bounded reads, native-keystore protection, exact UI review, one-use approvals, reversible deletion only, and no automatic send retry.
- Installation may add or update only the `imap-dashboard` entry and directory inside the known IMAP Plugin distribution. It must preserve the backend and unrelated marketplace entries.
- A missing, corrupt, or unverified backend is a hard stop. Follow `CODEX_INSTALL.md`; never improvise a second backend.
