import asyncio
import json
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from imap_plugin.approval import ApprovalError
from imap_plugin.contracts import MessageRef
from imap_plugin.operator import MailOperator, OperatorError
from imap_plugin.server import ACTION_TOOLS, READ_TOOLS, build_server


def payload(result):
    assert result.is_error is False
    return json.loads(result.content[0].text)


def test_server_uses_one_display_title():
    server = build_server()
    assert server._lowlevel_server.name == "imap-plugin"
    assert server._lowlevel_server.title is None
    config = json.loads((Path(__file__).parents[1] / ".mcp.json").read_text(encoding="utf-8"))
    assert "title" not in config["mcpServers"]["imap"]


def test_standalone_registry_is_exact_and_excludes_unsafe_raw_surface():
    names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    assert names == set(READ_TOOLS + ACTION_TOOLS)
    assert not names.intersection(
        {
            "bulk_send",
            "empty_bin",
            "expunge",
            "load_remote_images",
            "permanent_delete",
            "raw_imap",
            "render_mail_view",
            "unsubscribe",
        }
    )
    assert all(name == "open_setup" or name.startswith("review_") for name in ACTION_TOOLS)
    assert {
        "inspect_cleanup",
        "inspect_unsubscribe_candidates",
        "get_pack_settings",
        "rank_priority",
    }.issubset(names)
    assert {
        "review_bulk_mailbox_action",
        "review_unsubscribe",
        "review_bulk_unsubscribe",
        "review_update_pack_settings",
        "review_set_priority_rules",
    }.issubset(names)


def test_setup_status_works_before_customer_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = asyncio.run(build_server().call_tool("setup_status", {}))
    assert payload(result) == {
        "configured": False,
        "platform": "windows" if platform.system() == "Windows" else "macos",
        "profile": "unconfigured",
        "credentials": {"imap": False, "smtp": False},
    }


class StubOperator:
    def __init__(self):
        self.commits = 0

    def create_ui_session(self):
        return "session"

    def prepare_draft(self, **kwargs):
        return {"action": "save_draft", "exact": kwargs}, "private-handle"

    def commit_draft(self, **kwargs):
        self.commits += 1
        assert kwargs["approval_handle"] == "private-handle"
        return {"result": "draft_saved"}


class StubBridge:
    profile = "operator"


def test_native_review_cancellation_does_not_commit():
    operator = StubOperator()
    server = build_server(profile="operator", bridge=StubBridge(), operator=operator, reviewer=lambda *_: False)
    result = asyncio.run(
        server.call_tool(
            "review_save_draft",
            {"to": "customer@example.test", "subject": "Test", "body": "Body"},
        )
    )
    assert payload(result)["result"] == "cancelled"
    assert payload(result)["mailbox_changed"] is False
    assert operator.commits == 0


def test_native_review_confirmation_commits_exactly_once():
    operator = StubOperator()
    server = build_server(profile="operator", bridge=StubBridge(), operator=operator, reviewer=lambda *_: True)
    result = asyncio.run(
        server.call_tool(
            "review_save_draft",
            {"to": "customer@example.test", "subject": "Test", "body": "Body"},
        )
    )
    assert payload(result) == {"result": "draft_saved"}
    assert operator.commits == 1


def test_windows_setup_has_only_email_and_one_masked_password_field():
    source = (Path(__file__).parents[1] / "scripts" / "enroll_gui.ps1").read_text(
        encoding="utf-8"
    )
    assert "$password.UseSystemPasswordChar = $true" in source
    assert "$showPassword.Checked = $false" in source
    assert "$password.UseSystemPasswordChar = -not $showPassword.Checked" in source
    assert source.count("$password.Clear()") >= 2
    assert "RedirectStandardInput = $true" in source
    assert source.count("New-Object Windows.Forms.TextBox") == 2
    for technical_field in (
        "IMAP username",
        "IMAP server",
        "Confirm IMAP",
        "SMTP username",
        "SMTP server",
        "Confirm SMTP",
        "Trusted auth server",
        "Enable reviewed mailbox actions",
    ):
        assert technical_field not in source


def test_macos_setup_has_the_same_two_field_experience():
    source = (Path(__file__).parents[1] / "scripts" / "setup_macos.py").read_text(
        encoding="utf-8"
    )
    assert 'text="Email address"' in source
    assert 'text="Password"' in source
    assert 'show="*"' in source
    assert "simpledialog" not in source
    for technical_field in (
        "IMAP username",
        "IMAP server",
        "SMTP server",
        "Trusted Authentication-Results",
    ):
        assert technical_field not in source


class BulkBridge:
    profile = "operator"

    def __init__(self):
        self.settings = SimpleNamespace(max_results=20, from_address="mailbox@example.test")
        self.flags = {101: [], 102: ["\\Flagged"]}
        self.calls = []

    def current_state(self, reference):
        return {"message_ref": reference.as_dict(), "flags": list(self.flags[reference.uid])}

    def apply_flag(self, reference, flag, enabled, expected_flags):
        assert list(expected_flags) == self.flags[reference.uid]
        values = set(self.flags[reference.uid])
        values.add(flag) if enabled else values.discard(flag)
        self.flags[reference.uid] = sorted(values)
        self.calls.append((reference.uid, flag, enabled))
        return {"resulting_flags": self.flags[reference.uid]}


def bulk_refs():
    return [
        MessageRef("default", "folder", 10, uid).as_dict()
        for uid in (101, 102)
    ]


def bulk_operator(bridge):
    return MailOperator(bridge, state=object(), sender=object())


def test_bulk_action_exact_list_requires_fresh_one_use_approval():
    bridge = BulkBridge()
    operator = bulk_operator(bridge)
    session = operator.create_ui_session()
    proposal, handle = operator.prepare_bulk_mailbox_action(
        ui_session_id=session, action="mark_read", message_refs=bulk_refs()
    )
    assert len(proposal["targets"]) == 2
    result = operator.commit_bulk_mailbox_action(
        ui_session_id=session,
        approval_handle=handle,
        action="mark_read",
        message_refs=bulk_refs(),
    )
    assert result["completed_count"] == 2
    assert result["failed_count"] == 0
    assert result["permanent_delete_performed"] is False
    assert len(bridge.calls) == 2
    with pytest.raises(ApprovalError):
        operator.commit_bulk_mailbox_action(
            ui_session_id=session,
            approval_handle=handle,
            action="mark_read",
            message_refs=bulk_refs(),
        )


def test_bulk_action_rejects_unreviewed_or_permanent_variants():
    bridge = BulkBridge()
    operator = bulk_operator(bridge)
    session = operator.create_ui_session()
    with pytest.raises(OperatorError, match="unsupported"):
        operator.prepare_bulk_mailbox_action(
            ui_session_id=session, action="expunge", message_refs=bulk_refs()
        )


class FeatureOperator:
    def __init__(self):
        self.saves = 0

    def update_pack_settings(self, **values):
        self.saves += 1
        assert values["setup_confirmed"] is True
        return {"core": True, **{key: values[key] for key in ("phishing", "priority", "cleanup")}}


def test_pack_change_always_crosses_native_review():
    cancelled = FeatureOperator()
    server = build_server(
        profile="operator", bridge=StubBridge(), operator=cancelled, reviewer=lambda *_: False
    )
    result = asyncio.run(
        server.call_tool(
            "review_update_pack_settings",
            {"phishing": True, "priority": False, "cleanup": True},
        )
    )
    assert payload(result)["result"] == "cancelled"
    assert cancelled.saves == 0

    confirmed = FeatureOperator()
    server = build_server(
        profile="operator", bridge=StubBridge(), operator=confirmed, reviewer=lambda *_: True
    )
    result = asyncio.run(
        server.call_tool(
            "review_update_pack_settings",
            {"phishing": True, "priority": False, "cleanup": True},
        )
    )
    assert payload(result)["cleanup"] is True
    assert confirmed.saves == 1


class UnsubscribeBridge:
    profile = "operator"

    def __init__(self):
        self.settings = SimpleNamespace(max_results=20, from_address="mailbox@example.test")

    def current_state(self, reference):
        return {"message_ref": reference.as_dict(), "flags": []}


def test_bulk_unsubscribe_cancellation_contacts_nothing_and_confirmation_runs_once(monkeypatch):
    bridge = UnsubscribeBridge()
    calls = []
    operator = MailOperator(
        bridge,
        state=object(),
        sender=object(),
        unsubscribe_executor=lambda endpoint: calls.append(endpoint) or {"http_status": 204},
    )
    refs = bulk_refs()
    inspections = {
        101: {
            "enabled": True,
            "message_ref": refs[0],
            "one_click_eligible": True,
            "browser_eligible": False,
            "mailto_available": False,
            "endpoint": "https://one.example.test/unsubscribe",
            "endpoint_host": "one.example.test",
            "subscription_digest": "one",
            "display_from": "One <one@example.test>",
            "display_subject": "Offer one",
            "suspicion_label": "no_obvious_indicators",
            "reason": "guarded one-click",
        },
        102: {
            "enabled": True,
            "message_ref": refs[1],
            "one_click_eligible": False,
            "browser_eligible": True,
            "mailto_available": False,
            "endpoint": "https://two.example.test/preferences",
            "endpoint_host": "two.example.test",
            "subscription_digest": "two",
            "display_from": "Two <two@example.test>",
            "display_subject": "Offer two",
            "suspicion_label": "no_obvious_indicators",
            "reason": "guarded browser",
        },
    }
    operator.inspect_cleanup = lambda folder, uid: inspections[uid]
    monkeypatch.setattr("imap_plugin.operator.validate_public_https_url", lambda value: value)

    server = build_server(profile="operator", bridge=bridge, operator=operator, reviewer=lambda *_: False)
    result = asyncio.run(
        server.call_tool("review_bulk_unsubscribe", {"folder": "INBOX", "message_refs": refs})
    )
    assert payload(result)["result"] == "cancelled"
    assert calls == []

    server = build_server(profile="operator", bridge=bridge, operator=operator, reviewer=lambda *_: True)
    result = asyncio.run(
        server.call_tool("review_bulk_unsubscribe", {"folder": "INBOX", "message_refs": refs})
    )
    committed = payload(result)
    assert calls == ["https://one.example.test/unsubscribe"]
    assert committed["browser_required_count"] == 1
    assert committed["retry_performed"] is False
