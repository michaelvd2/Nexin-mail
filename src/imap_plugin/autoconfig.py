from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .bridge import MailBridge
from .config import AccountConfig, _validated_hostname
from .sender import MailSender


MAX_AUTOCONFIG_BYTES = 262_144
DISCOVERY_TIMEOUT_SECONDS = 8.0


class AutoConfigurationError(RuntimeError):
    def __init__(self, message: str, *, domain: str = "") -> None:
        super().__init__(message)
        self.domain = domain


@dataclass(frozen=True)
class ServerCandidate:
    protocol: str
    host: str
    port: int
    security: str
    username: str
    source: str

    def __post_init__(self) -> None:
        if self.protocol not in {"imap", "smtp"}:
            raise ValueError("protocol must be imap or smtp")
        object.__setattr__(self, "host", _validated_hostname(self.host, "mail server"))
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("mail server port must be between 1 and 65535")
        if self.security not in {"implicit_tls", "starttls"}:
            raise ValueError("mail server security must be implicit_tls or starttls")
        if not self.username or any(char in self.username for char in "\r\n\x00"):
            raise ValueError("mail username must be a non-empty single-line value")


@dataclass(frozen=True)
class AutoConfigurationResult:
    settings: AccountConfig
    source: str
    mailbox_actions_ready: bool
    send_ready: bool

    def public_dict(self) -> dict[str, Any]:
        settings = self.settings
        return {
            "status": "configured",
            "source": self.source,
            "email_address": settings.email_address,
            "username": settings.username,
            "host": settings.host,
            "port": settings.port,
            "imap_security": settings.imap_security,
            "smtp_configured": settings.send_configured,
            "smtp_host": settings.smtp_host,
            "smtp_port": settings.smtp_port,
            "smtp_security": settings.smtp_security if settings.send_configured else None,
            "smtp_username": settings.smtp_login if settings.send_configured else None,
            "operator_enabled": settings.operator_enabled,
            "mailbox_actions_ready": self.mailbox_actions_ready,
            "send_ready": self.send_ready,
        }


Fetcher = Callable[[str], bytes]
ImapProbe = Callable[[ServerCandidate, str, str], dict[str, Any]]
SmtpProbe = Callable[[ServerCandidate, ServerCandidate, str, str], dict[str, Any]]


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise urllib.error.URLError("autoconfiguration refused a non-HTTPS redirect")
        _validated_hostname(parsed.hostname, "autoconfiguration redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_xml(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "IMAP-Plugin-Autoconfig/0.1.4"},
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _HttpsOnlyRedirectHandler(),
    )
    with opener.open(request, timeout=DISCOVERY_TIMEOUT_SECONDS) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme.casefold() != "https" or not final.hostname:
            raise urllib.error.URLError("autoconfiguration requires HTTPS")
        payload = response.read(MAX_AUTOCONFIG_BYTES + 1)
    if len(payload) > MAX_AUTOCONFIG_BYTES:
        raise AutoConfigurationError("The provider's automatic settings response was too large.")
    return payload


def _email_parts(value: str) -> tuple[str, str, str]:
    address = value.strip()
    if address.count("@") != 1 or any(char in address for char in "\r\n\x00"):
        raise AutoConfigurationError("Enter one valid email address.")
    local, raw_domain = address.rsplit("@", 1)
    if not local or len(local) > 128:
        raise AutoConfigurationError("Enter one valid email address.")
    try:
        domain = _validated_hostname(raw_domain, "email domain")
    except ValueError as exc:
        raise AutoConfigurationError("Enter one valid email address.") from exc
    normalized = f"{local}@{domain}"
    return normalized, local, domain


def _username(template: str, email: str, local: str, domain: str) -> str:
    value = (template or "%EMAILADDRESS%").strip()
    replacements = {
        "%EMAILADDRESS%": email,
        "%EMAILLOCALPART%": local,
        "%EMAILDOMAIN%": domain,
    }
    for marker, replacement in replacements.items():
        value = value.replace(marker, replacement)
    if "%" in value or not value or any(char in value for char in "\r\n\x00"):
        raise ValueError("unsupported username template")
    return value


def _security(socket_type: str) -> str | None:
    normalized = (socket_type or "").strip().casefold().replace("-", "")
    if normalized in {"ssl", "ssl/tls", "ssltls"}:
        return "implicit_tls"
    if normalized == "starttls":
        return "starttls"
    return None


def parse_thunderbird_config(
    payload: bytes,
    email_address: str,
    source: str,
) -> tuple[list[ServerCandidate], list[ServerCandidate]]:
    if len(payload) > MAX_AUTOCONFIG_BYTES:
        raise ValueError("autoconfiguration response is too large")
    upper = payload[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DTD and entity declarations are forbidden")
    email, local, domain = _email_parts(email_address)
    root = ET.fromstring(payload)
    imap: list[ServerCandidate] = []
    smtp: list[ServerCandidate] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        protocol = (element.attrib.get("type") or "").casefold()
        if tag not in {"incomingServer", "outgoingServer"} or protocol not in {"imap", "smtp"}:
            continue
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in element}
        security = _security(values.get("socketType", ""))
        if security is None:
            continue
        try:
            candidate = ServerCandidate(
                protocol=protocol,
                host=values["hostname"],
                port=int(values["port"]),
                security=security,
                username=_username(values.get("username", ""), email, local, domain),
                source=source,
            )
        except (KeyError, TypeError, ValueError):
            continue
        (imap if protocol == "imap" else smtp).append(candidate)
    return imap, smtp


def _hint_candidate(
    protocol: str,
    raw: dict[str, Any] | None,
    email: str,
    local: str,
    domain: str,
) -> ServerCandidate | None:
    if not raw:
        return None
    style = str(raw.get("username_style", "email")).casefold()
    if style not in {"email", "localpart"}:
        raise AutoConfigurationError("Codex supplied an unsupported username style.", domain=domain)
    username = email if style == "email" else local
    try:
        return ServerCandidate(
            protocol=protocol,
            host=str(raw["host"]),
            port=int(raw["port"]),
            security=str(raw["security"]),
            username=username,
            source="official-provider-hint",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AutoConfigurationError("Codex supplied invalid provider settings.", domain=domain) from exc


def _deduplicate(values: Iterable[ServerCandidate]) -> list[ServerCandidate]:
    result: list[ServerCandidate] = []
    seen: set[tuple[str, str, int, str, str]] = set()
    for value in values:
        key = (value.protocol, value.host, value.port, value.security, value.username.casefold())
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def discover_candidates(
    email_address: str,
    *,
    hints: dict[str, Any] | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[list[ServerCandidate], list[ServerCandidate], str]:
    email, local, domain = _email_parts(email_address)
    imap: list[ServerCandidate] = []
    smtp: list[ServerCandidate] = []
    hint_imap = _hint_candidate("imap", (hints or {}).get("imap"), email, local, domain)
    hint_smtp = _hint_candidate("smtp", (hints or {}).get("smtp"), email, local, domain)
    if hint_imap:
        imap.append(hint_imap)
    if hint_smtp:
        smtp.append(hint_smtp)

    encoded_email = urllib.parse.quote(email, safe="")
    urls = (
        (f"https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={encoded_email}", "provider-autoconfig"),
        (f"https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml?emailaddress={encoded_email}", "provider-well-known"),
        (f"https://autoconfig.thunderbird.net/v1.1/{urllib.parse.quote(domain, safe='')}", "mozilla-ispdb"),
    )
    load = fetcher or _fetch_xml
    for url, source in urls:
        try:
            found_imap, found_smtp = parse_thunderbird_config(load(url), email, source)
        except Exception:
            continue
        imap.extend(found_imap)
        smtp.extend(found_smtp)

    for username in (email, local):
        imap.extend(
            ServerCandidate("imap", host, port, security, username, "secure-host-discovery")
            for host in (f"imap.{domain}", f"mail.{domain}")
            for port, security in ((993, "implicit_tls"), (143, "starttls"))
        )
        smtp.extend(
            ServerCandidate("smtp", host, port, security, username, "secure-host-discovery")
            for host in (f"smtp.{domain}", f"mail.{domain}")
            for port, security in ((465, "implicit_tls"), (587, "starttls"))
        )
    return _deduplicate(imap), _deduplicate(smtp), domain


def _probe_imap(candidate: ServerCandidate, password: str, email: str) -> dict[str, Any]:
    settings = AccountConfig(
        username=candidate.username,
        email_address=email,
        host=candidate.host,
        port=candidate.port,
        imap_security=candidate.security,
        timeout_seconds=DISCOVERY_TIMEOUT_SECONDS,
    )
    return MailBridge(settings, "read", secret_reader=lambda _target: password).tls_and_capabilities()


def _probe_smtp(imap: ServerCandidate, smtp: ServerCandidate, password: str, email: str) -> dict[str, Any]:
    settings = AccountConfig(
        username=imap.username,
        email_address=email,
        host=imap.host,
        port=imap.port,
        imap_security=imap.security,
        smtp_host=smtp.host,
        smtp_port=smtp.port,
        smtp_security=smtp.security,
        smtp_username=smtp.username,
        timeout_seconds=DISCOVERY_TIMEOUT_SECONDS,
    )
    return MailSender(settings, lambda _target: password).probe()


def autoconfigure(
    email_address: str,
    password: str,
    *,
    hints: dict[str, Any] | None = None,
    fetcher: Fetcher | None = None,
    imap_probe: ImapProbe | None = None,
    smtp_probe: SmtpProbe | None = None,
) -> AutoConfigurationResult:
    email, _, domain = _email_parts(email_address)
    if not password or len(password) > 4096:
        raise AutoConfigurationError("Enter your password or provider-issued app password.", domain=domain)
    imap_candidates, smtp_candidates, _ = discover_candidates(email, hints=hints, fetcher=fetcher)
    probe_imap = imap_probe or _probe_imap
    selected_imap: ServerCandidate | None = None
    health: dict[str, Any] = {}
    for candidate in imap_candidates:
        try:
            health = probe_imap(candidate, password, email)
            if health.get("tls", {}).get("verified") is True:
                selected_imap = candidate
                break
        except Exception:
            continue
    if selected_imap is None:
        raise AutoConfigurationError(
            f"Automatic setup could not verify secure IMAP settings for {domain}. Codex can retry using the provider's official settings; the password was not logged.",
            domain=domain,
        )

    gates = health.get("operator_features", {})
    mailbox_actions_ready = all(gates.get(name) is True for name in ("safe_move", "drafts", "bin"))
    selected_smtp: ServerCandidate | None = None
    probe_smtp = smtp_probe or _probe_smtp
    for candidate in smtp_candidates:
        try:
            smtp_health = probe_smtp(selected_imap, candidate, password, email)
            if smtp_health.get("authenticated") is True and smtp_health.get("tls_verified") is True:
                selected_smtp = candidate
                break
        except Exception:
            continue

    settings = AccountConfig(
        username=selected_imap.username,
        email_address=email,
        host=selected_imap.host,
        port=selected_imap.port,
        imap_security=selected_imap.security,
        smtp_host=selected_smtp.host if selected_smtp else None,
        smtp_port=selected_smtp.port if selected_smtp else None,
        smtp_security=selected_smtp.security if selected_smtp else "implicit_tls",
        smtp_username=selected_smtp.username if selected_smtp else None,
        operator_enabled=mailbox_actions_ready,
    )
    send_ready = bool(
        selected_smtp
        and mailbox_actions_ready
        and gates.get("sent") is True
    )
    sources = [selected_imap.source]
    if selected_smtp and selected_smtp.source not in sources:
        sources.append(selected_smtp.source)
    return AutoConfigurationResult(settings, "+".join(sources), mailbox_actions_ready, send_ready)
