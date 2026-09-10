from __future__ import annotations

import base64
import importlib.util
import json
import imaplib
import smtplib
import subprocess
import sys
from pathlib import Path

import pytest

from imap_plugin.bridge import MailBridge
from imap_plugin.config import AccountConfig
from imap_plugin.credentials import CredentialError, CredentialMetadata, CredentialNotFoundError, ChunkedSecretStore
from imap_plugin.oauth import (
    AUTHORITY,
    CONSUMER_TENANT_ID,
    IMAP_SCOPE,
    SMTP_SCOPE,
    OAuthCancelledError,
    OAuthCacheError,
    OAuthConsentRequiredError,
    OAuthIdentity,
    OAuthIdentityError,
    OAuthProviderError,
    OAuthReauthRequiredError,
    OAuthUnconfiguredError,
    MicrosoftOAuth,
    imap_xoauth2_authenticator,
    microsoft_settings,
    required_scopes,
    smtp_xoauth2_authenticator,
    xoauth2_payload,
)
from imap_plugin.sender import MailSender, build_message, parse_recipients


CLIENT_ID = "123e4567-e89b-12d3-a456-426614174000"
TENANT_ID = "123e4567-e89b-12d3-a456-426614174001"


class MemoryBackend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.fail_target: str | None = None

    def write_secret(self, target: str, secret: str) -> CredentialMetadata:
        if self.fail_target is not None and self.fail_target in target:
            self.fail_target = None
            raise CredentialError("injected write failure")
        self.values[target] = secret
        return CredentialMetadata(target, 1, 2, len(secret), "")

    def read_secret(self, target: str) -> str:
        try:
            return self.values[target]
        except KeyError as exc:
            raise CredentialNotFoundError("credential unavailable") from exc

    def delete_secret(self, target: str) -> None:
        self.deleted.append(target)
        self.values.pop(target, None)


class FailAfterIndexBackend(MemoryBackend):
    def write_secret(self, target: str, secret: str) -> CredentialMetadata:
        result = super().write_secret(target, secret)
        if target.endswith("/index") and secret != "":
            raise CredentialError("injected post-write pointer interruption")
        return result


def test_chunk_store_roundtrip_and_bounded_generation_cleanup() -> None:
    backend = MemoryBackend()
    store = ChunkedSecretStore(backend, "imap-plugin/oauth-cache/test", chunk_chars=128)
    payload = "opaque-cache-" + ("x" * 400)

    store.write(payload)
    assert store.read() == payload
    first_generation = backend.values["imap-plugin/oauth-cache/test/index"]

    store.write("rotated-cache")
    assert store.read() == "rotated-cache"
    assert "imap-plugin/oauth-cache/test/index" in backend.values
    assert first_generation not in backend.values.values()
    assert all(target.startswith("imap-plugin/oauth-cache/test/") for target in backend.deleted)


def test_chunk_store_interrupted_write_preserves_previous_generation() -> None:
    backend = MemoryBackend()
    store = ChunkedSecretStore(backend, "imap-plugin/oauth-cache/test", chunk_chars=128)
    store.write("healthy-cache")
    old_index = backend.values["imap-plugin/oauth-cache/test/index"]
    backend.fail_target = "/g-"

    with pytest.raises(CredentialError):
        store.write("replacement-cache")

    assert backend.values["imap-plugin/oauth-cache/test/index"] == old_index
    assert store.read() == "healthy-cache"


def test_chunk_store_interrupted_pointer_switch_recovers_previous_generation() -> None:
    backend = FailAfterIndexBackend()
    store = ChunkedSecretStore(backend, "imap-plugin/oauth-cache/test", chunk_chars=128)
    # Seed a healthy generation using the ordinary backend before enabling the
    # interruption after the new active pointer is written.
    healthy = MemoryBackend()
    healthy_store = ChunkedSecretStore(healthy, "imap-plugin/oauth-cache/test", chunk_chars=128)
    healthy_store.write("healthy-cache")
    backend.values.update(healthy.values)
    backend.fail_target = None

    with pytest.raises(CredentialError):
        store.write("replacement-cache")
    assert store.read() == "healthy-cache"


def test_chunk_store_corrupt_active_pointer_falls_back_to_previous_generation() -> None:
    backend = MemoryBackend()
    store = ChunkedSecretStore(backend, "imap-plugin/oauth-cache/test", chunk_chars=128)
    store.write("healthy-cache")
    old_index = backend.values["imap-plugin/oauth-cache/test/index"]
    backend.values["imap-plugin/oauth-cache/test/previous"] = old_index
    backend.values["imap-plugin/oauth-cache/test/index"] = "{}"

    assert store.read() == "healthy-cache"


def test_chunk_store_rejects_corrupt_generation_without_fallback() -> None:
    backend = MemoryBackend()
    store = ChunkedSecretStore(backend, "imap-plugin/oauth-cache/test", chunk_chars=128)
    store.write("healthy-cache")
    index = json.loads(backend.values["imap-plugin/oauth-cache/test/index"])
    backend.values[f"imap-plugin/oauth-cache/test/g-{index['generation']}/p-0000"] = "tampered"

    with pytest.raises(CredentialError):
        store.read()


def test_required_scopes_keep_smtp_consent_optional() -> None:
    assert IMAP_SCOPE in required_scopes()
    assert SMTP_SCOPE not in required_scopes()
    assert SMTP_SCOPE in required_scopes(include_smtp=True)


def _account(username: str = "person@example.test", *, tenant: str = TENANT_ID, home: str = "uid." + TENANT_ID) -> dict[str, str]:
    return {
        "username": username,
        "home_account_id": home,
        "environment": "login.microsoftonline.com",
        "realm": tenant,
    }


class FakeCache:
    def __init__(self) -> None:
        self.state = ""
        self.has_state_changed = False

    def deserialize(self, value: str) -> None:
        self.state = value
        self.has_state_changed = False

    def serialize(self) -> str:
        return self.state


class FakeApp:
    def __init__(self, account: dict[str, str]) -> None:
        self.account = account
        self.cache: FakeCache | None = None
        self.interactive_calls: list[dict[str, object]] = []
        self.silent_calls: list[dict[str, object]] = []
        self.interactive_result: dict[str, object] = {}
        self.silent_result: dict[str, object] = {"access_token": "access-token"}

    def acquire_token_interactive(self, **kwargs: object) -> dict[str, object]:
        self.interactive_calls.append(kwargs)
        if self.cache is not None:
            self.cache.state = "opaque-cache"
            self.cache.has_state_changed = True
        return self.interactive_result

    def get_accounts(self) -> list[dict[str, str]]:
        return [self.account]

    def acquire_token_silent(self, scopes: list[str], *, account: dict[str, str], force_refresh: bool) -> dict[str, object]:
        self.silent_calls.append({"scopes": scopes, "account": account, "force_refresh": force_refresh})
        if self.cache is not None:
            self.cache.state = "rotated-cache" if force_refresh else self.cache.state
            self.cache.has_state_changed = True
        return self.silent_result


class FakeMsal:
    PublicClientApplication = object


def _provider(account: dict[str, str] | None = None) -> tuple[MicrosoftOAuth, FakeApp, MemoryBackend]:
    account = account or _account()
    backend = MemoryBackend()
    app = FakeApp(account)
    cache = FakeCache()
    app.cache = cache

    def app_factory(client_id: str, **kwargs: object) -> FakeApp:
        assert client_id == CLIENT_ID
        assert kwargs["authority"] == AUTHORITY
        assert kwargs["token_cache"] is cache
        return app

    provider = MicrosoftOAuth(
        client_id=CLIENT_ID,
        credential_store=backend,
        msal_module=FakeMsal,
        app_factory=app_factory,
        cache_factory=lambda: cache,
    )
    return provider, app, backend


def test_enrollment_uses_msal_browser_pkce_loopback_contract_and_no_smtp_by_default() -> None:
    provider, app, backend = _provider()
    app.interactive_result = {
        "access_token": "access-token",
        "account": _account(),
        # The identity comes from MSAL's validated account cache; an unsigned
        # claims-shaped payload must not redirect endpoint or tenant choice.
        "id_token_claims": {"preferred_username": "attacker@example.test", "tid": CLIENT_ID},
    }

    enrollment = provider.enroll("person@example.test")
    call = app.interactive_calls[0]
    assert call["scopes"] == list(required_scopes())
    assert call["prompt"] == "select_account"
    assert call["login_hint"] == "person@example.test"
    assert call["port"] == 0
    assert call["timeout"] == 300
    assert "client_secret" not in call
    assert enrollment.settings.host == "outlook.office365.com"
    assert enrollment.settings.smtp_host is None
    assert enrollment.public_dict() == {
        "status": "configured",
        "auth_method": "microsoft",
        "account_type": "microsoft365",
        "smtp_enabled": False,
        "mailbox_actions_ready": False,
        "send_ready": False,
    }
    assert "access-token" not in json.dumps(enrollment.public_dict())
    assert backend.values


@pytest.mark.parametrize(
    ("result", "error_type"),
    [
        ({"error": "consent_required"}, OAuthConsentRequiredError),
        ({"error": "access_denied"}, OAuthCancelledError),
        ({"error": "state_mismatch"}, OAuthIdentityError),
    ],
)
def test_enrollment_maps_provider_consent_and_cancel(result: dict[str, str], error_type: type[Exception]) -> None:
    provider, app, _ = _provider()
    app.interactive_result = result
    with pytest.raises(error_type):
        provider.enroll("person@example.test")


def test_enrollment_maps_msal_state_value_error_without_revealing_detail() -> None:
    provider, app, _ = _provider()
    app.acquire_token_interactive = lambda **_kwargs: (_ for _ in ()).throw(
        ValueError("state mismatch contains provider token")
    )
    with pytest.raises(OAuthIdentityError) as failure:
        provider.enroll("person@example.test")
    assert "provider token" not in str(failure.value)


def test_enrollment_rejects_account_identity_mismatch_and_unconfigured_client() -> None:
    provider, app, _ = _provider(_account("other@example.test"))
    app.interactive_result = {"access_token": "access-token", "account": _account("other@example.test")}
    with pytest.raises(OAuthIdentityError):
        provider.enroll("person@example.test")

    with pytest.raises(OAuthUnconfiguredError) as failure:
        MicrosoftOAuth(credential_store=MemoryBackend(), msal_module=FakeMsal, cache_factory=FakeCache).enroll(
            "person@example.test"
        )
    assert failure.value.code == "oauth_unconfigured"


def test_enrollment_rejects_result_account_tenant_mismatch() -> None:
    provider, app, _ = _provider()
    mismatched_result_account = _account()
    mismatched_result_account["realm"] = CLIENT_ID
    app.interactive_result = {
        "access_token": "access-token",
        "account": mismatched_result_account,
    }
    with pytest.raises(OAuthIdentityError):
        provider.enroll("person@example.test")


def test_access_token_requires_complete_public_oauth_configuration() -> None:
    settings = AccountConfig(
        username="person@example.test",
        auth_method="microsoft",
        oauth_client_id=CLIENT_ID,
    )
    provider = MicrosoftOAuth(settings, credential_store=MemoryBackend(), msal_module=FakeMsal)
    with pytest.raises(OAuthUnconfiguredError):
        provider.get_access_token("imap")


def test_silent_refresh_rotates_cache_once_and_reauth_does_not_loop() -> None:
    provider, app, backend = _provider()
    app.interactive_result = {"access_token": "access-token", "account": _account()}
    enrollment = provider.enroll("person@example.test", include_smtp=True)
    token = provider.get_access_token("imap")
    assert token == "access-token"
    assert app.silent_calls[-1]["force_refresh"] is False
    assert provider.get_access_token("smtp") == "access-token"
    assert app.silent_calls[-1]["scopes"] == list(required_scopes(include_smtp=True))
    assert enrollment.settings.smtp_host == "smtp.office365.com"
    assert json.loads(backend.values[f"{enrollment.settings.oauth_store_target}/index"])["sha256"]

    app.silent_result = {"error": "invalid_grant"}
    with pytest.raises(OAuthReauthRequiredError):
        provider.get_access_token("imap", force_refresh=True)
    assert app.silent_calls[-1]["force_refresh"] is True

    app.silent_result = None
    with pytest.raises(OAuthReauthRequiredError):
        provider.get_access_token("imap")


def test_missing_cached_account_requires_local_reauthentication() -> None:
    provider, app, _ = _provider()
    app.interactive_result = {"access_token": "access-token", "account": _account()}
    provider.enroll("person@example.test")
    app.get_accounts = lambda: []  # fake cache has no validated account after revocation
    with pytest.raises(OAuthReauthRequiredError):
        provider.get_access_token("imap")


def test_consumer_account_uses_outlook_smtp_preset() -> None:
    identity = OAuthIdentity("person@example.test", CONSUMER_TENANT_ID, "outlook.com")
    settings = microsoft_settings(identity, client_id=CLIENT_ID, include_smtp=True)
    assert settings.smtp_host == "smtp-mail.outlook.com"
    assert settings.smtp_port == 587


def test_account_config_rejects_cross_tenant_smtp_preset() -> None:
    with pytest.raises(ValueError):
        AccountConfig(
            username="person@example.test",
            auth_method="microsoft",
            host="outlook.office365.com",
            smtp_host="smtp.office365.com",
            smtp_port=587,
            smtp_security="starttls",
            oauth_client_id=CLIENT_ID,
            oauth_tenant_id=CONSUMER_TENANT_ID,
            oauth_account_type="outlook.com",
        )


def test_unconfigured_microsoft_config_keeps_optional_public_id_absent(tmp_path: Path) -> None:
    from imap_plugin.enrollment import write_config
    from imap_plugin.config import load_settings

    settings = AccountConfig(username="person@example.test", auth_method="microsoft")
    destination = tmp_path / "config.toml"
    write_config(settings, destination)
    loaded = load_settings(destination)
    assert loaded.microsoft_oauth
    assert loaded.oauth_client_id is None
    assert loaded.oauth_tenant_id is None


def test_oauth_config_writer_preserves_account_scoped_cache_target(tmp_path: Path) -> None:
    from imap_plugin.enrollment import write_config
    from imap_plugin.config import load_settings

    settings = AccountConfig(
        username="person@example.test",
        account_id="work-1",
        auth_method="microsoft",
    )
    destination = tmp_path / "config.toml"
    write_config(settings, destination)
    loaded = load_settings(destination)
    assert loaded.account_id == "work-1"
    assert loaded.oauth_store_target == "imap-plugin/oauth-cache/work-1"


def test_native_oauth_adapter_reports_unconfigured_without_network_or_secret_input() -> None:
    root = Path(__file__).parents[1]
    env = {"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "oauth_enroll.py")],
        input=json.dumps({"email_address": "person@example.test", "include_smtp": False}),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 20
    result = json.loads(completed.stdout)
    assert result["error_code"] == "oauth_unconfigured"
    assert "person@example.test" not in completed.stdout
    assert completed.stderr == ""

    rejected = subprocess.run(
        [sys.executable, str(root / "scripts" / "oauth_enroll.py")],
        input=json.dumps({
            "email_address": "person@example.test",
            "include_smtp": False,
            "password": "do-not-accept",
        }),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert rejected.returncode == 1
    assert "do-not-accept" not in rejected.stdout
    assert rejected.stderr == ""


def test_configure_launcher_whitelists_native_result_before_emitting_it() -> None:
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("configure_launcher", root / "scripts" / "configure.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    safe = module._safe_configured_result({
        "status": "configured",
        "auth_method": "microsoft",
        "account_type": "microsoft365",
        "smtp_enabled": False,
        "mailbox_actions_ready": False,
        "send_ready": False,
        "email_address": "person@example.test",
        "access_token": "never-emit-this-token",
        "smtp_diagnostics": [{
            "host": "smtp.example.test",
            "port": 587,
            "security": "starttls",
            "error_code": "authentication_failed",
            "access_token": "never-emit-this-token",
        }],
    })

    encoded = json.dumps(safe)
    assert "never-emit-this-token" not in encoded
    assert "person@example.test" not in encoded
    assert safe["smtp_diagnostics"] == [{
        "host": "smtp.example.test",
        "port": 587,
        "security": "starttls",
        "error_code": "authentication_failed",
    }]


def test_xoauth2_payload_and_error_continuation_never_echo_token() -> None:
    token = "access-token"
    assert xoauth2_payload("person@example.test", token) == b"user=person@example.test\x01auth=Bearer access-token\x01\x01"
    imap_auth = imap_xoauth2_authenticator("person@example.test", token)
    assert imap_auth(b"") == xoauth2_payload("person@example.test", token)
    challenge = base64.b64encode(b'{"status":"401","schemes":"Bearer"}')
    assert imap_auth(challenge) == b""
    direct_error = imap_xoauth2_authenticator("person@example.test", token)
    assert direct_error(b'{"status":"401","schemes":"Bearer"}') == b""
    smtp_auth = smtp_xoauth2_authenticator("person@example.test", token)
    assert smtp_auth(None) == "user=person@example.test\x01auth=Bearer access-token\x01\x01"
    assert smtp_auth(challenge) == ""
    assert "access-token" not in str(OAuthProviderError("access-token"))


def test_bridge_oauth_refreshes_authentication_once_before_session() -> None:
    identity = OAuthIdentity("person@example.test", TENANT_ID, "microsoft365", "uid." + TENANT_ID)
    settings = microsoft_settings(identity, client_id=CLIENT_ID)
    calls: list[tuple[str, bool]] = []

    class Client:
        capabilities = (b"IMAP4rev1",)

        def __init__(self) -> None:
            self.auth_calls = 0

        def authenticate(self, mechanism: str, callback: object) -> tuple[str, list[bytes]]:
            assert mechanism == "XOAUTH2"
            self.auth_calls += 1
            if self.auth_calls == 1:
                raise imaplib.IMAP4.error("token rejected")
            assert callback(b"").startswith(b"user=person@example.test")
            return "OK", [b""]

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", []

    client = Client()

    def token_provider(service: str, *, force_refresh: bool) -> str:
        calls.append((service, force_refresh))
        return "access-token"

    bridge = MailBridge(
        settings,
        client_factory=lambda *args, **kwargs: client,
        secret_reader=lambda _target: (_ for _ in ()).throw(AssertionError("password path used")),
        oauth_token_provider=token_provider,
    )
    with bridge.session() as current:
        assert current is client
    assert calls == [("imap", False), ("imap", True)]


def test_bridge_oauth_refreshes_when_server_returns_non_ok_auth_status() -> None:
    identity = OAuthIdentity("person@example.test", TENANT_ID, "microsoft365", "uid." + TENANT_ID)
    settings = microsoft_settings(identity, client_id=CLIENT_ID)
    calls: list[bool] = []

    class Client:
        capabilities = (b"IMAP4rev1",)

        def __init__(self) -> None:
            self.auth_calls = 0

        def authenticate(self, _mechanism: str, _callback: object) -> tuple[str, list[bytes]]:
            self.auth_calls += 1
            return ("NO", []) if self.auth_calls == 1 else ("OK", [])

        def logout(self) -> tuple[str, list[bytes]]:
            return "BYE", []

    client = Client()
    bridge = MailBridge(
        settings,
        client_factory=lambda *args, **kwargs: client,
        oauth_token_provider=lambda _service, *, force_refresh: calls.append(force_refresh) or "access-token",
    )
    with bridge.session():
        pass
    assert calls == [False, True]


def test_sender_oauth_refreshes_before_send_and_submits_once() -> None:
    identity = OAuthIdentity("person@example.test", TENANT_ID, "microsoft365", "uid." + TENANT_ID)
    settings = microsoft_settings(identity, client_id=CLIENT_ID, include_smtp=True)
    auth_calls: list[bool] = []
    sent = 0

    class Client:
        def auth(self, mechanism: str, callback: object) -> tuple[int, bytes]:
            assert mechanism == "XOAUTH2"
            auth_calls.append(len(auth_calls) > 0)
            if len(auth_calls) == 1:
                raise smtplib.SMTPAuthenticationError(535, b"rejected")
            assert callback(None).startswith("user=person@example.test")
            return 235, b"ok"

        def send_message(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            nonlocal sent
            sent += 1
            return {}

        def quit(self) -> tuple[int, bytes]:
            return 221, b"bye"

    client = Client()
    provider_calls: list[tuple[str, bool]] = []

    def token_provider(service: str, *, force_refresh: bool) -> str:
        provider_calls.append((service, force_refresh))
        return "access-token"

    message = build_message(
        from_address="person@example.test",
        to=parse_recipients("recipient@example.test"),
        cc=(), subject="subject", body="body", message_id="<id@example.test>",
    )
    sender = MailSender(
        settings,
        transport_factory=lambda _settings, _context: client,
        oauth_token_provider=token_provider,
    )
    result = sender.send_once(message)
    assert result.message_id == "<id@example.test>"
    assert sent == 1
    assert provider_calls == [("smtp", False), ("smtp", True)]


def test_oauth_rejects_untrusted_account_id_and_controlled_token() -> None:
    with pytest.raises(ValueError):
        MicrosoftOAuth(account_id="../other", client_id=CLIENT_ID)
    with pytest.raises(CredentialError):
        ChunkedSecretStore(MemoryBackend(), "imap-plugin/other-secret")
    with pytest.raises(OAuthProviderError):
        xoauth2_payload("person@example.test", "access\x01token")


def test_oauth_cache_backend_exceptions_are_redacted() -> None:
    class BrokenCache(FakeCache):
        def deserialize(self, value: str) -> None:
            raise RuntimeError("provider token leaked")

    backend = MemoryBackend()
    provider = MicrosoftOAuth(
        client_id=CLIENT_ID,
        credential_store=backend,
        msal_module=FakeMsal,
        app_factory=lambda *_args, **_kwargs: None,
        cache_factory=BrokenCache,
    )
    provider._store().write("cache-blob")
    with pytest.raises(OAuthCacheError) as failure:
        provider._cache_object()
    assert "provider token leaked" not in str(failure.value)


def test_get_accounts_oauth_failure_is_mapped_without_unbound_local() -> None:
    provider, app, _ = _provider()
    app.get_accounts = lambda: (_ for _ in ()).throw(OAuthProviderError("cache token"))
    provider.settings = microsoft_settings(
        OAuthIdentity("person@example.test", TENANT_ID, "microsoft365", "uid." + TENANT_ID),
        client_id=CLIENT_ID,
    )
    with pytest.raises(OAuthProviderError):
        provider.get_access_token("imap")
