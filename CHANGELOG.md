# Changelog

## 0.1.3 - Installed-backend integrity

- Records a SHA-256 manifest for every installed macOS backend file before the distribution becomes active.
- Lets separately installed local UI plugins verify the Mac backend before launching any code from it.
- Keeps the existing two-field setup and operating-system credential identity unchanged.

## 0.1.2 - Public release hardening

- Rejects attachment downloads when Windows Mark of the Web or macOS quarantine marking cannot be applied, and removes the incomplete file.
- Verifies all Python runtime and test dependencies against reviewed SHA-256 hashes before installation.
- Pins CI actions to immutable revisions and checks the full Git history for personal data and secrets.
- Removes generated launchers that embed a build-machine profile path and blocks releases containing any builder home path.
- Keeps the customer setup at two fields: email address and one masked password or app password.

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
