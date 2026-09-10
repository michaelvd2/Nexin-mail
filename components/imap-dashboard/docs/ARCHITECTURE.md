# Architecture

`imap-dashboard` is a UI adapter, not an IMAP implementation.

```text
Codex
  ├─ IMAP Plugin tools ───────────────┐
  └─ IMAP Dashboard side panel        │
           └─ imap_dashboard.server ──┤
                                      ▼
                        installed imap_plugin package
                          ├─ one configuration
                          ├─ one native credential identity
                          ├─ one protected state database
                          └─ IMAP / optional SMTP over TLS
```

The dashboard launcher resolves only a verified sibling plugin under the installed IMAP Plugin distribution. Its Python path includes the dashboard UI adapter and the sibling backend source. The Python interpreter is the backend's pinned runtime. There is no bundled backend fallback because a fallback could drift into a second configuration or credential identity.

The dashboard server exposes the visual tool contract and delegates mailbox reads and actions to `imap_plugin.bridge.MailBridge` and `imap_plugin.operator.MailOperator`. Review proposals and one-use approval handles live in the dashboard MCP process. Persistent settings, classifications, assistant results, and action receipts use the backend's protected state implementation.
