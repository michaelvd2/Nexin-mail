from __future__ import annotations

import socket

import pytest

from imap_plugin.unsubscribe import UnsubscribeError, fetch_public_https_image, one_click_unsubscribe, validate_public_https_url


def resolver_for(address):
    def resolver(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]
    return resolver


@pytest.mark.parametrize("url", ["http://example.test/u", "https://user:pass@example.test/u", "https://example.test:8443/u"])
def test_unsubscribe_requires_plain_public_https_443(url):
    with pytest.raises(UnsubscribeError):
        validate_public_https_url(url, resolver_for("93.184.216.34"))


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.1.2", "192.168.1.1"])
def test_unsubscribe_blocks_ssrf_addresses(address):
    with pytest.raises(UnsubscribeError):
        validate_public_https_url("https://example.test/u", resolver_for(address))


def test_unsubscribe_accepts_public_https_address():
    assert validate_public_https_url("https://example.test/u", resolver_for("93.184.216.34")) == "https://example.test/u"


class FakeResponse:
    def __init__(self, status, *, content_type="text/plain", body=b"ok"):
        self.status = status
        self.content_type = content_type
        self.body = body

    def read(self, limit):
        return self.body[:limit]

    def getheader(self, name):
        if name.casefold() == "content-type":
            return self.content_type
        if name.casefold() == "content-length":
            return str(len(self.body))
        return None


class FakeConnection:
    def __init__(self, status=204, *, content_type="text/plain", body=b"ok"):
        self.status = status
        self.content_type = content_type
        self.body = body
        self.request_args = None
        self.closed = False

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)

    def getresponse(self):
        return FakeResponse(self.status, content_type=self.content_type, body=self.body)

    def close(self):
        self.closed = True


def test_unsubscribe_pins_validated_dns_address_and_posts_once():
    observed = {}
    fake = FakeConnection()

    def factory(hostname, address, port, context, timeout):
        observed.update(hostname=hostname, address=address, port=port, check_hostname=context.check_hostname)
        return fake

    result = one_click_unsubscribe(
        "https://example.test/unsubscribe?id=4",
        resolver=resolver_for("93.184.216.34"),
        connection_factory=factory,
    )
    assert observed == {"hostname": "example.test", "address": "93.184.216.34", "port": 443, "check_hostname": True}
    assert fake.request_args[0][:2] == ("POST", "/unsubscribe?id=4")
    assert result["dns_pinned_for_request"] is True
    assert fake.closed is True


def test_unsubscribe_does_not_follow_redirects():
    with pytest.raises(UnsubscribeError, match="redirects are blocked"):
        one_click_unsubscribe(
            "https://example.test/u",
            resolver=resolver_for("93.184.216.34"),
            connection_factory=lambda *args: FakeConnection(302),
        )


def test_remote_image_fetch_is_https_pinned_bounded_and_raster_only():
    fake = FakeConnection(200, content_type="image/png", body=b"\x89PNGunit")
    result = fetch_public_https_image(
        "https://images.example.test/pixel.png?id=4",
        resolver=resolver_for("93.184.216.34"),
        connection_factory=lambda *args: fake,
    )
    assert result["content"] == b"\x89PNGunit"
    assert result["content_type"] == "image/png"
    assert fake.request_args[0][:2] == ("GET", "/pixel.png?id=4")
    assert fake.closed is True


def test_remote_image_fetch_blocks_html_and_redirects():
    with pytest.raises(UnsubscribeError, match="not an allowed raster image"):
        fetch_public_https_image(
            "https://images.example.test/content",
            resolver=resolver_for("93.184.216.34"),
            connection_factory=lambda *args: FakeConnection(200, content_type="text/html"),
        )
    with pytest.raises(UnsubscribeError, match="redirects are blocked"):
        fetch_public_https_image(
            "https://images.example.test/redirect",
            resolver=resolver_for("93.184.216.34"),
            connection_factory=lambda *args: FakeConnection(302, content_type="image/png"),
        )
