# Changelog

## 0.1.0 - Beta

- Provider-independent IMAP and optional SMTP configuration.
- Implicit TLS and mandatory STARTTLS support for both transports.
- Bounded reads, advisory classification, exact reviewed mailbox actions, guarded unsubscribe, drafts, sending, and attachment download.
- Self-verifying Windows handoff with a pinned Python runtime and rollback script.
- macOS Keychain, native local setup/review, quarantine marking, source installer, and Windows/macOS CI.
- No built-in provider, domain, account, mailbox, credentials, or personal paths.
