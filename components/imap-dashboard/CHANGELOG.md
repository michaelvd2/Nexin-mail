# Changelog

## 0.1.2 - Secure build tooling

- Updated the pinned Python build tool to a version that fixes the macOS Unicode-normalization archive issue.

## 0.1.1 - Public release hardening

- Removes user-specific attribution and expands current-tree and Git-history privacy checks.
- Verifies the existing IMAP Plugin installation before launching any of its code during Dashboard setup.
- Pins CI inputs and Python test artifacts to reviewed immutable hashes.
- Shows sender, subject and folder for every reviewed mailbox action.
- Rewrites the public README in clear customer language while keeping Dashboard and IMAP Plugin separate.

## 0.1.0 - Beta

- Adds a side-panel mailbox view above an existing IMAP Plugin connection.
- Reuses the same local configuration, operating-system credential entry and protected state.
- Supports bounded mail reads, guarded actions, drafts, sending, unsubscribe, remote images and attachment downloads.
- Provides Windows and macOS installers and a self-verifying Windows handoff package.
