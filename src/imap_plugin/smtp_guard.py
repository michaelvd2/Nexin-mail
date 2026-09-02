"""Test-only SMTP guardrail harness.

This module is never imported by the production MCP server and accepts only
loopback destinations while IMAP_PLUGIN_TEST_MODE=1.
"""
from __future__ import annotations

import os
import time
from collections import deque
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid
from ipaddress import ip_address
from typing import Callable


class SmtpGuardError(RuntimeError):
    pass


class TestOnlySmtpGuard:
    __test__ = False

    def __init__(self, host: str, port: int, allowlist: set[str], transport_factory: Callable, max_per_minute: int = 3) -> None:
        if os.environ.get("IMAP_PLUGIN_TEST_MODE") != "1":
            raise SmtpGuardError("SMTP harness is disabled outside explicit test mode")
        try:
            if not ip_address(host).is_loopback:
                raise SmtpGuardError("SMTP harness accepts loopback destinations only")
        except ValueError as exc:
            raise SmtpGuardError("SMTP harness requires a numeric loopback host") from exc
        self.host = host
        self.port = port
        self.allowlist = {value.casefold() for value in allowlist}
        self.transport_factory = transport_factory
        self.max_per_minute = max_per_minute
        self.sent_ids: set[str] = set()
        self.times: deque[float] = deque()

    @staticmethod
    def _check_headers(message: EmailMessage) -> None:
        for name, value in message.items():
            if "\r" in value or "\n" in value:
                raise SmtpGuardError(f"header injection rejected in {name}")
        if message.get("Bcc"):
            raise SmtpGuardError("BCC is rejected")

    def send(self, message: EmailMessage, confirmed: bool, idempotency_key: str) -> str:
        if not confirmed:
            raise SmtpGuardError("explicit per-message confirmation is required")
        if not idempotency_key or idempotency_key in self.sent_ids:
            raise SmtpGuardError("duplicate or missing idempotency key")
        self._check_headers(message)
        recipients = {addr.casefold() for _, addr in getaddresses(message.get_all("To", []) + message.get_all("Cc", []))}
        if not recipients or not recipients.issubset(self.allowlist):
            raise SmtpGuardError("recipient outside allowlist")
        now = time.monotonic()
        while self.times and now - self.times[0] >= 60:
            self.times.popleft()
        if len(self.times) >= self.max_per_minute:
            raise SmtpGuardError("rate limit exceeded")
        if not message.get("Message-ID"):
            message["Message-ID"] = make_msgid(domain="imap-plugin.test")
        with self.transport_factory(self.host, self.port, timeout=5) as client:
            client.send_message(message, to_addrs=sorted(recipients))
        self.sent_ids.add(idempotency_key)
        self.times.append(now)
        return str(message["Message-ID"])
