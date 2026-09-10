from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from imap_plugin.approval import ApprovalStore
from imap_plugin.contracts import MessageRef
from nexin_mail.server import ACTION_TOOLS, READ_TOOLS, build_server


def _text_payload(result):
    assert result.is_error is False, getattr(result, "content", None)
    text = next(item.text for item in result.content if getattr(item, "type", None) == "text")
    return json.loads(text)


class _Bridge:
    profile = "operator"
    settings = SimpleNamespace(account_id="test-account", from_address="owner@example.test")


class _ReadBridge(_Bridge):
    profile = "read"


class _DraftOperator:
    """Small operator double that keeps the real approval contract in use."""

    def __init__(self):
        self.approvals = ApprovalStore()
        self.sessions = 0
        self.commits = 0
        self._binding = None

    def create_ui_session(self):
        self.sessions += 1
        return f"ui-session-{self.sessions:08d}"

    def prepare_draft(self, *, ui_session_id, to, cc, subject, body, in_reply_to, source_message_ref):
        target = MessageRef("test-account", "folder_drafts", 7, 41)
        payload = {
            "to": to,
            "cc": cc,
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to,
            "source_message_ref": source_message_ref,
        }
        before = {"draft": "not_saved"}
        proposal, handle = self.approvals.prepare(
            ui_session_id=ui_session_id,
            action="save_draft",
            targets=(target,),
            before_state=before,
            payload=payload,
        )
        self._binding = (ui_session_id, target, before, payload)
        return proposal.as_dict(), handle

    def commit_draft(self, *, ui_session_id, approval_handle, to, cc, subject, body, in_reply_to, source_message_ref):
        assert self._binding is not None
        bound_session, target, before, payload = self._binding
        self.approvals.consume(
            handle=approval_handle,
            ui_session_id=ui_session_id,
            action="save_draft",
            targets=(target,),
            before_state=before,
            payload={
                "to": to,
                "cc": cc,
                "subject": subject,
                "body": body,
                "in_reply_to": in_reply_to,
                "source_message_ref": source_message_ref,
            },
        )
        assert ui_session_id == bound_session
        self.commits += 1
        return {"result": "draft_saved", "sent": False}


class _SettingsOperator(_DraftOperator):
    def __init__(self):
        super().__init__()
        self.packs = {"core": True, "phishing": False, "priority": False, "cleanup": False}
        self.rules = {"important_senders": [], "high_keywords": [], "low_keywords": []}
        self.settings_writes = 0

    def get_pack_settings(self):
        return dict(self.packs)

    def update_pack_settings(self, *, phishing, priority, cleanup, setup_confirmed):
        assert setup_confirmed is True
        self.settings_writes += 1
        self.packs.update(phishing=phishing, priority=priority, cleanup=cleanup)
        return dict(self.packs)

    def get_priority_rules(self):
        return {key: list(values) for key, values in self.rules.items()}

    def set_priority_rules(self, rules, confirmed):
        assert confirmed is True
        self.settings_writes += 1
        self.rules = {key: list(values) for key, values in rules.items()}
        return self.get_priority_rules()


class _BrowserOperator(_DraftOperator):
    def __init__(self):
        super().__init__()
        self.outcomes = []
        self.batch = {
            "batch_id": "browser-batch-0001",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "rules": ["Open only the exact endpoint."],
            "tasks": [{
                "task_id": "browser-task-0001",
                "message_ref": {"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41},
                "display_from": "List <list@example.test>",
                "display_subject": "Offer",
                "endpoint": "https://example.test/unsubscribe?id=1",
                "endpoint_host": "example.test",
            }],
        }

    def get_confirmed_browser_unsubscribe_batch(self, batch_id):
        assert batch_id == self.batch["batch_id"]
        return self.batch

    def record_browser_unsubscribe_result(self, *, batch_id, task_id, outcome, note=""):
        self.outcomes.append((batch_id, task_id, outcome, note))
        return {"kind": "browser_unsubscribe_progress", "outcome": outcome, "no_message_changes": True}


class _ActionOperator:
    """Generic operator double for exercising every unified commit gate."""

    def __init__(self):
        self.approvals = ApprovalStore()
        self.sessions = 0
        self.commits = []
        self._pending = {}

    def create_ui_session(self):
        self.sessions += 1
        return f"ui-session-{self.sessions:08d}"

    def _save(self, *, ui_session_id, action, payload, count=1):
        targets = tuple(MessageRef("test-account", "folder", 9, uid) for uid in range(41, 41 + count))
        before = {"state": "unchanged", "count": count}
        proposal, handle = self.approvals.prepare(
            ui_session_id=ui_session_id,
            action=action,
            targets=targets,
            before_state=before,
            payload=payload,
        )
        self._pending[handle] = (ui_session_id, action, targets, before, payload)
        return proposal.as_dict(), handle

    def __getattr__(self, name):
        if name.startswith("prepare_"):
            def prepare(**kwargs):
                session = kwargs["ui_session_id"]
                if name == "prepare_mailbox_action":
                    action = kwargs["action"]
                    payload = {"action": action, "destination_folder_id": kwargs.get("destination_folder_id"), "restore_receipt": kwargs.get("restore_receipt")}
                    return self._save(ui_session_id=session, action=action, payload=payload)
                if name == "prepare_bulk_mailbox_action":
                    action = f"bulk_{kwargs['action']}"
                    payload = {"action": kwargs["action"], "count": len(kwargs["message_refs"]), "destination_folder_id": kwargs.get("destination_folder_id")}
                    return self._save(ui_session_id=session, action=action, payload=payload, count=max(1, len(kwargs["message_refs"])))
                if name == "prepare_draft":
                    payload = {key: kwargs.get(key) for key in ("to", "cc", "subject", "body", "in_reply_to", "source_message_ref")}
                    return self._save(ui_session_id=session, action="save_draft", payload=payload)
                if name == "prepare_send":
                    payload = {"draft_message_ref": kwargs["draft_message_ref"], "message_id": "message-id", "digest": "digest"}
                    proposal, handle = self._save(ui_session_id=session, action="send", payload=payload)
                    return {"proposal": proposal, "preview": {"message_id": "message-id", "digest": "digest"}}, handle
                if name == "prepare_unsubscribe":
                    proposal, handle = self._save(ui_session_id=session, action="unsubscribe", payload={"endpoint": "https://example.test/unsubscribe"})
                    return {**proposal, "endpoint": "https://example.test/unsubscribe"}, handle
                if name == "prepare_bulk_unsubscribe":
                    payload = {"count": len(kwargs["message_refs"])}
                    return self._save(ui_session_id=session, action="bulk_unsubscribe", payload=payload, count=max(1, len(kwargs["message_refs"])))
                if name == "prepare_remote_images":
                    payload = {"folder": kwargs["folder"], "uid": kwargs["uid"], "message_ref": kwargs["message_ref"]}
                    proposal, handle = self._save(ui_session_id=session, action="load_remote_images", payload=payload)
                    return {**proposal, "remote_images": {"count": 1, "hosts": ["example.test"], "blocked_count": 0}}, handle
                if name == "prepare_attachment_download":
                    payload = {"folder": kwargs["folder"], "message_ref": kwargs["message_ref"], "part_id": kwargs["part_id"]}
                    proposal, handle = self._save(ui_session_id=session, action="download_attachment", payload=payload)
                    return {**proposal, "attachment": {"part_id": kwargs["part_id"], "name": "report.pdf", "mime_type": "application/pdf"}}, handle
                raise AssertionError(f"unsupported prepare method: {name}")
            return prepare
        if name == "undo_mailbox_action" or name.startswith("commit_"):
            def commit(**kwargs):
                handle = kwargs["approval_handle"]
                session, action, targets, before, payload = self._pending.pop(handle)
                self.approvals.consume(
                    handle=handle,
                    ui_session_id=session,
                    action=action,
                    targets=targets,
                    before_state=before,
                    payload=payload,
                )
                self.commits.append(name)
                return {"result": name}
            return commit
        raise AttributeError(name)


def _draft_args():
    return {
        "ui_session_id": "ui-session-existing",
        "to": "recipient@example.test",
        "cc": "",
        "subject": "A reviewed subject",
        "body": "A reviewed body",
        "in_reply_to": "",
        "source_message_ref": None,
    }


def test_unified_entrypoint_has_one_unique_registry_and_no_approval_handle_wire_field(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAP_PLUGIN_CONFIG", str(tmp_path / "missing.toml"))
    server = build_server()
    assert server._lowlevel_server.name == "nexin-mail"
    assert server._lowlevel_server.title is None
    tools = asyncio.run(server.list_tools())
    names = [tool.name for tool in tools]

    assert len(names) == len(set(names))
    assert set(names) == set(READ_TOOLS + ACTION_TOOLS)
    assert len(READ_TOOLS) == len(set(READ_TOOLS))
    assert len(ACTION_TOOLS) == len(set(ACTION_TOOLS))
    for tool in tools:
        schema = json.dumps(tool.input_schema, ensure_ascii=False)
        assert "approval_handle" not in schema


def test_unconfigured_runtime_exposes_status_dashboard_and_onboarding_without_mailbox_load(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAP_PLUGIN_CONFIG", str(tmp_path / "missing.toml"))
    server = build_server()

    status = _text_payload(asyncio.run(server.call_tool("setup_status", {})))
    assert status["configured"] is False
    assert status["profile"] == "unconfigured"
    assert status["credentials"] == {"imap": False, "smtp": False}
    assert status["onboarding"]["required"] is True
    assert "microsoft_browser_oauth" in status["onboarding"]["methods"]
    assert "account_id" not in status
    assert "from_address" not in status

    rendered = _text_payload(asyncio.run(server.call_tool("render_mail_view", {})))
    assert rendered["configured"] is False
    assert rendered["profile"] == "unconfigured"
    assert rendered["ui_session_id"]

    bootstrap = _text_payload(asyncio.run(server.call_tool("mail_view_bootstrap", {"folder": "INBOX", "limit": 999})))
    assert bootstrap["configured"] is False
    assert bootstrap["mailboxes"] == []
    assert bootstrap["messages"] == []
    assert bootstrap["limit"] == 20

    health = _text_payload(asyncio.run(server.call_tool("mail_health", {})))
    assert health["configured"] is False
    assert health["operator_features"]["send_configured"] is False
    assert _text_payload(asyncio.run(server.call_tool("get_pack_settings", {})))["setup_completed"] is False
    assert _text_payload(asyncio.run(server.call_tool("get_priority_rules", {}))) == {
        "important_senders": [], "high_keywords": [], "low_keywords": [],
    }


def test_malformed_config_keeps_render_onboarding_available(monkeypatch, tmp_path):
    config = tmp_path / "malformed.toml"
    config.write_text("[unexpected]\nvalue = true\n", encoding="utf-8")
    monkeypatch.setenv("IMAP_PLUGIN_CONFIG", str(config))

    def malformed_settings():
        raise KeyError("unexpected configuration shape")

    monkeypatch.setattr("imap_dashboard.server.load_settings", malformed_settings)
    server = build_server()

    rendered = _text_payload(asyncio.run(server.call_tool("render_mail_view", {})))
    assert rendered["configured"] is False
    assert rendered["profile"] == "invalid"
    assert rendered["onboarding"]["required"] is True


def test_prepare_result_and_native_review_never_export_private_handle():
    operator = _DraftOperator()
    seen = []

    def reviewer(title, payload, require_checkbox):
        seen.append((title, payload, require_checkbox))
        return True

    server = build_server(bridge=_Bridge(), operator=operator, reviewer=reviewer)
    args = _draft_args()
    prepared = asyncio.run(server.call_tool("prepare_draft", args))
    public = _text_payload(prepared)
    serialized = json.dumps(prepared.model_dump(), ensure_ascii=False)
    assert "approval_handle" not in serialized
    assert "private" not in serialized
    assert public["proposal_id"]

    commit = asyncio.run(server.call_tool("commit_draft", {**args, "proposal_id": public["proposal_id"]}))
    assert _text_payload(commit) == {"result": "draft_saved", "sent": False}
    assert operator.commits == 1
    assert seen[0][2] is False
    review = seen[0][1]["proposal"]
    assert review["proposal_id"] == public["proposal_id"]
    assert review["payload"]["body"] == args["body"]
    assert "approval_handle" not in json.dumps(seen[0][1], ensure_ascii=False)

    with pytest.raises(Exception):
        asyncio.run(server.call_tool("commit_draft", {**args, "proposal_id": public["proposal_id"]}))
    assert operator.commits == 1


def test_native_cancel_does_not_commit_or_export_handle():
    operator = _DraftOperator()
    server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda *_: False)
    args = _draft_args()
    prepared = asyncio.run(server.call_tool("prepare_draft", args))
    public = _text_payload(prepared)
    result = asyncio.run(server.call_tool("commit_draft", {**args, "proposal_id": public["proposal_id"]}))

    assert _text_payload(result)["result"] == "cancelled"
    assert operator.commits == 0


_DIRECT_COMMIT_CASES = (
    (
        "mailbox",
        "prepare_mailbox_action",
        "commit_mailbox_action",
        {
            "ui_session_id": "ui-session-existing",
            "action": "move_junk",
            "message_ref": {"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41},
            "destination_folder_id": "folder_junk",
            "restore_receipt": None,
        },
        {},
    ),
    (
        "bulk mailbox",
        "prepare_bulk_mailbox_action",
        "commit_bulk_mailbox_action",
        {
            "ui_session_id": "ui-session-existing",
            "action": "move_bin",
            "message_refs": [{"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41}],
        },
        {"destination_folder_id": "folder_bin"},
    ),
    (
        "draft",
        "prepare_draft",
        "commit_draft",
        _draft_args(),
        {},
    ),
    (
        "send",
        "prepare_send",
        "commit_send",
        {"ui_session_id": "ui-session-existing", "draft_message_ref": {"account_id": "test-account", "folder_id": "drafts", "uidvalidity": 9, "uid": 12}},
        {"message_id": "message-id", "digest": "digest", "reviewed_recipients_and_message": True},
    ),
    (
        "unsubscribe",
        "prepare_unsubscribe",
        "commit_unsubscribe",
        {"ui_session_id": "ui-session-existing", "folder": "INBOX", "uid": 41},
        {"endpoint": "https://example.test/unsubscribe"},
    ),
    (
        "bulk unsubscribe",
        "prepare_bulk_unsubscribe",
        "commit_bulk_unsubscribe",
        {
            "ui_session_id": "ui-session-existing",
            "folder": "INBOX",
            "message_refs": [{"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41}],
        },
        {},
    ),
    (
        "remote images",
        "prepare_remote_images",
        "commit_remote_images",
        {"ui_session_id": "ui-session-existing", "folder": "INBOX", "uid": 41, "message_ref": {"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41}},
        {},
    ),
    (
        "attachment",
        "prepare_attachment_download",
        "commit_attachment_download",
        {"ui_session_id": "ui-session-existing", "folder": "INBOX", "message_ref": {"account_id": "test-account", "folder_id": "folder", "uidvalidity": 9, "uid": 41}, "part_id": "2"},
        {},
    ),
)


@pytest.mark.parametrize("label,prepare_name,commit_name,prepare_args,commit_extra", _DIRECT_COMMIT_CASES, ids=lambda case: case[0] if isinstance(case, tuple) else str(case))
def test_native_cancel_and_approve_bind_every_direct_commit_class(label, prepare_name, commit_name, prepare_args, commit_extra):
    del label
    operator = _ActionOperator()
    seen = []
    cancelled_server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda title, payload, checkbox: seen.append(payload) or False)
    prepared = _text_payload(asyncio.run(cancelled_server.call_tool(prepare_name, prepare_args)))
    proposal = prepared.get("proposal", prepared)
    proposal_id = proposal["proposal_id"]
    cancelled = asyncio.run(cancelled_server.call_tool(commit_name, {**prepare_args, **commit_extra, "proposal_id": proposal_id}))
    assert _text_payload(cancelled)["result"] == "cancelled"
    assert operator.commits == []
    assert seen[0]["proposal"]["proposal_id"] == proposal_id
    assert "approval_handle" not in json.dumps(seen[0], ensure_ascii=False)

    operator = _ActionOperator()
    approved_server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda title, payload, checkbox: True)
    prepared = _text_payload(asyncio.run(approved_server.call_tool(prepare_name, prepare_args)))
    proposal = prepared.get("proposal", prepared)
    approved = asyncio.run(approved_server.call_tool(commit_name, {**prepare_args, **commit_extra, "proposal_id": proposal["proposal_id"]}))
    assert _text_payload(approved)["result"] == commit_name
    assert operator.commits == [commit_name]


def test_native_gate_covers_restore_commit_class():
    operator = _ActionOperator()
    session = operator.create_ui_session()
    proposal, _ = operator._save(
        ui_session_id=session,
        action="restore",
        payload={"restore_receipt": "receipt-1", "destination_folder_id": "folder"},
    )
    server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda *_: False)
    result = asyncio.run(server.call_tool(
        "undo_mailbox_action",
        {"ui_session_id": session, "proposal_id": proposal["proposal_id"], "restore_receipt": "receipt-1", "destination_folder_id": "folder"},
    ))
    assert _text_payload(result)["result"] == "cancelled"
    assert operator.commits == []

    operator = _ActionOperator()
    session = operator.create_ui_session()
    proposal, _ = operator._save(
        ui_session_id=session,
        action="restore",
        payload={"restore_receipt": "receipt-2", "destination_folder_id": "folder"},
    )
    server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda *_: True)
    result = asyncio.run(server.call_tool(
        "undo_mailbox_action",
        {"ui_session_id": session, "proposal_id": proposal["proposal_id"], "restore_receipt": "receipt-2", "destination_folder_id": "folder"},
    ))
    assert _text_payload(result)["result"] == "undo_mailbox_action"
    assert operator.commits == ["undo_mailbox_action"]


def test_read_profile_denies_prepare_and_settings_writes():
    operator = _DraftOperator()
    server = build_server(bridge=_ReadBridge(), operator=operator, reviewer=lambda *_: True)

    with pytest.raises(Exception):
        asyncio.run(server.call_tool("prepare_draft", _draft_args()))
    with pytest.raises(Exception):
        asyncio.run(server.call_tool(
            "update_pack_settings",
            {"phishing": True, "priority": False, "cleanup": False, "setup_confirmed": True},
        ))

    restricted = build_server(profile="read", bridge=_Bridge(), operator=_DraftOperator(), reviewer=lambda *_: True)
    with pytest.raises(Exception):
        asyncio.run(restricted.call_tool("prepare_draft", _draft_args()))


def test_unified_settings_use_the_same_native_proposal_gate():
    operator = _SettingsOperator()
    reviews = []
    server = build_server(
        bridge=_Bridge(), operator=operator,
        reviewer=lambda title, payload, checkbox: reviews.append(payload) or False,
    )
    cancelled = asyncio.run(server.call_tool(
        "update_pack_settings",
        {"phishing": True, "priority": False, "cleanup": True, "setup_confirmed": True},
    ))
    assert _text_payload(cancelled)["status"] == "cancelled"
    assert operator.settings_writes == 0
    assert reviews[0]["kind"] == "native_commit"
    assert reviews[0]["proposal"]["action"] == "update_pack_settings"
    assert "approval_handle" not in json.dumps(reviews[0], ensure_ascii=False)

    operator = _SettingsOperator()
    server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda *_: True)
    saved = asyncio.run(server.call_tool(
        "review_set_priority_rules",
        {"rules": {"important_senders": ["owner@example.test"], "high_keywords": [], "low_keywords": []}},
    ))
    assert _text_payload(saved)["important_senders"] == ["owner@example.test"]
    assert operator.settings_writes == 1


def test_browser_task_and_terminal_result_share_native_proposal_gate():
    operator = _BrowserOperator()
    server = build_server(bridge=_Bridge(), operator=operator, reviewer=lambda *_: True)
    task = asyncio.run(server.call_tool(
        "review_browser_unsubscribe_task",
        {"batch_id": operator.batch["batch_id"], "task_id": operator.batch["tasks"][0]["task_id"]},
    ))
    assert _text_payload(task)["result"] == "confirmed"

    result = asyncio.run(server.call_tool(
        "review_record_browser_unsubscribe_result",
        {
            "batch_id": operator.batch["batch_id"],
            "task_id": operator.batch["tasks"][0]["task_id"],
            "outcome": "confirmed",
            "note": "done",
        },
    ))
    assert _text_payload(result)["outcome"] == "confirmed"
    assert operator.outcomes == [(operator.batch["batch_id"], operator.batch["tasks"][0]["task_id"], "confirmed", "done")]


def test_mutated_commit_arguments_fail_after_native_review_of_original_binding():
    operator = _DraftOperator()
    seen = []
    server = build_server(
        bridge=_Bridge(), operator=operator,
        reviewer=lambda title, payload, checkbox: seen.append(payload) or True,
    )
    args = _draft_args()
    public = _text_payload(asyncio.run(server.call_tool("prepare_draft", args)))
    mutated = {**args, "proposal_id": public["proposal_id"], "body": "tampered after review"}
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("commit_draft", mutated))
    assert operator.commits == 0
    assert seen[0]["proposal"]["payload"]["body"] == args["body"]
