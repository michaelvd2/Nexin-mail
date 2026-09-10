# Microsoft sign-in

Nexin Mail supports Microsoft 365 and Outlook.com through the maintained
[Microsoft Authentication Library for Python (MSAL)](https://learn.microsoft.com/en-us/entra/msal/python/)
public-client browser flow and Microsoft's [IMAP, POP, and SMTP OAuth
guidance](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth).
The application is a public client: it never
stores or accepts an app secret. MSAL owns the authorization-code exchange,
PKCE, state, loopback callback, token validation, and silent refresh.

The authority is fixed to `https://login.microsoftonline.com/common`. The
interactive callback uses MSAL's `http://localhost` loopback listener on a
system-selected port. Nexin Mail does not implement device-code login, accept
an authorization URL from a caller, or let mailbox data choose an authority or
endpoint.

## Scopes and endpoints

Enrollment requests the delegated IMAP scope, plus the standard identity and
refresh scopes:

```
https://outlook.office.com/IMAP.AccessAsUser.All
offline_access
openid
profile
```

The SMTP scope is requested only when the user explicitly enables sending:

```
https://outlook.office.com/SMTP.Send
```

Microsoft 365 uses `outlook.office365.com:993` with implicit TLS and
`smtp.office365.com:587` with STARTTLS. Outlook.com uses the same IMAP
endpoint and `smtp-mail.outlook.com:587` for SMTP. These are fixed presets;
Microsoft OAuth configuration does not use autodiscovery or arbitrary hosts.
IMAP enrollment can therefore succeed while SMTP remains disabled.

## What is persisted

The serialized MSAL token cache is opaque provider state. It can contain
refresh tokens, access tokens, and identity metadata, depending on MSAL's
cache contents and token lifecycle. Nexin Mail stores that opaque value only
in Windows Credential Manager or the macOS Keychain, using bounded,
integrity-checked generation chunks. It does not promise that access tokens
are RAM-only. No cache, token, password, or app secret is written to a file,
environment variable, configuration value, command line, trace, diagnostic,
or chat response.

Each account's cache uses the exact native target
`imap-plugin/oauth-cache/<account_id>`. A pointer identifies one bounded
generation and its SHA-256 digest. A new generation is read back and verified
before the active pointer changes; the previous pointer remains available
during that switch. Recovery reads only the active or previous generation and
cleanup deletes only exact targets owned by this connector. Native credential
blob limits are a separate platform proof requirement.

Configuration stores only non-secret connection data: the selected account,
validated tenant and account type, public client ID, fixed endpoints, and
whether SMTP was enabled. A missing client ID or MSAL runtime returns the typed
`oauth_unconfigured` state. The code does not invent a client ID. Provider app
registration, delegated-scope consent, publisher verification, and tenant
policy are external gates and are not claimed by source tests.

## Connection and refresh behavior

IMAP and SMTP use XOAUTH2 with the provider-validated account username:

```
user=<address>\x01auth=Bearer <access-token>\x01\x01
```

An authentication failure permits one silent MSAL refresh. A failed refresh
returns `oauth_reauth_required`; there is no retry loop. An action that may
already have reached the mailbox or SMTP server is never repeated after an
authentication refresh or an ambiguous transport result. SMTP authentication
is a separate capability, so an SMTP failure does not discard a healthy IMAP
read connection.

Enrollment validates the account returned by MSAL's account cache, including
the selected username, tenant, authority environment, and consumer versus
work/school classification. Unsigned or caller-supplied token claims are not
used to select an account, tenant, host, or SMTP preset.

The native setup offers a Microsoft browser sign-in choice alongside the
existing masked password/app-password route. Cancelling, refusing consent,
an unavailable browser, an invalid account result, and an unavailable cache
are reported as bounded recovery codes. The native process handles secrets;
the agent-host does not request passwords or tokens in chat.

## Current proof boundary

The synthetic auth tests inject a fake MSAL application and fake native
keystore so they make no live network, browser, account, or credential-store
calls. A live customer connection still requires a real public-client app
registration, user or administrator consent, the actual Windows Credential
Manager or macOS Keychain, provider policy (including SMTP AUTH), and a
manual read/send acceptance. Source tests do not prove those external or
native states.
