"""Single Nexin Mail MCP entrypoint.

The dashboard implementation is a presentation adapter; this module is the
only package entrypoint registered by Nexin Mail.  ``build_server`` creates one
MCP server with one lazy MailBridge/MailOperator/ApprovalStore runtime and one
native review boundary for all consequential commits.
"""
from __future__ import annotations

from typing import Any

from imap_dashboard.server import (
    OPERATOR_TOOLS as DASHBOARD_OPERATOR_TOOLS,
    READ_TOOLS as DASHBOARD_READ_TOOLS,
    UI_RESOURCE_URI,
    build_server as _build_dashboard_server,
)
from imap_plugin.bridge import MailBridge
from imap_plugin.operator import MailOperator
from imap_plugin.review import Reviewer

from . import __version__


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for name in group:
            if name not in seen:
                seen.add(name)
                result.append(name)
    return tuple(result)


# Public protocol constants are intentionally derived from one registration
# source.  They are also consumed by the local verifier and protocol tests.
READ_TOOLS = _unique(
    ("setup_status", "wait_setup"),
    tuple(name for name in DASHBOARD_READ_TOOLS if name not in {"update_pack_settings", "set_priority_rules"}),
)
ACTION_TOOLS = _unique(
    ("open_setup",),
    DASHBOARD_OPERATOR_TOOLS,
    ("update_pack_settings", "set_priority_rules"),
    (
        "review_mailbox_action",
        "review_bulk_mailbox_action",
        "review_save_draft",
        "review_send_draft",
        "review_attachment_download",
        "review_update_pack_settings",
        "review_set_priority_rules",
        "review_unsubscribe",
        "review_bulk_unsubscribe",
        "review_browser_unsubscribe_task",
        "review_record_browser_unsubscribe_result",
    ),
)
WRITE_TOOLS = ACTION_TOOLS


def build_server(
    profile: str | None = None,
    bridge: MailBridge | None = None,
    operator: MailOperator | None = None,
    reviewer: Reviewer | None = None,
) -> Any:
    """Build the unified lazy server without loading a mailbox at import time."""
    return _build_dashboard_server(
        profile=profile,
        bridge=bridge,
        operator=operator,
        reviewer=reviewer,
        unified=True,
        version=__version__,
    )


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
