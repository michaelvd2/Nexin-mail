from __future__ import annotations

import pytest

from imap_plugin.approval import ApprovalError, ApprovalStore
from imap_plugin.contracts import MessageRef


def _ref(uid: int = 41) -> MessageRef:
    return MessageRef("account", "folder", 9, uid)


def test_peek_exposes_exact_nonsecret_snapshot_and_defensive_copies():
    store = ApprovalStore()
    proposal, handle = store.prepare(
        ui_session_id="ui-session-proposal-test",
        action="save_draft",
        targets=(_ref(),),
        before_state={"flags": []},
        payload={"body": "reviewed"},
    )
    snapshot = store.peek(proposal.proposal_id)
    snapshot["payload"]["body"] = "tampered"

    assert "approval_handle" not in snapshot
    assert handle not in str(snapshot)
    assert store.peek(proposal.proposal_id)["payload"]["body"] == "reviewed"


def test_proposal_id_is_one_use_and_expiry_prunes_private_material():
    now = [100.0]
    store = ApprovalStore(ttl_seconds=30, clock=lambda: now[0])
    proposal, _ = store.prepare(
        ui_session_id="ui-session-proposal-test",
        action="flag",
        targets=(_ref(),),
        before_state={"flags": []},
        payload={"enabled": True},
    )
    assert store.pending_count() == 1
    now[0] += 31
    with pytest.raises(ApprovalError):
        store.peek(proposal.proposal_id)
    assert store.pending_count() == 0


def test_invalid_or_foreign_proposal_ids_fail_closed():
    store = ApprovalStore()
    with pytest.raises(ApprovalError):
        store.peek("not-a-proposal")
    proposal, _ = store.prepare(
        ui_session_id="ui-session-proposal-test",
        action="flag",
        targets=(_ref(),),
        before_state={"flags": []},
        payload={"enabled": True},
    )
    other = ApprovalStore()
    with pytest.raises(ApprovalError):
        other.peek(proposal.proposal_id)
