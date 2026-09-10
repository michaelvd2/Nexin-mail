"""Verify the local Nexin Mail protocol surface without opening a mailbox.

This check is intentionally source/runtime evidence only. It builds the MCP
registry, validates the single server identity and wire contracts, and probes
the no-config onboarding path in a temporary config location. It does not
install, register, connect to IMAP/SMTP, open setup, or inspect live mail.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

from nexin_mail.server import ACTION_TOOLS, READ_TOOLS, build_server


FORBIDDEN = {
    "bulk_send",
    "delete",
    "empty_bin",
    "expunge",
    "load_remote_images",
    "permanent_delete",
    "raw_imap",
    "unsubscribe",
}


def _tool_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "input_schema", None)
    return schema if isinstance(schema, dict) else {}


async def _verify() -> dict[str, Any]:
    server = build_server()
    lowlevel = server._lowlevel_server
    if lowlevel.name != "nexin-mail" or lowlevel.title is not None:
        raise RuntimeError("unexpected Nexin Mail server identity")

    tools = await server.list_tools()
    names = [tool.name for tool in tools]
    expected = set(READ_TOOLS + ACTION_TOOLS)
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate MCP tool names are exposed")
    if set(names) != expected:
        raise RuntimeError(
            f"unexpected MCP surface: missing={sorted(expected - set(names))!r} extra={sorted(set(names) - expected)!r}"
        )
    forbidden = set(names) & FORBIDDEN
    if forbidden:
        raise RuntimeError(f"forbidden MCP tools are exposed: {sorted(forbidden)!r}")

    by_name = {tool.name: tool for tool in tools}
    for name, tool in by_name.items():
        schema_text = json.dumps(_tool_schema(tool), ensure_ascii=False)
        if "approval_handle" in schema_text:
            raise RuntimeError(f"private approval material is present in {name} schema")
    for name in (
        "commit_mailbox_action", "commit_bulk_mailbox_action", "undo_mailbox_action",
        "commit_draft", "commit_send", "commit_unsubscribe", "commit_bulk_unsubscribe",
        "commit_remote_images", "commit_attachment_download",
    ):
        if name not in by_name or "proposal_id" not in _tool_schema(by_name[name]).get("properties", {}):
            raise RuntimeError(f"{name} has no proposal-id commit contract")

    with tempfile.TemporaryDirectory(prefix="nexin-mail-verify-") as temporary:
        previous = os.environ.get("IMAP_PLUGIN_CONFIG")
        os.environ["IMAP_PLUGIN_CONFIG"] = str(Path(temporary).resolve() / "missing.toml")
        try:
            probe = build_server()
            status = await probe.call_tool("setup_status", {})
            rendered = await probe.call_tool("render_mail_view", {})
            bootstrap = await probe.call_tool("mail_view_bootstrap", {"folder": "INBOX", "limit": 20})
            for label, result in (("setup_status", status), ("render_mail_view", rendered), ("mail_view_bootstrap", bootstrap)):
                if result.is_error:
                    raise RuntimeError(f"unconfigured {label} probe failed")
            status_value = getattr(status, "structured_content", None) or json.loads(status.content[0].text)
            rendered_value = getattr(rendered, "structured_content", None) or json.loads(rendered.content[0].text)
            bootstrap_value = getattr(bootstrap, "structured_content", None) or json.loads(bootstrap.content[0].text)
            if status_value.get("configured") is not False or rendered_value.get("configured") is not False or bootstrap_value.get("configured") is not False:
                raise RuntimeError("unconfigured probes did not remain unconfigured")
        finally:
            if previous is None:
                os.environ.pop("IMAP_PLUGIN_CONFIG", None)
            else:
                os.environ["IMAP_PLUGIN_CONFIG"] = previous

    return {
        "status": "pass",
        "server": lowlevel.name,
        "python": platform.python_version(),
        "executable": sys.executable,
        "tools": len(names),
        "unconfigured_onboarding": "verified",
        "forbidden_exposed": [],
    }


def main() -> int:
    try:
        result = asyncio.run(_verify())
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
