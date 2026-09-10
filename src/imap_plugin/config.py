from __future__ import annotations

import os
import ipaddress
import platform
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOST = ""
DEFAULT_PORT = 993
DEFAULT_TARGET = "imap-plugin/imap"
DEFAULT_SMTP_TARGET = "imap-plugin/smtp"
MICROSOFT_AUTH_METHOD = "microsoft"
PASSWORD_AUTH_METHOD = "password"
MICROSOFT_IMAP_HOST = "outlook.office365.com"
MICROSOFT_SMTP_HOST = "smtp.office365.com"
OUTLOOK_SMTP_HOST = "smtp-mail.outlook.com"
MICROSOFT_CONSUMER_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"


HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
GUID_RE = re.compile(
    # Microsoft tenant/client IDs are canonical UUID strings.  The UUID
    # version and variant bits are not part of the provider's contract, so
    # validate the shape without rejecting a provider-issued all-zero/test ID.
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _validated_hostname(value: str, field: str) -> str:
    value = value.strip().rstrip(".")
    if not value or len(value) > 253 or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError(f"{field} must be a valid DNS hostname")
    try:
        ascii_value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"{field} must be a valid DNS hostname") from exc
    try:
        ipaddress.ip_address(ascii_value)
    except ValueError:
        pass
    else:
        raise ValueError(f"{field} must be a DNS hostname, not an IP literal")
    if not all(HOST_LABEL_RE.fullmatch(label) for label in ascii_value.split(".")):
        raise ValueError(f"{field} must be a valid DNS hostname")
    return ascii_value.lower()


def state_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("LOCALAPPDATA is unavailable; refusing roaming or plaintext state")
        return Path(base) / "imap-plugin"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "IMAP Plugin"
    raise RuntimeError("IMAP Plugin currently supports Windows and macOS only")


def config_path() -> Path:
    override = os.environ.get("IMAP_PLUGIN_CONFIG")
    return Path(override) if override else state_root() / "config.toml"


@dataclass(frozen=True)
class AccountConfig:
    username: str
    account_id: str = "default"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    imap_security: str = "implicit_tls"
    credential_target: str = DEFAULT_TARGET
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str = "implicit_tls"
    smtp_credential_target: str = DEFAULT_SMTP_TARGET
    smtp_username: str | None = None
    email_address: str | None = None
    trusted_authserv_ids: tuple[str, ...] = ()
    operator_enabled: bool = False
    timeout_seconds: float = 15.0
    max_results: int = 20
    max_scan: int = 250
    max_days: int = 31
    max_message_bytes: int = 262_144
    trace_max_bytes: int = 262_144
    trace_files: int = 3
    auth_method: str = PASSWORD_AUTH_METHOD
    oauth_client_id: str | None = None
    oauth_tenant_id: str | None = None
    oauth_cache_target: str | None = None
    oauth_account_type: str | None = None

    def __post_init__(self) -> None:
        username = self.username.strip()
        if not username or any(char in username for char in "\r\n\x00"):
            raise ValueError("username must be a non-empty single-line value")
        object.__setattr__(self, "username", username)
        if not self.account_id or len(self.account_id) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", self.account_id):
            raise ValueError("account_id must use 1..64 letters, digits, dot, underscore, or hyphen")
        if not isinstance(self.auth_method, str) or self.auth_method not in {PASSWORD_AUTH_METHOD, MICROSOFT_AUTH_METHOD}:
            raise ValueError("auth_method must be password or microsoft")
        # An unconfigured Microsoft account still gets a safe endpoint preset
        # so callers can reach the typed ``oauth_unconfigured`` state without
        # inventing a host or placing a placeholder in config.
        if self.auth_method == MICROSOFT_AUTH_METHOD and not self.host:
            if self.port != DEFAULT_PORT or self.imap_security != "implicit_tls":
                raise ValueError("Microsoft IMAP must use the fixed verified endpoint")
            object.__setattr__(self, "host", MICROSOFT_IMAP_HOST)
            object.__setattr__(self, "port", 993)
            object.__setattr__(self, "imap_security", "implicit_tls")
        object.__setattr__(self, "host", _validated_hostname(self.host, "host"))
        if not 1 <= self.port <= 65535:
            raise ValueError("IMAP port must be 1..65535")
        if self.imap_security not in {"implicit_tls", "starttls"}:
            raise ValueError("imap_security must be implicit_tls or starttls")
        if not self.credential_target or not self.smtp_credential_target:
            raise ValueError("separate IMAP and SMTP credential targets are required")
        if any(
            len(value) > 256 or any(char in value for char in "\r\n\x00")
            for value in (self.credential_target, self.smtp_credential_target)
        ):
            raise ValueError("credential targets must be bounded single-line values")
        if self.credential_target == self.smtp_credential_target:
            raise ValueError("IMAP and SMTP credentials must use separate targets")
        if self.smtp_security not in {"implicit_tls", "starttls"}:
            raise ValueError("smtp_security must be implicit_tls or starttls")
        if (self.smtp_host is None) != (self.smtp_port is None):
            raise ValueError("smtp_host and smtp_port must be configured together")
        if self.smtp_host is not None:
            object.__setattr__(self, "smtp_host", _validated_hostname(self.smtp_host, "smtp_host"))
            if not 1 <= int(self.smtp_port) <= 65535:
                raise ValueError("SMTP port must be 1..65535")
        if self.smtp_username is not None:
            smtp_username = self.smtp_username.strip()
            if not smtp_username or any(char in smtp_username for char in "\r\n\x00"):
                raise ValueError("smtp_username must be a non-empty single-line value")
            object.__setattr__(self, "smtp_username", smtp_username)
        if self.email_address is not None:
            address = self.email_address.strip()
            if "@" not in address or any(char in address for char in "\r\n\x00"):
                raise ValueError("email_address must be a single valid-looking address")
            object.__setattr__(self, "email_address", address)
        for field in ("oauth_client_id", "oauth_tenant_id"):
            value = getattr(self, field)
            if value is not None:
                if not isinstance(value, str) or GUID_RE.fullmatch(value.strip()) is None:
                    raise ValueError(f"{field} must be a canonical UUID")
                object.__setattr__(self, field, value.strip().lower())
        if self.oauth_account_type is not None:
            if not isinstance(self.oauth_account_type, str) or self.oauth_account_type not in {"microsoft365", "outlook.com"}:
                raise ValueError("oauth_account_type must be microsoft365 or outlook.com")
        if self.oauth_cache_target is not None:
            target = self.oauth_cache_target
            expected = f"imap-plugin/oauth-cache/{self.account_id}"
            if target != expected:
                raise ValueError("oauth_cache_target must be the account-scoped native target")
        if self.auth_method == MICROSOFT_AUTH_METHOD:
            if self.host != MICROSOFT_IMAP_HOST or self.port != 993 or self.imap_security != "implicit_tls":
                raise ValueError("Microsoft IMAP must use the fixed verified endpoint")
            if self.smtp_host is not None and self.smtp_host not in {MICROSOFT_SMTP_HOST, OUTLOOK_SMTP_HOST}:
                raise ValueError("Microsoft SMTP must use a fixed verified endpoint")
            if self.smtp_host is not None and (self.smtp_port != 587 or self.smtp_security != "starttls"):
                raise ValueError("Microsoft SMTP must use verified STARTTLS")
            if self.oauth_tenant_id == MICROSOFT_CONSUMER_TENANT_ID:
                if self.oauth_account_type not in {None, "outlook.com"}:
                    raise ValueError("consumer Microsoft accounts must use the Outlook.com account type")
                if self.smtp_host is not None and self.smtp_host != OUTLOOK_SMTP_HOST:
                    raise ValueError("consumer Microsoft accounts must use the Outlook.com SMTP endpoint")
            elif self.oauth_tenant_id is not None:
                if self.oauth_account_type not in {None, "microsoft365"}:
                    raise ValueError("organization Microsoft accounts must use the Microsoft 365 account type")
                if self.smtp_host is not None and self.smtp_host != MICROSOFT_SMTP_HOST:
                    raise ValueError("organization Microsoft accounts must use the Microsoft 365 SMTP endpoint")
        if not isinstance(self.operator_enabled, bool):
            raise ValueError("operator_enabled must be true or false")
        if not isinstance(self.trusted_authserv_ids, (list, tuple)) or len(self.trusted_authserv_ids) > 10:
            raise ValueError("trusted_authserv_ids must contain at most ten DNS hostnames")
        trusted = tuple(
            dict.fromkeys(
                _validated_hostname(str(value), "trusted_authserv_ids")
                for value in self.trusted_authserv_ids
            )
        )
        object.__setattr__(self, "trusted_authserv_ids", trusted)
        if not (1 <= self.max_results <= 50):
            raise ValueError("max_results must be 1..50")
        if not (1 <= self.max_days <= 31):
            raise ValueError("max_days must be 1..31")
        if not (16_384 <= self.max_message_bytes <= 1_048_576):
            raise ValueError("max_message_bytes outside safe bounds")

    @property
    def from_address(self) -> str:
        return self.email_address or self.username

    @property
    def send_configured(self) -> bool:
        return self.smtp_host is not None and self.smtp_port is not None

    @property
    def smtp_login(self) -> str:
        return self.smtp_username or self.username

    @property
    def microsoft_oauth(self) -> bool:
        return self.auth_method == MICROSOFT_AUTH_METHOD

    @property
    def oauth_configured(self) -> bool:
        return self.microsoft_oauth and self.oauth_client_id is not None and self.oauth_tenant_id is not None

    @property
    def oauth_store_target(self) -> str:
        return self.oauth_cache_target or f"imap-plugin/oauth-cache/{self.account_id}"


# Concise import name used by the installer and tests.
Settings = AccountConfig


def load_settings(path: Path | None = None) -> AccountConfig:
    source = path or config_path()
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"configuration is missing: {source}") from exc
    allowed = {field for field in AccountConfig.__dataclass_fields__}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
    forbidden = {key for key in data if any(word in key.lower() for word in ("password", "secret", "token", "api_key"))}
    if forbidden:
        raise ValueError(f"forbidden configuration keys: {sorted(forbidden)}")
    return AccountConfig(**data)


def safe_profile(value: str | None = None) -> str:
    raw = os.environ.get("IMAP_PLUGIN_PROFILE") if value is None else value
    normalized = (raw or "read").strip().lower()
    if normalized in {"write", "operator"}:
        return normalized
    return "read"


def resolve_profile(settings: AccountConfig, value: str | None = None) -> str:
    """Resolve a process profile with read as the fail-closed default.

    A missing process override may use the explicit local onboarding choice.
    Any present but invalid override always resolves to read.
    """
    raw = os.environ.get("IMAP_PLUGIN_PROFILE") if value is None else value
    if raw is None:
        return "operator" if settings.operator_enabled else "read"
    return safe_profile(raw)
