from __future__ import annotations

import urllib.parse

import pytest

from imap_plugin.autoconfig import (
    AutoConfigurationError,
    ServerCandidate,
    autoconfigure,
    discover_candidates,
    parse_thunderbird_config,
)


STANDARD_XML = b"""<?xml version="1.0"?>
<clientConfig version="1.1">
  <emailProvider id="example.test">
    <incomingServer type="imap">
      <hostname>imap.example.test</hostname>
      <port>993</port>
      <socketType>SSL</socketType>
      <username>%EMAILADDRESS%</username>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.example.test</hostname>
      <port>587</port>
      <socketType>STARTTLS</socketType>
      <username>%EMAILLOCALPART%</username>
    </outgoingServer>
  </emailProvider>
</clientConfig>
"""


def test_standard_autoconfig_is_parsed_without_secrets():
    imap, smtp = parse_thunderbird_config(
        STANDARD_XML,
        "person@example.test",
        "provider-autoconfig",
    )
    assert imap == [
        ServerCandidate(
            "imap",
            "imap.example.test",
            993,
            "implicit_tls",
            "person@example.test",
            "provider-autoconfig",
        )
    ]
    assert smtp == [
        ServerCandidate(
            "smtp",
            "smtp.example.test",
            587,
            "starttls",
            "person",
            "provider-autoconfig",
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [
        b"<!DOCTYPE x [<!ENTITY secret SYSTEM 'file:///etc/passwd'>]><x>&secret;</x>",
        b"<clientConfig><incomingServer type='imap'><hostname>imap.example.test</hostname><port>143</port><socketType>plain</socketType><username>%EMAILADDRESS%</username></incomingServer></clientConfig>",
    ],
)
def test_autoconfig_never_accepts_entities_or_plaintext(payload):
    if b"DOCTYPE" in payload:
        with pytest.raises(ValueError, match="forbidden"):
            parse_thunderbird_config(payload, "person@example.test", "test")
    else:
        imap, smtp = parse_thunderbird_config(
            payload,
            "person@example.test",
            "test",
        )
        assert imap == []
        assert smtp == []


def test_discovery_shares_email_only_with_provider_and_domain_with_ispdb():
    urls: list[str] = []

    def fetcher(url: str) -> bytes:
        urls.append(url)
        return STANDARD_XML

    discover_candidates("person+tag@example.test", fetcher=fetcher)
    assert len(urls) == 3
    provider_urls = urls[:2]
    ispdb_url = urls[2]
    assert all(
        urllib.parse.quote("person+tag@example.test", safe="") in value
        for value in provider_urls
    )
    assert "person" not in ispdb_url
    assert ispdb_url.endswith("/example.test")


def test_autoconfigure_enables_only_proven_features_and_never_returns_password():
    credential = "unique-unit-secret"
    attempted: list[tuple[str, str]] = []

    def imap_probe(candidate, supplied_password, email):
        attempted.append((candidate.host, supplied_password))
        assert supplied_password == credential
        assert email == "person@example.test"
        return {
            "tls": {"verified": True},
            "operator_features": {
                "safe_move": True,
                "drafts": True,
                "bin": True,
                "sent": True,
                "send_configured": False,
            },
        }

    def smtp_probe(imap, smtp, supplied_password, email):
        assert imap.protocol == "imap"
        assert smtp.protocol == "smtp"
        assert supplied_password == credential
        assert email == "person@example.test"
        return {"authenticated": True, "tls_verified": True}

    result = autoconfigure(
        "person@example.test",
        credential,
        fetcher=lambda _url: STANDARD_XML,
        imap_probe=imap_probe,
        smtp_probe=smtp_probe,
    )
    assert attempted == [("imap.example.test", credential)]
    assert result.settings.operator_enabled is True
    assert result.settings.send_configured is True
    assert result.mailbox_actions_ready is True
    assert result.send_ready is True
    assert credential not in str(result.public_dict())


def test_smtp_failure_does_not_block_verified_imap_reading():
    result = autoconfigure(
        "person@example.test",
        "unit-secret",
        fetcher=lambda _url: STANDARD_XML,
        imap_probe=lambda *_: {
            "tls": {"verified": True},
            "operator_features": {
                "safe_move": False,
                "drafts": True,
                "bin": True,
                "sent": True,
            },
        },
        smtp_probe=lambda *_: {"authenticated": False, "tls_verified": True},
    )
    assert result.settings.send_configured is False
    assert result.settings.operator_enabled is False
    assert result.mailbox_actions_ready is False
    assert result.send_ready is False


def test_failure_reports_only_domain_and_not_password():
    credential = "never-print-this"
    with pytest.raises(AutoConfigurationError) as failure:
        autoconfigure(
            "person@example.test",
            credential,
            fetcher=lambda _url: b"<clientConfig/>",
            imap_probe=lambda *_: (_ for _ in ()).throw(RuntimeError("no")),
        )
    assert failure.value.domain == "example.test"
    assert credential not in str(failure.value)
    assert "person@example.test" not in str(failure.value)


def test_official_hint_is_first_and_requires_complete_secure_values():
    imap, _, _ = discover_candidates(
        "person@example.test",
        hints={
            "imap": {
                "host": "mail.provider.test",
                "port": 993,
                "security": "implicit_tls",
                "username_style": "localpart",
            }
        },
        fetcher=lambda _url: b"<clientConfig/>",
    )
    assert imap[0].source == "official-provider-hint"
    assert imap[0].username == "person"

    with pytest.raises(AutoConfigurationError, match="invalid provider settings"):
        discover_candidates(
            "person@example.test",
            hints={"imap": {"host": "mail.provider.test", "port": 993}},
            fetcher=lambda _url: b"<clientConfig/>",
        )
