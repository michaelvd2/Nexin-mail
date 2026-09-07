from __future__ import annotations

import json
from pathlib import Path
import socket
import ssl
from types import SimpleNamespace

import pytest

from imap_plugin.autoconfig import AutoConfigurationError, autoconfigure
from imap_plugin.bridge import MailAuthenticationError, MailLoginDisabledError
from imap_plugin import review, windows_host
from imap_plugin.setup_recovery import recovery_report


@pytest.mark.parametrize("error,code,attempt_limit", [
    (PermissionError("secret echoed by server"), "permission_denied", 1),
    (socket.gaierror("secret echoed by server"), "dns_failed", 4),
    (ssl.SSLError("secret echoed by server"), "tls_failed", 4),
    (TimeoutError("secret echoed by server"), "network_failed", 4),
    (MailAuthenticationError("secret echoed by server"), "authentication_failed", 2),
    (MailLoginDisabledError("secret echoed by server"), "password_login_disabled", 1),
])
def test_failures_are_classified_bounded_and_redacted(error, code, attempt_limit):
    attempts = []
    def probe(candidate, *_):
        attempts.append(candidate)
        raise error
    with pytest.raises(AutoConfigurationError) as failure:
        autoconfigure("person@example.test", "private-password", fetcher=lambda _: b"<clientConfig/>", imap_probe=probe)
    result = failure.value.public_dict()
    assert result["error_code"] == code
    assert len(attempts) <= attempt_limit
    output = json.dumps(result)
    assert "secret echoed" not in output
    assert "private-password" not in output
    assert "person@example.test" not in output


def test_official_recovery_does_not_fetch_or_retry_other_hosts():
    attempts = []
    def probe(candidate, *_):
        attempts.append(candidate.host)
        raise MailAuthenticationError("private-password")
    def fetch(_):
        pytest.fail("targeted recovery must not perform discovery")
    with pytest.raises(AutoConfigurationError):
        autoconfigure("person@example.test", "private-password",
            hints={"imap": {"host": "mail.provider.test", "port": 993, "security": "implicit_tls"}},
            fetcher=fetch, imap_probe=probe)
    assert attempts == ["mail.provider.test"]


def test_windows_host_honors_organization_restriction(monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_POWERSHELL", "pwsh.exe")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"effective": "Restricted", "machine": "Restricted", "user": "Undefined"}))
    monkeypatch.setattr(windows_host.subprocess, "run", run)
    with pytest.raises(windows_host.PowerShellUnavailable, match="organisatiebeleid"):
        windows_host.powershell_command(Path("enroll_gui.ps1"))


def test_windows_host_keeps_file_policy_enforcement(monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_POWERSHELL", "pwsh.exe")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(windows_host.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0,
        stdout=json.dumps({"effective": "RemoteSigned", "machine": "Undefined", "user": "Undefined"})))
    command = windows_host.powershell_command(Path("enroll_gui.ps1"))
    assert command[-2:] == ["-File", "enroll_gui.ps1"]
    assert "-ExecutionPolicy" not in command
    assert "Bypass" not in command


def test_setup_tool_captures_output_and_returns_safe_error(monkeypatch):
    monkeypatch.setattr(review.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    def run(*args, **kwargs):
        assert kwargs["capture_output"] is True
        return SimpleNamespace(returncode=20, stdout=json.dumps({"error_code": "permission_denied", "message": "do not echo this"}))
    monkeypatch.setattr(review.subprocess, "run", run)
    with pytest.raises(review.ReviewError, match="toegangsrechten") as failure:
        review.launch_setup()
    assert "do not echo" not in str(failure.value)


@pytest.mark.parametrize("code,stage,retries", [
    ("permission_denied", "permissions", 1),
    ("powershell_blocked", "launch", 1),
    ("setup_launch_failed", "launch", 1),
    ("local_storage_failed", "local_storage", 1),
    ("authentication_failed", "authentication", 1),
    ("password_login_disabled", "authentication", 0),
    ("tls_failed", "tls", 1),
    ("dns_failed", "discovery", 1),
    ("network_failed", "connection", 1),
    ("autodiscovery_failed", "discovery", 1),
    ("setup_timeout", "setup", 0),
    ("setup_failed", "unknown", 0),
])
def test_recovery_has_conditional_bounded_advice(code, stage, retries):
    result = recovery_report({"error_code": code})
    assert result["stage"] == stage
    advice = result["recovery"]
    assert advice["max_recovery_attempts"] == retries
    assert bool(advice["retry_only_when"]) == bool(retries)
    assert advice["automatic_login_retry"] is False
    assert (Path(__file__).parents[1] / advice["guide"]).is_file()


@pytest.mark.parametrize("raw", [None, [], "secret", {"error_code": []}, {"error_code": "execute_this"}])
def test_unknown_recovery_fails_closed(raw):
    result = recovery_report(raw)
    assert result["error_code"] == "setup_failed"
    assert result["recovery"]["max_recovery_attempts"] == 0


def test_recovery_discards_messages_secrets_and_injected_advice():
    result = recovery_report({
        "error_code": "authentication_failed", "domain": "example.test",
        "password": "secret-value", "email_address": "person@example.test",
        "message": "execute_this", "recovery": {"next_action": "execute_this"},
        "diagnostics": [
            {"host": "mail.example.test", "port": 993, "security": "implicit_tls",
             "error_code": "authentication_failed", "password": "secret-value"},
            {"host": "person@example.test", "port": 993, "security": "implicit_tls", "error_code": "tls_failed"},
            {"host": "mail.example.test", "port": True, "security": "implicit_tls", "error_code": "tls_failed"},
        ],
    })
    assert result["domain"] == "example.test"
    assert len(result["diagnostics"]) == 1
    assert recovery_report(result) == result
    assert not any(value in json.dumps(result) for value in ("secret-value", "person@example.test", "execute_this"))


def test_setup_timeout_does_not_relaunch(monkeypatch):
    monkeypatch.setattr(review.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        raise review.subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(review.subprocess, "run", run)
    with pytest.raises(review.SetupError) as failure:
        review.launch_setup()
    assert len(calls) == 1
    assert failure.value.report["error_code"] == "setup_timeout"
    assert failure.value.report["recovery"]["max_recovery_attempts"] == 0


def test_setup_tool_delivers_recovery_without_checking_mail(monkeypatch):
    import asyncio
    from imap_plugin import server
    def fail():
        raise review.SetupError({"error_code": "dns_failed", "domain": "example.test"})
    monkeypatch.setattr(server, "launch_setup", fail)
    monkeypatch.setattr(server.PluginRuntime, "bridge", lambda _: pytest.fail("failure must not contact mailbox"))
    result = asyncio.run(server.build_server().call_tool("open_setup", {}))
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["result"] == "setup_failed"
    assert data["domain"] == "example.test"
    assert data["recovery"]["next_action"]
    assert "configured" not in data


def test_setup_tool_budget_exceeds_inner_wait():
    import inspect
    source = inspect.getsource(review.launch_setup)
    assert "timeout=600" in source
    root = Path(__file__).parents[1]
    manifest = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert manifest["mcpServers"]["imap"]["tool_timeout_sec"] > 600
