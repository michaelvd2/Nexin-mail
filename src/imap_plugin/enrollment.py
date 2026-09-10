"""Native setup adapters for Microsoft enrollment.

This module is used by both platform setup front ends.  It accepts only the
user-entered address and a local SMTP capability choice; MSAL and the native
credential backend keep all token/cache material inside the local process.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from .config import AccountConfig, config_path, load_settings
from .oauth import MicrosoftOAuth, OAuthEnrollment


def _toml_string(value: str) -> str:
    if any(char in value for char in "\r\n\x00"):
        raise ValueError("configuration values must be single-line")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_config(settings: AccountConfig, destination: Path | None = None) -> None:
    """Atomically write only non-secret account and endpoint configuration."""
    values = [
        f"account_id = {_toml_string(settings.account_id)}",
        f"username = {_toml_string(settings.username)}",
        f"email_address = {_toml_string(settings.email_address or settings.username)}",
        f"host = {_toml_string(settings.host)}",
        f"port = {settings.port}",
        f"imap_security = {_toml_string(settings.imap_security)}",
        f"credential_target = {_toml_string(settings.credential_target)}",
        f"smtp_credential_target = {_toml_string(settings.smtp_credential_target)}",
        "trusted_authserv_ids = ["
        + ", ".join(_toml_string(value) for value in settings.trusted_authserv_ids)
        + "]",
        f"operator_enabled = {'true' if settings.operator_enabled else 'false'}",
        "timeout_seconds = 15.0",
        "max_results = 20",
        "max_scan = 250",
        "max_days = 31",
        "max_message_bytes = 262144",
        "trace_max_bytes = 262144",
        "trace_files = 3",
    ]
    if settings.microsoft_oauth:
        values.append('auth_method = "microsoft"')
        if settings.oauth_client_id is not None:
            values.append(f"oauth_client_id = {_toml_string(settings.oauth_client_id)}")
        if settings.oauth_tenant_id is not None:
            values.append(f"oauth_tenant_id = {_toml_string(settings.oauth_tenant_id)}")
        values.append(f"oauth_cache_target = {_toml_string(settings.oauth_store_target)}")
        if settings.oauth_account_type is not None:
            values.append(f"oauth_account_type = {_toml_string(settings.oauth_account_type)}")
    if settings.send_configured:
        values.extend(
            [
                f"smtp_host = {_toml_string(settings.smtp_host or '')}",
                f"smtp_port = {settings.smtp_port}",
                f"smtp_security = {_toml_string(settings.smtp_security)}",
                f"smtp_username = {_toml_string(settings.smtp_login)}",
            ]
        )
    target = destination or config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(values) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configured_oauth_client_id() -> str | None:
    """Read only an existing validated public client ID from local config."""
    try:
        settings = load_settings()
    except Exception:
        return None
    return settings.oauth_client_id


def enroll_microsoft_native(
    email_address: str,
    *,
    include_smtp: bool = False,
    progress: Callable[[str], None] | None = None,
) -> OAuthEnrollment:
    """Enroll through MSAL and atomically persist the resulting safe config."""
    enrollment = MicrosoftOAuth(
        client_id=configured_oauth_client_id(),
        account_id="default",
        progress=progress,
    ).enroll(email_address, include_smtp=include_smtp)
    write_config(enrollment.settings)
    return enrollment


__all__ = ["configured_oauth_client_id", "enroll_microsoft_native", "write_config"]
