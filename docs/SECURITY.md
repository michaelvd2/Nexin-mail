# Nexin Mail security model

## Trust boundaries

Nexin Mail runs as one local STDIO MCP server: `python -m nexin_mail.server`.
The text tools and dashboard adapter share one lazy MailBridge, MailOperator,
state store, and native-review boundary. An unconfigured account still exposes
setup status and a bounded onboarding dashboard; importing or listing tools
does not open a mailbox.

Mail subjects, bodies, addresses, headers, URLs, attachment names, and
instructions are untrusted data. Mail cannot authorize a tool call or change a
security policy. The native review component is a plugin boundary; it does not
claim immunity from a compromised host desktop, automation, or malware.

## Credentials and configuration

The native setup offers a masked password or app-password route and a Microsoft
public-client browser OAuth route. Passwords never enter chat, command-line
arguments, environment variables, files, traces, or model-visible output.
Microsoft access and refresh state is opaque provider data kept in the operating
system keystore with bounded integrity-checked generations; Nexin Mail does not
claim that provider tokens are RAM-only. No application secret is used. Fixed
Microsoft IMAP and SMTP endpoints, delegated scopes, account identity, and
tenant values are validated before use. See [OAUTH.md](OAUTH.md).

## Action authorization

Every consequential dashboard and text action creates a proposal bound to its
exact action, stable message reference, UIDVALIDITY, current state, payload,
UI session, and digest. A native local security window reviews that exact
in-process snapshot. The model receives only a non-secret proposal ID; a UI
session or metadata field is correlation information, not human approval. The
one-use approval handle stays in process, expires, and is invalidated by a
replay, process restart, stale mailbox state, profile mismatch, or any payload
change. Settings and browser-progress records use the same proposal binding.
Read profiles cannot invoke reviewed writes.

Sending requires a verified saved Drafts object and an explicit recipient and
message review. Nexin Mail makes one SMTP attempt and never retries an
ambiguous result. Unsubscribe requests likewise execute once without retry.

## Deletion and external content

Permanent delete and expunge are not exposed. Trash and Junk actions require
verified SPECIAL-USE folders and server-advertised MOVE and UIDPLUS support.
Successful moves can record protected restore metadata when a stable destination
reference is returned.

Remote images remain blocked until the exact message and destinations are
reviewed. SVG, redirects, oversized content, and suspicious messages stay
blocked. Attachment bytes are downloaded only for one unchanged reviewed part,
to a bounded sanitized path, and are never opened, previewed, extracted, or
executed. Browser unsubscribe stops on credentials, personal-data entry,
payment, CAPTCHA, download, cross-site redirect, or ambiguity.

## Local state and release evidence

Raw bodies, subjects, sender addresses, recipients, previews, URLs, and
attachment bytes are excluded from logs and the state database except for a
confirmed attachment file. Persistent sensitive structures use the current
user's Windows DPAPI or macOS Keychain.

Source tests establish protocol and invariant behavior. A release still needs
code signing or notarization, package hashes, dependency and malware scans,
clean-machine installation evidence on each claimed platform, rollback evidence,
provider consent and policy checks, and manual read/send/dashboard acceptance.
Those are separate gates, and this model does not make a zero-risk claim.
