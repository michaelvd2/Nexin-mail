from __future__ import annotations

import asyncio
import json
import platform
import sys

from imap_plugin.server import ACTION_TOOLS, READ_TOOLS, build_server


FORBIDDEN = {
    "bulk_send",
    "delete",
    "empty_bin",
    "expunge",
    "load_remote_images",
    "permanent_delete",
    "raw_imap",
    "render_mail_view",
    "unsubscribe",
}


def main() -> int:
    server = build_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    expected = set(READ_TOOLS + ACTION_TOOLS)
    if names != expected:
        raise RuntimeError(
            f"unexpected MCP surface: missing={sorted(expected - names)!r} extra={sorted(names - expected)!r}"
        )
    if names & FORBIDDEN:
        raise RuntimeError(f"forbidden MCP tools are exposed: {sorted(names & FORBIDDEN)!r}")
    if any(name != "open_setup" and not name.startswith("review_") for name in ACTION_TOOLS):
        raise RuntimeError("a consequential tool is exposed without the native review_* boundary")
    print(
        json.dumps(
            {
                "status": "pass",
                "python": platform.python_version(),
                "executable": sys.executable,
                "tools": sorted(names),
                "forbidden_exposed": [],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
