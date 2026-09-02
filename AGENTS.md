# Codex guidance for IMAP Plugin

This repository is a standalone, provider-independent Codex plugin. It must never contain a real account, personal path, mailbox value, credential, provider assumption, or customer-specific brand.

When the user asks to install this repository, read `CODEX_INSTALL.md` and `docs/TROUBLESHOOTING.md` completely before acting. Detect Windows or macOS and follow only that platform's route. The user enters all secrets personally in the masked native setup form; never request or handle them in chat, commands, environment variables, logs, or files.

Self-healing is allowed for the local install mechanics: missing pinned dependencies, stale plugin registration, an incomplete copied distribution, platform-launcher paths, permissions inside the dedicated plugin directory, and rerunning read-only verification. Diagnose from exact output, preserve existing configuration and native credential-store entries, apply the smallest repair, then rerun verification from the beginning.

Self-healing must never bypass a hash or manifest mismatch, TLS or certificate validation, an unknown marketplace collision, operating-system security, native review, capability gates, or a failed/ambiguous mail action. Never mutate the mailbox as an installation test.

For development changes, run the tests only from `tests/`, then run `scripts/privacy_scan.py` and `scripts/validate_structure.py`. Keep Windows and macOS behavior aligned and fail closed on unsupported platforms.
