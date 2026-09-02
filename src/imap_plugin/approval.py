from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from .contracts import ActionProposal, MessageRef, canonical_digest


class ApprovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApprovalBinding:
    ui_session_id: str
    action: str
    targets: tuple[MessageRef, ...]
    before_state: Mapping[str, Any]
    payload_digest: str
    proposal_digest: str
    expires_at_epoch: float


class ApprovalStore:
    """Memory-only, one-use approvals that are never returned to the model."""

    def __init__(
        self,
        ttl_seconds: int = 300,
        max_pending: int = 100,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 30 <= ttl_seconds <= 300:
            raise ValueError("approval TTL must be 30..300 seconds")
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self.clock = clock
        self._pending: dict[str, ApprovalBinding] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _validate_session(ui_session_id: str) -> str:
        if not 16 <= len(ui_session_id) <= 128:
            raise ApprovalError("a compatible Codex mail UI session is required")
        if any(ord(char) < 33 or ord(char) > 126 for char in ui_session_id):
            raise ApprovalError("invalid UI session identifier")
        return ui_session_id

    @staticmethod
    def _handle_key(handle: str) -> str:
        return hashlib.sha256(handle.encode("ascii", "strict")).hexdigest()

    def _prune(self, now: float) -> None:
        expired = [key for key, binding in self._pending.items() if binding.expires_at_epoch <= now]
        for key in expired:
            self._pending.pop(key, None)

    def prepare(
        self,
        *,
        ui_session_id: str,
        action: str,
        targets: Iterable[MessageRef],
        before_state: Mapping[str, Any],
        payload: Mapping[str, Any],
        warnings: Iterable[str] = (),
    ) -> tuple[ActionProposal, str]:
        session = self._validate_session(ui_session_id)
        target_tuple = tuple(targets)
        if not action:
            raise ApprovalError("action is required")
        now = self.clock()
        expires = now + self.ttl_seconds
        payload_digest = canonical_digest(payload)
        proposal_data = {
            "ui_session_id": session,
            "action": action,
            "targets": [item.as_dict() for item in target_tuple],
            "before_state": dict(before_state),
            "payload_digest": payload_digest,
            "expires_at_epoch": int(expires),
        }
        proposal_digest = canonical_digest(proposal_data)
        handle = secrets.token_urlsafe(32)
        key = self._handle_key(handle)
        binding = ApprovalBinding(
            ui_session_id=session,
            action=action,
            targets=target_tuple,
            before_state=dict(before_state),
            payload_digest=payload_digest,
            proposal_digest=proposal_digest,
            expires_at_epoch=expires,
        )
        with self._lock:
            self._prune(now)
            if len(self._pending) >= self.max_pending:
                raise ApprovalError("too many pending approvals; close older review dialogs")
            self._pending[key] = binding
        proposal = ActionProposal(
            proposal_id=secrets.token_hex(8),
            action=action,
            targets=target_tuple,
            before_state=dict(before_state),
            digest=proposal_digest,
            expires_at=datetime.fromtimestamp(expires, timezone.utc).isoformat(),
            warnings=tuple(warnings),
        )
        return proposal, handle

    def consume(
        self,
        *,
        handle: str,
        ui_session_id: str,
        action: str,
        targets: Iterable[MessageRef],
        before_state: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> ApprovalBinding:
        self._validate_session(ui_session_id)
        if not handle or len(handle) > 256:
            raise ApprovalError("approval handle is missing or invalid")
        try:
            key = self._handle_key(handle)
        except UnicodeEncodeError as exc:
            raise ApprovalError("approval handle is invalid") from exc
        now = self.clock()
        with self._lock:
            self._prune(now)
            binding = self._pending.pop(key, None)
        if binding is None:
            raise ApprovalError("approval expired, was already used, or is not valid in this process")
        if binding.expires_at_epoch <= now:
            raise ApprovalError("approval expired")
        supplied_targets = tuple(targets)
        checks = (
            hmac.compare_digest(binding.ui_session_id, ui_session_id),
            hmac.compare_digest(binding.action, action),
            binding.targets == supplied_targets,
            canonical_digest(binding.before_state) == canonical_digest(dict(before_state)),
            hmac.compare_digest(binding.payload_digest, canonical_digest(payload)),
        )
        if not all(checks):
            raise ApprovalError("approval no longer matches the reviewed action")
        return binding

    def pending_count(self) -> int:
        now = self.clock()
        with self._lock:
            self._prune(now)
            return len(self._pending)
