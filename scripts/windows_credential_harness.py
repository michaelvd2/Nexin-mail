"""Run a synthetic Credential Manager chunk round-trip on Windows.

Use ``--run-native`` only in an isolated Windows profile.  The generated
target is unique and cleanup is attempted for every target written by this
run.  No customer credential or target is accepted as an argument.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys


def run_native() -> dict[str, object]:
    if os.name != "nt":
        return {"status": "unsupported_platform", "store": "Windows Credential Manager"}
    from imap_plugin.credentials import ChunkedSecretStore, platform_store

    target = "nexin-mail/native-harness/" + secrets.token_hex(12)
    backend = platform_store()
    store = ChunkedSecretStore(backend, target)
    payload = "synthetic-credential-fixture-" + ("x" * 9000)
    # Pin the generation only inside this short-lived harness process so a
    # failure before the pointer is written still leaves a bounded cleanup set.
    import imap_plugin.credentials as credentials_module
    generation = secrets.token_hex(16)
    original_token_hex = credentials_module.secrets.token_hex
    credentials_module.secrets.token_hex = lambda size: generation if size == 16 else original_token_hex(size)
    try:
        store.write(payload)
        pointer = json.loads(backend.read_secret(f"{target}/index"))
        if store.read() != payload:
            raise RuntimeError("credential round-trip mismatch")
        metadata = store.metadata()
        if metadata.persist != 2:
            raise RuntimeError("credential persistence is not LOCAL_MACHINE")
        return {"status": "pass", "store": "Windows Credential Manager", "chunks": pointer["chunks"], "persist": metadata.persist, "secret": "synthetic_only"}
    finally:
        credentials_module.secrets.token_hex = original_token_hex
        chunk_count = (len(payload) + store.chunk_chars - 1) // store.chunk_chars
        cleanup_targets = [store._chunk_target(generation, index) for index in range(chunk_count)]
        cleanup_targets.extend([f"{target}/index", f"{target}/previous"])
        for name in cleanup_targets:
            try:
                backend.delete_secret(name)
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-native", action="store_true")
    args = parser.parse_args()
    if not args.run_native:
        result = {"status": "ready_to_run", "store": "Windows Credential Manager", "secret": "not_supplied", "cleanup": "native_run_required"}
    else:
        result = run_native()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"ready_to_run", "pass", "unsupported_platform"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
