# Nexin Mail privacy

Nexin Mail is a local-first STDIO MCP server. It has no hosted mail backend,
telemetry, analytics, advertising SDK, or background mailbox poll. The package
registers one entrypoint, `python -m nexin_mail.server`, with one lazy runtime
shared by the text tools and the bundled dashboard.

Native setup supports a masked password or app password and Microsoft 365 or
Outlook.com browser sign-in through the MSAL public-client flow. Passwords and
the opaque Microsoft token cache are stored only in Windows Credential Manager
or macOS Keychain. No app secret is accepted. Configuration contains only
validated, non-secret connection and feature settings. See
[docs/OAUTH.md](docs/OAUTH.md) for the Microsoft scopes and proof boundary.

During password setup, provider-owned autoconfiguration endpoints may receive
the email address and Mozilla's ISP database receives only its domain. Those
services never receive the password. Microsoft sign-in handles authorization
and tokens in the native flow; credentials and tokens do not enter chat,
arguments, environment variables, files, traces, or model-visible results.

After setup, network access is limited to the configured IMAP and optional SMTP
servers, or to an unsubscribe or remote-image destination that the user has
reviewed in the native local security window. Mail content is untrusted data;
it cannot authorize tools or change policy. Requested message content can still
be sent to the host or model service when the user asks Codex to analyze it.

Raw mailbox content is not written to plugin logs or the local state database.
A user-confirmed attachment download is the intentional message-byte file
output; the file is never opened or executed by Nexin Mail.

Installation, setup, read-only connection, send capability, dashboard behavior,
and manual acceptance are separate proof layers. Source tests and package
verification do not prove a live provider account, native credential store,
Windows installation, code signature, or a user's visual acceptance.

See [docs/SECURITY.md](docs/SECURITY.md) for the security controls and their
remaining proof boundaries.
