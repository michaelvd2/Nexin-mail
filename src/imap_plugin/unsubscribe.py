from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse


class UnsubscribeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedEndpoint:
    url: str
    hostname: str
    address: str
    port: int
    request_target: str


def resolve_public_https_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> ResolvedEndpoint:
    if len(url) > 2048 or any(char in url for char in "\r\n\x00"):
        raise UnsubscribeError("unsubscribe endpoint is invalid")
    parsed = urlparse(url)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise UnsubscribeError("unsubscribe requires a public HTTPS endpoint without credentials or fragments")
    if parsed.port not in {None, 443}:
        raise UnsubscribeError("unsubscribe endpoints are restricted to HTTPS port 443")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
        answers = resolver(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsubscribeError("unsubscribe endpoint DNS resolution failed") from exc
    addresses = sorted({answer[4][0].split("%", 1)[0] for answer in answers})
    if not addresses:
        raise UnsubscribeError("unsubscribe endpoint did not resolve")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise UnsubscribeError("private, local, reserved, or non-global unsubscribe endpoints are blocked")
    normalized = parsed._replace(netloc=hostname if parsed.port is None else f"{hostname}:{parsed.port}").geturl()
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return ResolvedEndpoint(normalized, hostname, addresses[0], parsed.port or 443, target)


def validate_public_https_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> str:
    return resolve_public_https_url(url, resolver).url


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Use the validated IP while preserving the hostname for SNI and certificate checks."""

    def __init__(self, hostname: str, address: str, port: int, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(hostname, port=port, context=context, timeout=timeout)
        self._validated_address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._validated_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _connection(
    hostname: str,
    address: str,
    port: int,
    context: ssl.SSLContext,
    timeout: float,
) -> http.client.HTTPSConnection:
    return _PinnedHTTPSConnection(hostname, address, port, context, timeout)


def one_click_unsubscribe(
    url: str,
    *,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    connection_factory: Callable[[str, str, int, ssl.SSLContext, float], Any] = _connection,
) -> dict[str, Any]:
    endpoint = resolve_public_https_url(url, resolver)
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    client = connection_factory(endpoint.hostname, endpoint.address, endpoint.port, context, 15.0)
    try:
        client.request(
            "POST",
            endpoint.request_target,
            body=b"List-Unsubscribe=One-Click",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "IMAP-Plugin/1",
                "Content-Length": "26",
            },
        )
        response = client.getresponse()
        status = int(response.status)
        response.read(4096)
    except Exception as exc:
        raise UnsubscribeError("unsubscribe request failed; it was not retried") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
    if 300 <= status < 400:
        raise UnsubscribeError("unsubscribe redirects are blocked in v1")
    if not 200 <= status < 300:
        raise UnsubscribeError(f"unsubscribe endpoint returned HTTP {status}")
    return {
        "result": "unsubscribe request accepted",
        "http_status": status,
        "redirected": False,
        "dns_pinned_for_request": True,
    }


def fetch_public_https_image(
    url: str,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    connection_factory: Callable[[str, str, int, ssl.SSLContext, float], Any] = _connection,
) -> dict[str, Any]:
    if not 1 <= max_bytes <= 5 * 1024 * 1024:
        raise UnsubscribeError("remote image ceiling must be 1..5 MiB")
    endpoint = resolve_public_https_url(url, resolver)
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    client = connection_factory(endpoint.hostname, endpoint.address, endpoint.port, context, 15.0)
    try:
        client.request(
            "GET",
            endpoint.request_target,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
                "User-Agent": "IMAP-Plugin/1",
            },
        )
        response = client.getresponse()
        status = int(response.status)
        content_type = str(response.getheader("Content-Type") or "").split(";", 1)[0].strip().casefold()
        content_length = response.getheader("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise UnsubscribeError("remote image exceeds the 5 MiB per-image ceiling")
        raw = response.read(max_bytes + 1)
    except UnsubscribeError:
        raise
    except Exception as exc:
        raise UnsubscribeError("remote image request failed; it was not retried") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
    if 300 <= status < 400:
        raise UnsubscribeError("remote image redirects are blocked")
    if not 200 <= status < 300:
        raise UnsubscribeError(f"remote image endpoint returned HTTP {status}")
    if content_type not in {"image/avif", "image/webp", "image/png", "image/jpeg", "image/gif"}:
        raise UnsubscribeError("remote content is not an allowed raster image")
    if len(raw) > max_bytes:
        raise UnsubscribeError("remote image exceeds the 5 MiB per-image ceiling")
    return {
        "content": raw,
        "content_type": content_type,
        "bytes": len(raw),
        "http_status": status,
        "redirected": False,
        "dns_pinned_for_request": True,
    }
