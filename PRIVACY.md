# Privacy

IMAP Plugin is local-first. It has no telemetry, analytics, hosted mail service, or vendor account.

The plugin sends data only to endpoints the user configures or explicitly reviews:

- the configured IMAP server;
- the optional configured SMTP server;
- an explicitly reviewed public HTTPS unsubscribe endpoint;
- an explicitly reviewed remote-image host.

Passwords stay in Windows Credential Manager or macOS Keychain. Raw mailbox content is processed in memory and is not written to the plugin database or logs. A user-confirmed attachment download is the only intentional persistence of message bytes.

See [docs/SECURITY.md](docs/SECURITY.md) for the complete security boundary.
