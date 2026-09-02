# Security and privacy model

## Trust boundaries

The plugin runs locally as a STDIO MCP server. It has no hosted mail backend, HTTP listener, telemetry, analytics, remote UI assets, cloud credential store, scheduled task, launch agent, or background mailbox poll. IMAP and optional SMTP connect only to validated DNS hostnames with the operating-system trust store and hostname verification. Supported transport modes are implicit TLS and mandatory STARTTLS; plaintext fallback is unavailable.

Every subject, body, address, header, URL, attachment name, and instruction from mail is untrusted data. Mail content cannot authorize an action or change the security policy.

## Credentials and configuration

The native setup form asks only for an email address and one masked password or app password. Provider-owned standard autoconfiguration endpoints receive the email address, while Mozilla's ISP database receives only its domain. Those discovery endpoints never receive the password. The password is used in memory only to authenticate directly to candidate IMAP and SMTP servers over verified TLS, then stored in Windows Credential Manager or macOS Keychain after IMAP succeeds. It is never accepted through chat, command arguments, environment variables, logs, or configuration files. The TOML configuration contains only nonsecret connection settings and bounded feature choices.

## Action authorization

The server enforces confirmation. A proposal binds the exact action, stable message reference, UIDVALIDITY, current flags, payload, UI session, and immutable digest. Approval handles are cryptographically random, memory-only, short-lived, and one-use. Any mismatch, expiry, replay, process restart, or server-state change invalidates approval.

Sending requires a verified saved Drafts object and an explicit recipient-and-body review. The server creates the Message-ID, makes one SMTP submission attempt, and never automatically retries an ambiguous result.

## Deletion and restore

Production code exposes no permanent delete or expunge operation. Trash and Junk actions require server-advertised MOVE and UIDPLUS plus verified SPECIAL-USE folders. If those capabilities are absent, the action is unavailable. Successful moves can record native-keystore-protected restore metadata when the server returns a stable destination reference.

## Attachments and remote content

Attachment bytes are fetched only for one unchanged reviewed IMAP part up to 25 MiB. Files receive a sanitized collision-safe name, are written only under `Downloads/IMAP Plugin`, and receive a Windows Mark of the Web or macOS quarantine marker. Windows Defender is invoked when available; macOS leaves scanning and blocking to the operating system. The plugin never opens, previews, extracts, imports, or executes the file and never describes a completed scan as proof of safety.

Unsubscribe endpoints are limited to validated public HTTPS destinations. RFC 8058 requests execute once without retry. Browser-only unsubscribe requires a separate visible review and stops on credentials, personal-data entry, payment, CAPTCHA, download, cross-site redirect, or ambiguity.

## Local state

Raw bodies, subjects, sender addresses, recipients, previews, URLs, and attachment bytes are never written to the plugin database or logs. The confirmed attachment destination is the sole intentional file-content exception. The SQLite state contains hashes, bounded advisory labels, configuration digests, transition metadata, and send idempotency metadata. Sensitive persistent structures use current-user Windows DPAPI or AES-GCM with a key stored in the current user's macOS Keychain.

## Release gates

The beta build is not a production trust claim. A production release requires code signing or notarization, package hashes, an SBOM, dependency and malware scans, clean-machine installation evidence on each claimed platform, rollback evidence, and no unresolved high-severity findings.
