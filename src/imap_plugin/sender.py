from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from difflib import SequenceMatcher
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, getaddresses
from typing import Any, Callable, Iterable

from .config import AccountConfig
from .contracts import canonical_digest


class SendError(RuntimeError):
    def __init__(self, message: str, *, ambiguous: bool = False) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous


def parse_recipients(*values: str) -> tuple[str, ...]:
    if any(any(char in value for char in "\r\n\x00") for value in values):
        raise SendError("recipient fields must be single-line values")
    addresses = []
    for _, address in getaddresses([value for value in values if value]):
        normalized = address.strip()
        if not normalized or "@" not in normalized or any(char in normalized for char in "\r\n\x00"):
            raise SendError("every recipient must be a valid single-line email address")
        addresses.append(normalized)
    result = tuple(dict.fromkeys(address.casefold() for address in addresses))
    return result


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].casefold().encode("idna").decode("ascii")


def recipient_warnings(from_address: str, to: Iterable[str], cc: Iterable[str]) -> tuple[str, ...]:
    recipients = tuple(to) + tuple(cc)
    warnings = ["Review every recipient; sending cannot be undone."]
    from_domain = _domain(from_address)
    external = sorted({_domain(address) for address in recipients if _domain(address) != from_domain})
    if external:
        warnings.append("External recipient domains: " + ", ".join(external))
    lookalikes = []
    for domain in external:
        similarity = SequenceMatcher(a=domain.replace("-", ""), b=from_domain.replace("-", "")).ratio()
        if similarity >= 0.78:
            lookalikes.append(domain)
    if lookalikes:
        warnings.append("Possible lookalike domain: " + ", ".join(lookalikes))
    if tuple(cc):
        warnings.append("This message includes Cc recipients; verify reply-all scope.")
    return tuple(warnings)


def build_message(
    *,
    from_address: str,
    to: tuple[str, ...],
    cc: tuple[str, ...],
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str = "",
) -> EmailMessage:
    if any(char in subject for char in "\r\n\x00") or len(subject) > 500:
        raise SendError("subject contains forbidden characters or is too long")
    if "\x00" in body or len(body.encode("utf-8")) > 262_144:
        raise SendError("body contains a null byte or exceeds the v1 limit")
    if not to:
        raise SendError("at least one To recipient is required")
    if len(to) + len(cc) > 10:
        raise SendError("v1 allows at most ten total recipients")
    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = message_id
    if in_reply_to:
        if any(char in in_reply_to for char in "\r\n\x00"):
            raise SendError("reply reference contains forbidden characters")
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    if msg.get("Bcc"):
        raise SendError("BCC is disabled in v1")
    return msg


def send_digest(message: EmailMessage) -> str:
    return canonical_digest({
        "from": message.get("From", ""),
        "to": message.get("To", ""),
        "cc": message.get("Cc", ""),
        "subject": message.get("Subject", ""),
        "body": message.get_body(preferencelist=("plain",)).get_content(),
        "message_id": message.get("Message-ID", ""),
    })


def delivery_content_digest(message: EmailMessage) -> str:
    """Stable across fresh Message-IDs so an ambiguous draft cannot be resent."""
    return canonical_digest({
        "from": message.get("From", ""),
        "to": message.get("To", ""),
        "cc": message.get("Cc", ""),
        "subject": message.get("Subject", ""),
        "body": message.get_body(preferencelist=("plain",)).get_content(),
        "in_reply_to": message.get("In-Reply-To", ""),
    })


@dataclass(frozen=True)
class SendResult:
    message_id: str
    digest: str
    raw: bytes


class MailSender:
    def __init__(
        self,
        settings: AccountConfig,
        secret_reader: Callable[[str], str],
        transport_factory: Callable[[AccountConfig, ssl.SSLContext], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.secret_reader = secret_reader
        self.transport_factory = transport_factory or self._open_transport

    @staticmethod
    def _open_transport(settings: AccountConfig, context: ssl.SSLContext) -> Any:
        if not settings.send_configured:
            raise SendError("SMTP is not configured for this account")
        if settings.smtp_security == "implicit_tls":
            return smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.timeout_seconds,
                context=context,
            )
        transport_type = getattr(smtplib, "SMTP")
        client = transport_type(settings.smtp_host, settings.smtp_port, timeout=settings.timeout_seconds)
        client.ehlo()
        client.starttls(context=context)
        client.ehlo()
        return client

    def send_once(self, message: EmailMessage) -> SendResult:
        if not self.settings.send_configured:
            raise SendError("SMTP is not configured for this account")
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        invoked_send = False
        client = None
        try:
            client = self.transport_factory(self.settings, context)
            client.login(
                self.settings.smtp_login,
                self.secret_reader(self.settings.smtp_credential_target),
            )
            invoked_send = True
            refused = client.send_message(
                message,
                from_addr=self.settings.from_address,
                to_addrs=list(parse_recipients(message.get("To", ""), message.get("Cc", ""))),
            )
            if refused:
                raise SendError(
                    "the message may have reached some recipients while others were refused; do not resend",
                    ambiguous=True,
                )
        except SendError:
            raise
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise SendError("the mail server rejected the envelope", ambiguous=False) from exc
        except smtplib.SMTPDataError as exc:
            ambiguous = invoked_send and int(getattr(exc, "smtp_code", 0) or 0) < 500
            raise SendError("the mail server returned an error after message submission", ambiguous=ambiguous) from exc
        except Exception as exc:
            raise SendError(
                "the send result is ambiguous; do not resend automatically" if invoked_send else "the mail server connection failed before submission",
                ambiguous=invoked_send,
            ) from exc
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    try:
                        client.close()
                    except Exception:
                        pass
        raw = message.as_bytes(policy=SMTP)
        return SendResult(str(message["Message-ID"]), send_digest(message), raw)

    def probe(self) -> dict[str, Any]:
        """Authenticate over verified TLS without submitting a message."""
        if not self.settings.send_configured:
            return {"configured": False, "authenticated": False, "tls_verified": False}
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        client = None
        try:
            client = self.transport_factory(self.settings, context)
            client.login(
                self.settings.smtp_login,
                self.secret_reader(self.settings.smtp_credential_target),
            )
            code, _ = client.noop()
            if int(code) >= 400:
                raise SendError("SMTP health check was rejected")
            return {
                "configured": True,
                "authenticated": True,
                "tls_verified": True,
                "security": self.settings.smtp_security,
                "endpoint": f"{self.settings.smtp_host}:{self.settings.smtp_port}",
            }
        except SendError:
            raise
        except Exception as exc:
            raise SendError("SMTP authentication or TLS verification failed") from exc
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    try:
                        client.close()
                    except Exception:
                        pass
