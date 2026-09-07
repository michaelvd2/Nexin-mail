# Codex guidance for IMAP Plugin

This repository is a standalone, provider-independent Codex plugin. It must never contain a real account, personal path, mailbox value, credential, provider assumption, or customer-specific brand.

When a task starts with only this repository URL, or with the URL plus neutral context, do not download, install, or open setup yet. Ask in the user's language for explicit confirmation; for a Dutch-speaking customer ask exactly: "Zal ik deze IMAP-plugin installeren en je mail instellen?" A link alone is not authorization. If the user clearly asks to install, or confirms that question, read `CODEX_INSTALL.md` and `docs/TROUBLESHOOTING.md` completely before acting. Detect Windows or macOS and follow only that platform's route. The native setup asks the user only for their email address and one masked password or app password; it discovers the technical settings automatically. Never request or handle a secret in chat, commands, environment variables, logs, or files.

For adaptive self-healing, read `docs/SETUP_RECOVERY.md`. It defines evidence-led checks, permitted local repairs, scoped approvals and stopping conditions. Consume structured setup recovery results, preserve healthy configuration and credential-store entries, and rerun affected verification gates. Do not reset retry limits by restarting a task or reinstalling the same unchanged package.

Self-healing must never bypass a hash or manifest mismatch, TLS or certificate validation, an unknown marketplace collision, operating-system security, native review, capability gates, or a failed/ambiguous mail action. Never mutate the mailbox as an installation test.

For development changes, run the tests only from `tests/`, then run `scripts/privacy_scan.py` and `scripts/validate_structure.py`. Keep Windows and macOS behavior aligned and fail closed on unsupported platforms. Do not add scheduled tasks, launch agents, background health checks, or recurring mailbox polls.
