# Privacy

IMAP Plugin is local-first. It has no telemetry, analytics, hosted mail service, or vendor account.

During setup, provider-owned standard autoconfiguration endpoints receive the email address, while Mozilla's ISP database receives only the domain. Discovery services never receive the password. Authentication uses the password only in memory and sends it directly to a candidate mail server over certificate-verified TLS.

After setup, the plugin sends data only to the discovered connection or an endpoint the user explicitly reviews:

- the configured IMAP server;
- the optional configured SMTP server;
- an explicitly reviewed public HTTPS unsubscribe endpoint;
- an explicitly reviewed remote-image host.

Passwords stay in Windows Credential Manager or macOS Keychain. Raw mailbox content is processed in memory and is not written to the plugin database or logs. A user-confirmed attachment download is the only intentional persistence of message bytes.

The plugin creates no scheduled task, launch agent, background health check, or recurring mailbox poll.

See [docs/SECURITY.md](docs/SECURITY.md) for the complete security boundary.
