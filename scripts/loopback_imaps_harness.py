"""Loopback-only IMAPS harness preparation.

It binds no socket by default and has no provider or mailbox credentials.  A
native run may use an isolated temporary TLS fixture; this module records the
boundary so a successful preparation is not mistaken for provider proof.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys


def check(bind: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "product": "nexin-mail",
        "harness": "loopback_imaps",
        "endpoint": "127.0.0.1",
        "mailbox": "not_touched",
        "provider": "not_contacted",
        "tls_certificate": "fixture_required",
    }
    if not bind:
        value["status"] = "ready_to_run"
        return value
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            value["port"] = server.getsockname()[1]
    except OSError:
        value["status"] = "blocked"
        return value
    value["status"] = "loopback_bound"
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.bind), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
