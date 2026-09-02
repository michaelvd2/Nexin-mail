from __future__ import annotations

import pytest

from imap_plugin.approval import ApprovalError, ApprovalStore
from imap_plugin.contracts import ContextBundle, ContextSource, MessageRef


def ref(uid: int = 7) -> MessageRef:
    return MessageRef("default", "folder_abc", 11, uid)


def test_approval_is_one_use_and_bound_to_exact_payload():
    store = ApprovalStore(ttl_seconds=300)
    proposal, handle = store.prepare(
        ui_session_id="ui-session-123456",
        action="move_bin",
        targets=(ref(),),
        before_state={"flags": []},
        payload={"destination": "trash"},
    )
    assert handle not in str(proposal.as_dict())
    store.consume(
        handle=handle,
        ui_session_id="ui-session-123456",
        action="move_bin",
        targets=(ref(),),
        before_state={"flags": []},
        payload={"destination": "trash"},
    )
    with pytest.raises(ApprovalError):
        store.consume(
            handle=handle,
            ui_session_id="ui-session-123456",
            action="move_bin",
            targets=(ref(),),
            before_state={"flags": []},
            payload={"destination": "trash"},
        )


def test_mismatch_invalidates_handle():
    store = ApprovalStore(ttl_seconds=300)
    _, handle = store.prepare(
        ui_session_id="ui-session-123456",
        action="send",
        targets=(ref(),),
        before_state={"flags": ["\\Draft"]},
        payload={"body": "reviewed"},
    )
    with pytest.raises(ApprovalError):
        store.consume(
            handle=handle,
            ui_session_id="ui-session-123456",
            action="send",
            targets=(ref(),),
            before_state={"flags": ["\\Draft"]},
            payload={"body": "changed"},
        )
    with pytest.raises(ApprovalError):
        store.consume(
            handle=handle,
            ui_session_id="ui-session-123456",
            action="send",
            targets=(ref(),),
            before_state={"flags": ["\\Draft"]},
            payload={"body": "reviewed"},
        )


def test_expired_handle_fails_closed():
    now = [1000.0]
    store = ApprovalStore(ttl_seconds=30, clock=lambda: now[0])
    _, handle = store.prepare(
        ui_session_id="ui-session-123456",
        action="flag",
        targets=(ref(),),
        before_state={"flags": []},
        payload={"enabled": True},
    )
    now[0] += 31
    with pytest.raises(ApprovalError):
        store.consume(
            handle=handle,
            ui_session_id="ui-session-123456",
            action="flag",
            targets=(ref(),),
            before_state={"flags": []},
            payload={"enabled": True},
        )


def test_context_is_hard_limited_to_five_related_messages():
    with pytest.raises(ValueError):
        ContextBundle(
            current_message=ref(),
            thread=(ref(),),
            related=tuple(ContextSource(ref(uid), "same sender") for uid in range(1, 7)),
        )
