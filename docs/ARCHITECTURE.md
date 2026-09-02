# Architecture

IMAP Plugin is a local STDIO MCP server. It has no hosted backend and does not expose a network listener.

- `config.py` validates provider-independent account settings and fail-closed runtime profiles.
- `autoconfig.py` discovers standard provider settings and verifies candidate IMAP and SMTP connections without persisting a password or sending mail.
- `credentials.py` reads secrets from Windows Credential Manager or macOS Keychain without exposing them to Codex.
- `bridge.py` owns TLS-protected IMAP sessions, bounded reads, stable message references, capability checks, safe folder operations, and attachment retrieval.
- `sender.py` owns optional TLS-protected SMTP authentication and one-attempt submission.
- `operator.py` composes read operations, advisory classification, proposals, and exact reviewed actions.
- `approval.py` binds short-lived one-use approvals to immutable action payloads and message state.
- `state.py` stores only bounded metadata and uses current-user native keystore protection for sensitive settings that require persistence.
- `server.py` exposes the bounded MCP tool surface.

Setup is interactive only. The plugin has no scheduler, launch agent, service, watcher, or background polling loop.

Consequential actions follow the same sequence:

1. Read current server state.
2. Build an exact proposal.
3. Show a native local review.
4. Bind one short-lived approval to the proposal and stable message state.
5. Revalidate state immediately before execution.
6. Execute once and record only bounded metadata.

Mail content can never authorize a tool call or relax these gates.
