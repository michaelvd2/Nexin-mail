# Changelog

## 0.1.1 - Simple automatic setup

- Replaced technical Windows and macOS setup fields with just email address and one masked password or app password.
- Added standard provider autoconfiguration, domain-only Mozilla ISP database lookup, secure hostname discovery, and a Codex fallback based only on official provider documentation.
- Verifies IMAP and optional SMTP without sending or changing mail, and enables only capabilities the server proves safe.
- Removed the unused scheduled mailbox-check path; the plugin performs no background polling.
- Kept secrets out of chat, command arguments, environment variables, files, logs, discovery services, and release packages.

## 0.1.0 - Beta

- Provider-independent IMAP and optional SMTP configuration.
- Implicit TLS and mandatory STARTTLS support for both transports.
- Bounded reads, advisory classification, exact reviewed mailbox actions, guarded unsubscribe, drafts, sending, and attachment download.
- Self-verifying Windows handoff with a pinned Python runtime and rollback script.
- macOS Keychain, native local setup/review, quarantine marking, source installer, and Windows/macOS CI.
- No built-in provider, domain, account, mailbox, credentials, or personal paths.
