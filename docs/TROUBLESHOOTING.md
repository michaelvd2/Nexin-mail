# Troubleshooting and self-healing

Read [SETUP_RECOVERY.md](SETUP_RECOVERY.md) for the adaptive decision loop and retry limits. Diagnose failures from evidence, make the smallest permitted repair, and rerun the affected verification gates. Preserve successful steps unless their package, settings, or user context changed.

## Safe repairs

### Distinguish permissions from mail authentication

- `permission_denied`: a local permission check failed (including socket access denied). Identify whether Codex sandbox permissions, Windows ACLs, firewall, or organization policy caused it. Do not ask for another password as a repair. Request only the needed permission through the available Codex approval mechanism; if it cannot be granted, stop. Never globally disable the sandbox or create a background helper to circumvent it.
- `local_storage_failed`: connection verification passed but credential/configuration storage did not. Check the executing Windows user and their profile/credential-store access. Do not export credentials or copy them between a sandbox account and the customer account. Repeat setup under the intended user only through a permitted launch route.
- `powershell_blocked` or `setup_launch_failed`: inspect host, execution policy and package integrity independently from sandbox permissions. The Windows launcher prefers an available permitted host and still uses `-File`; it never changes policy or bypasses signature checks. A company policy or unsigned-script restriction needs a permitted installation path, not a retry under weaker security.
- `authentication_failed`: the reached mail server rejected login; this does not prove that every candidate is the correct provider. Confirm official settings and ask for at most one personal retry in the masked form. No unattended password retries.
- `dns_failed`, `network_failed`, `tls_failed`, or `autodiscovery_failed`: inspect the reported domain and nonsecret endpoint diagnostics. Network failure alone does not prove a sandbox problem. Use official provider settings for targeted recovery; never disable TLS checks. Complete IMAP hints limit recovery to that endpoint; supply SMTP hints too when sending is wanted.
- `password_login_disabled`: stop password discovery and check provider authentication requirements. OAuth is not implemented in this password-based setup.

The Windows form closes after a connection attempt and returns JSON automatically: exit 0 configured, 2 cancelled, 20 setup failure; the launcher uses 21 when no permitted PowerShell host is available. Codex must consume the result and continue with read-only acceptance or the matching recovery path, never wait for a chat message saying done. Failure output excludes passwords and full email addresses.

Official reference: [Codex Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox). Approval is scoped to a needed operation, not permission to alter unrelated security settings.

### Package and runtime repair

- Redownload into a new temporary directory when an archive is incomplete or its checksum differs. Never run a mismatched archive.
- Recreate only the plugin's isolated runtime when a pinned dependency is missing or corrupt.
- Repair a generated launcher path when the verified plugin was copied to a different dedicated installation directory.
- Re-register the plugin when the marketplace already points to the same verified distribution.
- Preserve and reuse an existing healthy generic configuration; rerun the masked setup when the user explicitly wants to change it.
- If automatic provider discovery fails, use only the reported domain to read the provider's official documentation and pass complete nonsecret hints to `scripts/configure.py`. Keep the visible form limited to email address and password. Never search with the full address or accept unofficial server settings.
- Start a new Codex task after installation so the plugin cache and tool list are refreshed.
- Remove any legacy scheduled mail-check task or launch agent bearing this plugin's name; the public plugin does not need or create one.

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
