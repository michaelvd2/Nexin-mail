# Troubleshooting

Self-healing is limited to ordinary local installation problems.

1. Confirm the operating system is Windows 10/11 x64 or macOS 13+.
2. Confirm the installed IMAP Plugin distribution exists in its documented application directory.
3. Run the backend's own verifier and read-only doctor. If the backend is missing, install it from the sibling [IMAP Plugin repository](../../imap-plugin) by following that repository's `CODEX_INSTALL.md`.
4. Rerun this dashboard package's verifier and installer.
5. Confirm the installed marketplace still contains both `imap-plugin` and `imap-dashboard`, then start a new Codex task.

Never repair the dashboard by copying a password, editing credential targets, creating a second config, weakening TLS, skipping a manifest mismatch, bypassing Gatekeeper or antivirus, or changing review gates. Stop and report an exact failure if the backend identity is unknown, its verification fails, or secure credential access is unavailable.
