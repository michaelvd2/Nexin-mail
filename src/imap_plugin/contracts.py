from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_digest(value: Any) -> str:
    """Return a stable digest without retaining the source values."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MessageRef:
    account_id: str
    folder_id: str
    uidvalidity: int
    uid: int

    def __post_init__(self) -> None:
        if not self.account_id or len(self.account_id) > 64:
            raise ValueError("account_id is required and must be at most 64 characters")
        if not self.folder_id or len(self.folder_id) > 128:
            raise ValueError("folder_id is required and must be at most 128 characters")
        if self.uidvalidity <= 0 or self.uid <= 0:
            raise ValueError("uidvalidity and uid must be positive")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MessageRef":
        return cls(
            account_id=str(value["account_id"]),
            folder_id=str(value["folder_id"]),
            uidvalidity=int(value["uidvalidity"]),
            uid=int(value["uid"]),
        )


@dataclass(frozen=True)
class ContextSource:
    message_ref: MessageRef
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"message_ref": self.message_ref.as_dict(), "reason": self.reason}


@dataclass(frozen=True)
class ContextBundle:
    current_message: MessageRef
    thread: tuple[MessageRef, ...]
    related: tuple[ContextSource, ...]
    scope_days: int = 31
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if len(self.related) > 5:
            raise ValueError("context is limited to five related messages")
        if not 1 <= self.scope_days <= 31:
            raise ValueError("context scope must be 1..31 days")

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_message": self.current_message.as_dict(),
            "thread": [item.as_dict() for item in self.thread],
            "related": [item.as_dict() for item in self.related],
            "scope_days": self.scope_days,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Classification:
    message_ref: MessageRef
    label: str
    reason_codes: tuple[str, ...]
    explanation: str
    version: str
    timestamp: str = field(default_factory=utc_now)
    advisory: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_ref": self.message_ref.as_dict(),
            "label": self.label,
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
            "version": self.version,
            "timestamp": self.timestamp,
            "advisory": self.advisory,
        }


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    action: str
    targets: tuple[MessageRef, ...]
    before_state: Mapping[str, Any]
    digest: str
    expires_at: str
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "action": self.action,
            "targets": [item.as_dict() for item in self.targets],
            "before_state": dict(self.before_state),
            "digest": self.digest,
            "expires_at": self.expires_at,
            "warnings": list(self.warnings),
            "approval_required": True,
        }


@dataclass(frozen=True)
class ActionReceipt:
    action: str
    targets: tuple[MessageRef, ...]
    before_state: Mapping[str, Any]
    after_state: Mapping[str, Any]
    result: str
    correlation_id: str
    restore_available: bool
    timestamp: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "targets": [item.as_dict() for item in self.targets],
            "before_state": dict(self.before_state),
            "after_state": dict(self.after_state),
            "result": self.result,
            "correlation_id": self.correlation_id,
            "restore_available": self.restore_available,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class SendPreview:
    from_address: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    body: str
    message_id: str
    digest: str
    expires_at: str
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_address,
            "to": list(self.to),
            "cc": list(self.cc),
            "subject": self.subject,
            "body": self.body,
            "message_id": self.message_id,
            "digest": self.digest,
            "expires_at": self.expires_at,
            "warnings": list(self.warnings),
            "requires_review_checkbox": True,
        }
