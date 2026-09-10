"""Microsoft public-client OAuth for the local IMAP/SMTP connector.

The provider surface is deliberately small.  Microsoft Authentication Library
(MSAL) owns the authorization-code, PKCE, state, loopback, token validation and
refresh protocol.  This module supplies only strict Microsoft configuration,
native-keystore cache persistence, validated account selection and XOAUTH2
protocol adapters.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .config import (
    AccountConfig,
    GUID_RE,
    MICROSOFT_AUTH_METHOD,
    MICROSOFT_IMAP_HOST,
    MICROSOFT_SMTP_HOST,
    MICROSOFT_CONSUMER_TENANT_ID,
    OUTLOOK_SMTP_HOST,
)
from .credentials import (
    ChunkedSecretStore,
    CredentialError,
    CredentialNotFoundError,
    SecretBackend,
    platform_store,
)

try:  # Keep password-only installations importable before runtime deps arrive.
    import msal  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only by a dependency failure.
    msal = None  # type: ignore[assignment]


AUTHORITY = "https://login.microsoftonline.com/common"
AUTHORITY_HOST = "login.microsoftonline.com"
REDIRECT_HOST = "localhost"
IMAP_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All"
SMTP_SCOPE = "https://outlook.office.com/SMTP.Send"
OFFLINE_ACCESS_SCOPE = "offline_access"
OPENID_SCOPE = "openid"
PROFILE_SCOPE = "profile"
CONSUMER_TENANT_ID = MICROSOFT_CONSUMER_TENANT_ID
SUPPORTED_SERVICES = frozenset({"imap", "smtp"})
MAX_EMAIL_LENGTH = 320
MAX_BROWSER_TIMEOUT = 600
ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class OAuthError(RuntimeError):
    """Safe, typed OAuth failure without provider response text."""

    code = "oauth_failed"
    public_message = "Microsoft authentication did not complete."

    def __init__(self, message: str | None = None) -> None:
        # Provider/server text is attacker-controlled and may contain tokens,
        # addresses, or authorization details. Keep exception text fixed even
        # when an internal caller accidentally supplies a message.
        del message
        super().__init__(self.public_message)


class OAuthUnconfiguredError(OAuthError):
    code = "oauth_unconfigured"
    public_message = "Microsoft sign-in is not configured for this installation."


class OAuthConsentRequiredError(OAuthError):
    code = "oauth_consent_required"
    public_message = "Microsoft consent is required before this mailbox can connect."


class OAuthReauthRequiredError(OAuthError):
    code = "oauth_reauth_required"
    public_message = "Microsoft sign-in has expired or was revoked; sign in again locally."


class OAuthBrowserUnavailableError(OAuthError):
    code = "oauth_browser_unavailable"
    public_message = "A supported local browser sign-in could not be opened."


class OAuthCancelledError(OAuthError):
    code = "oauth_cancelled"
    public_message = "Microsoft sign-in was cancelled."


class OAuthIdentityError(OAuthError):
    code = "oauth_identity_invalid"
    public_message = "Microsoft returned an account that could not be validated."


class OAuthCacheError(OAuthError):
    code = "oauth_cache_corrupt"
    public_message = "The protected Microsoft sign-in cache failed integrity validation."


class OAuthProviderError(OAuthError):
    code = "oauth_provider_failed"
    public_message = "Microsoft sign-in returned an unusable response."


class OAuthSmtpDisabledError(OAuthError):
    code = "smtp_auth_disabled"
    public_message = "SMTP sign-in was not enabled for this Microsoft connection."


@dataclass(frozen=True)
class OAuthIdentity:
    """Identity selected from an MSAL-validated account cache entry."""

    username: str
    tenant_id: str
    account_type: str
    home_account_id: str = ""


@dataclass(frozen=True)
class OAuthEnrollment:
    identity: OAuthIdentity
    settings: AccountConfig
    smtp_enabled: bool

    def public_dict(self) -> dict[str, Any]:
        """Return setup state without an address, token or provider response."""
        return {
            "status": "configured",
            "auth_method": MICROSOFT_AUTH_METHOD,
            "account_type": self.identity.account_type,
            "smtp_enabled": self.smtp_enabled,
            "mailbox_actions_ready": False,
            "send_ready": False,
        }


def required_scopes(*, include_smtp: bool = False) -> tuple[str, ...]:
    """Return the least delegated Microsoft scopes for the requested services."""
    if type(include_smtp) is not bool:
        raise ValueError("include_smtp must be a boolean")
    scopes = [IMAP_SCOPE]
    if include_smtp:
        scopes.append(SMTP_SCOPE)
    scopes.extend((OFFLINE_ACCESS_SCOPE, OPENID_SCOPE, PROFILE_SCOPE))
    return tuple(scopes)


def oauth_scopes(*, include_smtp: bool = False) -> tuple[str, ...]:
    """Compatibility name for callers that describe scopes as OAuth settings."""
    return required_scopes(include_smtp=include_smtp)


def _email(value: str) -> str:
    if not isinstance(value, str):
        raise OAuthIdentityError()
    value = value.strip()
    if (
        not value
        or len(value) > MAX_EMAIL_LENGTH
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        or value.count("@") != 1
    ):
        raise OAuthIdentityError()
    local, domain = value.rsplit("@", 1)
    if not local or not domain or any(char.isspace() for char in value):
        raise OAuthIdentityError()
    try:
        domain.encode("idna")
    except UnicodeError as exc:
        raise OAuthIdentityError() from exc
    return value


def _guid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if GUID_RE.fullmatch(value) else None


def _safe_text(value: Any, *, limit: int = 32_768) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise OAuthProviderError()
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise OAuthProviderError() from exc
    return value


def _error_from_result(result: Mapping[str, Any]) -> OAuthError:
    raw_error = result.get("error", "")
    error = raw_error[:256].casefold() if isinstance(raw_error, str) else ""
    if "state" in error:
        return OAuthIdentityError()
    if "65001" in error or "consent" in error or "interaction_required" in error:
        return OAuthConsentRequiredError()
    if "cancel" in error or "denied" in error or error in {"user_cancelled", "access_denied"}:
        return OAuthCancelledError()
    if error in {"invalid_grant", "login_required", "no_account", "account_unavailable"}:
        return OAuthReauthRequiredError()
    if error in {"no_tokens_found", "no_cached_token", "token_missing"}:
        return OAuthReauthRequiredError()
    if "timeout" in error or "network" in error or "tempor" in error:
        return OAuthBrowserUnavailableError()
    return OAuthProviderError()


def _error_from_exception(exc: BaseException, *, browser: bool = False) -> OAuthError:
    """Map only bounded MSAL error codes; never relay exception text."""
    for name in ("error_code", "error", "code"):
        value = getattr(exc, name, None)
        if (
            isinstance(value, str)
            and len(value) <= 256
            and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        ):
            return _error_from_result({"error": value})
    if isinstance(exc, ValueError):
        # MSAL raises ValueError for invalid/CSRF state in its interactive
        # response validation. Do not expose the exception text.
        return OAuthIdentityError()
    if isinstance(exc, (OSError, TimeoutError)) or browser:
        return OAuthBrowserUnavailableError()
    return OAuthProviderError()


def _require_success(result: Any) -> Mapping[str, Any]:
    if not isinstance(result, Mapping):
        raise OAuthProviderError()
    if result.get("error"):
        raise _error_from_result(result)
    token = result.get("access_token")
    if (
        not isinstance(token, str)
        or not token
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in token)
    ):
        raise OAuthProviderError()
    return result


def _account_tenant(account: Mapping[str, Any]) -> tuple[str, str]:
    realm_value = account.get("realm")
    tenant_value = account.get("tenant_id")
    if realm_value and tenant_value:
        realm_tenant = _account_tenant({"realm": realm_value})
        field_tenant = _account_tenant({"realm": tenant_value})
        if realm_tenant != field_tenant:
            raise OAuthIdentityError()
        return realm_tenant
    realm = realm_value or tenant_value
    if not realm:
        home_account_id = account.get("home_account_id")
        if isinstance(home_account_id, str) and "." in home_account_id:
            realm = home_account_id.rsplit(".", 1)[-1]
    if isinstance(realm, str) and realm.casefold() in {"consumer", "consumers"}:
        return CONSUMER_TENANT_ID, "outlook.com"
    tenant = _guid(realm)
    if tenant is None:
        raise OAuthIdentityError()
    if tenant == CONSUMER_TENANT_ID:
        return tenant, "outlook.com"
    return tenant, "microsoft365"


def _validated_identity(
    accounts: Any,
    *,
    requested_username: str,
    result: Mapping[str, Any] | None = None,
    tenant_hint: str | None = None,
) -> OAuthIdentity:
    if not isinstance(accounts, (list, tuple)):
        raise OAuthIdentityError()
    requested = _email(requested_username)
    candidates: list[Mapping[str, Any]] = []
    result_account = result.get("account") if isinstance(result, Mapping) else None
    result_home = result_account.get("home_account_id") if isinstance(result_account, Mapping) else None
    if result_account is not None and not isinstance(result_account, Mapping):
        raise OAuthIdentityError()
    if result_home is not None and (
        not isinstance(result_home, str)
        or len(result_home) > 512
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in result_home)
    ):
        raise OAuthIdentityError()
    if isinstance(result_account, Mapping):
        result_username = result_account.get("username")
        if result_username is not None and (
            not isinstance(result_username, str)
            or result_username.casefold() != requested.casefold()
        ):
            raise OAuthIdentityError()
    for item in accounts:
        if not isinstance(item, Mapping):
            continue
        username = item.get("username")
        if not isinstance(username, str) or username.casefold() != requested.casefold():
            continue
        if result_home is not None and item.get("home_account_id") != result_home:
            continue
        candidates.append(item)
    if len(candidates) != 1:
        raise OAuthIdentityError()
    account = candidates[0]
    username = _email(account.get("username"))
    tenant_id, account_type = _account_tenant(account)
    if isinstance(result_account, Mapping):
        result_environment = result_account.get("environment")
        if result_environment is not None and (
            not isinstance(result_environment, str)
            or result_environment.casefold() != AUTHORITY_HOST
        ):
            raise OAuthIdentityError()
        result_realm = result_account.get("realm") or result_account.get("tenant_id")
        if result_realm is not None:
            result_tenant, _ = _account_tenant(result_account)
            if result_tenant != tenant_id:
                raise OAuthIdentityError()
    if tenant_hint is not None and tenant_id != tenant_hint:
        raise OAuthIdentityError()
    environment = account.get("environment")
    if not isinstance(environment, str) or environment.casefold() != AUTHORITY_HOST:
        raise OAuthIdentityError()
    home_account_id = account.get("home_account_id", "")
    if (
        not isinstance(home_account_id, str)
        or len(home_account_id) > 512
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in home_account_id)
    ):
        raise OAuthIdentityError()
    return OAuthIdentity(username, tenant_id, account_type, home_account_id)


def microsoft_settings(
    identity: OAuthIdentity,
    *,
    client_id: str,
    include_smtp: bool = False,
    account_id: str = "default",
) -> AccountConfig:
    """Build strict Microsoft endpoints from a validated MSAL account."""
    if type(include_smtp) is not bool:
        raise ValueError("include_smtp must be a boolean")
    smtp_host = None
    if include_smtp:
        smtp_host = OUTLOOK_SMTP_HOST if identity.account_type == "outlook.com" else MICROSOFT_SMTP_HOST
    return AccountConfig(
        username=identity.username,
        account_id=account_id,
        host=MICROSOFT_IMAP_HOST,
        port=993,
        imap_security="implicit_tls",
        smtp_host=smtp_host,
        smtp_port=587 if smtp_host else None,
        smtp_security="starttls",
        smtp_username=identity.username if smtp_host else None,
        email_address=identity.username,
        auth_method=MICROSOFT_AUTH_METHOD,
        oauth_client_id=client_id,
        oauth_tenant_id=identity.tenant_id,
        oauth_cache_target=f"imap-plugin/oauth-cache/{account_id}",
        oauth_account_type=identity.account_type,
    )


def _sasl_error_challenge(challenge: Any) -> bool:
    if challenge in (None, b"", ""):
        return False
    if isinstance(challenge, str):
        raw = challenge.encode("ascii", "ignore")
    elif isinstance(challenge, bytes):
        raw = challenge
    else:
        return True
    candidates = [raw]
    try:
        candidates.append(base64.b64decode(raw, validate=True))
    except (binascii.Error, ValueError):
        pass
    for candidate in candidates:
        try:
            value = json.loads(candidate.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, Mapping) and any(key in value for key in ("status", "schemes", "scope", "error")):
            return True
    return False


def xoauth2_payload(username: str, access_token: str) -> bytes:
    """Return the RFC 7628 XOAUTH2 bytes; callers never log this value."""
    user = _email(username)
    token = _safe_text(access_token)
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode("utf-8")


class _SaslConversation:
    def __init__(self, username: str, access_token: str, *, as_bytes: bool) -> None:
        self._payload = xoauth2_payload(username, access_token)
        self._as_bytes = as_bytes
        self._sent = False

    def __call__(self, challenge: Any = None) -> bytes | str:
        if self._sent:
            # Microsoft may return a base64 JSON failure continuation. An
            # empty response acknowledges/cancels it without echoing details.
            return b"" if self._as_bytes else ""
        self._sent = True
        if _sasl_error_challenge(challenge):
            return b"" if self._as_bytes else ""
        if self._as_bytes:
            return self._payload
        return self._payload.decode("utf-8")


def imap_xoauth2_authenticator(username: str, access_token: str) -> Callable[[bytes], bytes]:
    return _SaslConversation(username, access_token, as_bytes=True)


def smtp_xoauth2_authenticator(username: str, access_token: str) -> Callable[[bytes | None], str]:
    return _SaslConversation(username, access_token, as_bytes=False)


# Friendly aliases used by protocol adapters and tests.
make_imap_xoauth2_authenticator = imap_xoauth2_authenticator
make_smtp_xoauth2_authenticator = smtp_xoauth2_authenticator
oauth_sasl_payload = xoauth2_payload


class MicrosoftOAuth:
    """MSAL public client with native-keystore-only token cache state."""

    def __init__(
        self,
        settings: AccountConfig | None = None,
        *,
        client_id: str | None = None,
        account_id: str = "default",
        credential_store: SecretBackend | ChunkedSecretStore | None = None,
        cache_store: SecretBackend | ChunkedSecretStore | None = None,
        msal_module: Any | None = None,
        app_factory: Callable[..., Any] | None = None,
        cache_factory: Callable[[], Any] | None = None,
        browser_timeout: int = 300,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        if settings is not None:
            account_id = settings.account_id
        if not isinstance(account_id, str) or ACCOUNT_ID_RE.fullmatch(account_id) is None:
            raise ValueError("account_id is outside the safe bound")
        if type(browser_timeout) is not int or not 1 <= browser_timeout <= MAX_BROWSER_TIMEOUT:
            raise ValueError("browser timeout is outside the safe bound")
        self.settings = settings
        self.client_id = client_id or (settings.oauth_client_id if settings is not None else None)
        self.account_id = account_id
        self._backend = credential_store if credential_store is not None else cache_store
        self._msal = msal_module if msal_module is not None else msal
        self._app_factory = app_factory
        self._cache_factory = cache_factory
        self.browser_timeout = browser_timeout
        self.progress = progress
        self._lock = threading.RLock()
        self._cache: Any | None = None
        self._app: Any | None = None
        self._chunk_store: ChunkedSecretStore | None = None

    def _validated_client_id(self) -> str:
        value = self.client_id
        if _guid(value) is None:
            raise OAuthUnconfiguredError()
        return str(value).strip().lower()

    def _require_dependency(self) -> Any:
        if self._app_factory is None and (
            self._msal is None or not hasattr(self._msal, "PublicClientApplication")
        ):
            raise OAuthUnconfiguredError()
        if self._cache_factory is None and (
            self._msal is None or not hasattr(self._msal, "SerializableTokenCache")
        ):
            raise OAuthUnconfiguredError()
        return self._msal

    def _store(self) -> ChunkedSecretStore:
        if self._chunk_store is not None:
            return self._chunk_store
        target = self.settings.oauth_store_target if self.settings is not None else f"imap-plugin/oauth-cache/{self.account_id}"
        if isinstance(self._backend, ChunkedSecretStore):
            if self._backend.target != target:
                raise OAuthCacheError()
            self._chunk_store = self._backend
            return self._chunk_store
        backend = self._backend or platform_store()
        try:
            self._chunk_store = ChunkedSecretStore(backend, target)
        except CredentialError as exc:
            raise OAuthCacheError() from exc
        return self._chunk_store

    def _cache_object(self) -> Any:
        if self._cache is not None:
            return self._cache
        module = self._require_dependency()
        try:
            cache = self._cache_factory() if self._cache_factory is not None else module.SerializableTokenCache()
            serialized = self._store().read_optional()
            if serialized:
                cache.deserialize(serialized)
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthCacheError() from exc
        self._cache = cache
        return cache

    def _app_object(self) -> Any:
        if self._app is not None:
            return self._app
        module = self._require_dependency()
        cache = self._cache_object()
        client_id = self._validated_client_id()
        try:
            if self._app_factory is not None:
                app = self._app_factory(client_id, authority=AUTHORITY, token_cache=cache)
            else:
                app = module.PublicClientApplication(
                    client_id,
                    authority=AUTHORITY,
                    token_cache=cache,
                    enable_pii_log=False,
                )
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthProviderError() from exc
        self._app = app
        return app

    def _persist(self) -> None:
        cache = self._cache
        if cache is None or not bool(getattr(cache, "has_state_changed", True)):
            return
        try:
            serialized = cache.serialize()
            if not isinstance(serialized, str):
                raise OAuthCacheError()
            self._store().write(serialized)
            # MSAL exposes this mutable marker; clearing it after a verified
            # native write avoids rotating the same cache on every read.
            try:
                cache.has_state_changed = False
            except Exception:
                pass
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthCacheError() from exc

    def cache_metadata(self) -> Any | None:
        """Return native-cache metadata without exposing cache contents."""
        try:
            return self._store().metadata()
        except CredentialNotFoundError:
            return None
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthCacheError() from exc

    def _notify(self, event: str) -> None:
        if not callable(self.progress):
            return
        try:
            self.progress(event)
        except Exception:
            # Progress is a UI hint and must never alter auth semantics.
            return

    def enroll(self, email_address: str, *, include_smtp: bool = False) -> OAuthEnrollment:
        """Open Microsoft's official interactive browser flow and persist cache."""
        requested = _email(email_address)
        with self._lock:
            self._validated_client_id()
            app = self._app_object()
            self._notify("browser_sign_in_starting")

            def before_ui(**kwargs: Any) -> None:
                if kwargs.get("ui") == "browser":
                    self._notify("browser_opened")

            try:
                result = app.acquire_token_interactive(
                    scopes=list(required_scopes(include_smtp=include_smtp)),
                    prompt="select_account",
                    login_hint=requested,
                    timeout=self.browser_timeout,
                    port=0,
                    on_before_launching_ui=before_ui,
                )
            except KeyboardInterrupt as exc:
                raise OAuthCancelledError() from exc
            except OAuthError:
                raise
            except (OSError, RuntimeError, TimeoutError) as exc:
                raise _error_from_exception(exc, browser=True) from exc
            except Exception as exc:
                raise _error_from_exception(exc, browser=True) from exc
            try:
                result_map = _require_success(result)
            except OAuthError:
                raise
            except Exception as exc:
                raise OAuthProviderError() from exc
            try:
                identity = _validated_identity(
                    app.get_accounts(),
                    requested_username=requested,
                    result=result_map,
                )
            except OAuthError:
                raise
            except Exception as exc:
                raise OAuthIdentityError() from exc
            client_id = self._validated_client_id()
            settings = microsoft_settings(
                identity,
                client_id=client_id,
                include_smtp=include_smtp,
                account_id=self.account_id,
            )
            self.settings = settings
            self.client_id = client_id
            self._persist()
            self._notify("browser_sign_in_complete")
            return OAuthEnrollment(identity, settings, include_smtp)

    def get_access_token(self, service: str, *, force_refresh: bool = False) -> str:
        """Get one cached/refresh token; never launches UI or retries an action."""
        if not isinstance(service, str) or service not in SUPPORTED_SERVICES:
            raise OAuthProviderError()
        with self._lock:
            settings = self.settings
            if settings is None or not settings.microsoft_oauth or not settings.oauth_configured:
                raise OAuthUnconfiguredError()
            self._validated_client_id()
            if service == "smtp" and not settings.send_configured:
                raise OAuthSmtpDisabledError()
            app = self._app_object()
            accounts: Any = None
            try:
                accounts = app.get_accounts()
                identity = _validated_identity(
                    accounts,
                    requested_username=settings.username,
                    tenant_hint=settings.oauth_tenant_id,
                )
                configured_type = getattr(settings, "oauth_account_type", None)
                if configured_type is not None and configured_type != identity.account_type:
                    raise OAuthIdentityError()
                if service == "smtp":
                    expected_host = (
                        OUTLOOK_SMTP_HOST if identity.account_type == "outlook.com" else MICROSOFT_SMTP_HOST
                    )
                    if settings.smtp_host != expected_host:
                        raise OAuthIdentityError()
                account = next(
                    item for item in accounts
                    if isinstance(item, Mapping)
                    and isinstance(item.get("username"), str)
                    and item["username"].casefold() == identity.username.casefold()
                    and (
                        (identity.home_account_id and item.get("home_account_id") == identity.home_account_id)
                        or not identity.home_account_id
                    )
                )
            except OAuthError:
                if isinstance(accounts, (list, tuple)) and not accounts:
                    raise OAuthReauthRequiredError()
                raise
            except Exception as exc:
                raise OAuthReauthRequiredError() from exc
            scopes = list(required_scopes(include_smtp=service == "smtp"))
            try:
                result = app.acquire_token_silent(scopes, account=account, force_refresh=bool(force_refresh))
            except Exception as exc:
                raise OAuthReauthRequiredError() from exc
            try:
                if result is None or (
                    isinstance(result, Mapping)
                    and not result.get("error")
                    and not result.get("access_token")
                ):
                    raise OAuthReauthRequiredError()
                result_map = _require_success(result)
                token = _safe_text(result_map.get("access_token"))
                self._persist()  # includes rotated refresh state when MSAL changed it
                return token
            except OAuthError:
                self._persist()
                raise
            except Exception as exc:
                self._persist()
                raise OAuthProviderError() from exc

    # Provider callback spelling used by bridge/sender integrations.
    access_token = get_access_token


MicrosoftOAuthClient = MicrosoftOAuth
OAuthClient = MicrosoftOAuth


def oauth_provider_for(settings: AccountConfig, **kwargs: Any) -> MicrosoftOAuth:
    return MicrosoftOAuth(settings, **kwargs)


def enroll_microsoft(
    email_address: str,
    *,
    client_id: str | None = None,
    include_smtp: bool = False,
    account_id: str = "default",
    **kwargs: Any,
) -> OAuthEnrollment:
    return MicrosoftOAuth(client_id=client_id, account_id=account_id, **kwargs).enroll(
        email_address,
        include_smtp=include_smtp,
    )


__all__ = [
    "AUTHORITY",
    "AUTHORITY_HOST",
    "CONSUMER_TENANT_ID",
    "IMAP_SCOPE",
    "OFFLINE_ACCESS_SCOPE",
    "OPENID_SCOPE",
    "PROFILE_SCOPE",
    "REDIRECT_HOST",
    "SMTP_SCOPE",
    "OAuthBrowserUnavailableError",
    "OAuthCacheError",
    "OAuthCancelledError",
    "OAuthClient",
    "OAuthConsentRequiredError",
    "OAuthEnrollment",
    "OAuthError",
    "OAuthIdentity",
    "OAuthIdentityError",
    "OAuthProviderError",
    "OAuthReauthRequiredError",
    "OAuthSmtpDisabledError",
    "OAuthUnconfiguredError",
    "MicrosoftOAuth",
    "MicrosoftOAuthClient",
    "enroll_microsoft",
    "imap_xoauth2_authenticator",
    "make_imap_xoauth2_authenticator",
    "make_smtp_xoauth2_authenticator",
    "microsoft_settings",
    "oauth_provider_for",
    "oauth_scopes",
    "oauth_sasl_payload",
    "required_scopes",
    "smtp_xoauth2_authenticator",
    "xoauth2_payload",
]
