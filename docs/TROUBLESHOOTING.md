# Troubleshooting and self-healing

Codex should diagnose installation failures from their exact output and make the smallest local repair. After a repair, restart the platform installation route from its first verification step.

## Safe repairs

- Redownload into a new temporary directory when an archive is incomplete or its checksum differs. Never run a mismatched archive.
- Recreate only the plugin's isolated runtime when a pinned dependency is missing or corrupt.
- Repair a generated launcher path when the verified plugin was copied to a different dedicated installation directory.
- Re-register the plugin when the marketplace already points to the same verified distribution.
- Preserve and reuse an existing healthy generic configuration; rerun the masked setup when the user explicitly wants to change it.
- Start a new Codex task after installation so the plugin cache and tool list are refreshed.

## Stop conditions

- An archive hash or package manifest still differs after a clean redownload.
- A marketplace with the reserved name points to an unknown location or product.
- The configured server cannot prove TLS with hostname verification.
- Authentication fails after the user has personally retried the masked setup.
- Required IMAP capabilities or SPECIAL-USE folders are absent. Report the unavailable feature; do not emulate it unsafely.
- SMTP returns an ambiguous delivery result. Never retry automatically.
- A native review or operating-system security control cannot open or complete.

## Evidence to report separately

Report source validation, dependency installation, plugin registration, read-only IMAP connectivity, reviewed mailbox-action readiness, SMTP readiness, and clean-machine acceptance as separate results. One passing layer never proves another.
