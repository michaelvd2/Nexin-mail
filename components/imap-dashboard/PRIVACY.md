# Privacy

IMAP Dashboard has no hosted service, telemetry, analytics, advertising SDK, or cloud credential service. It does not own mailbox credentials or configuration. It uses the already installed IMAP Plugin, which reads the one existing secret from Windows Credential Manager or macOS Keychain only when connecting locally to the configured server.

The dashboard source and release package contain no real account, host, address, message, password, token, private path, or provider default. Demo content uses reserved example domains.

Message bodies and headers are not written by the dashboard. User-requested assistant summaries or action lists may be stored only through the IMAP Plugin's bounded, operating-system-protected cache. Drafts, arbitrary questions, raw message bodies, and attachment bytes are not cached. A confirmed attachment download is the only intentional content-file output.
