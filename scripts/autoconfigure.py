from __future__ import annotations

import json
import sys

from imap_plugin.autoconfig import AutoConfigurationError, autoconfigure


MAX_REQUEST_BYTES = 16_384


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        print(json.dumps({"status": "error", "error_code": "invalid_request", "message": "The local setup request was too large."}))
        return 64
    password = ""
    try:
        request = json.loads(raw.decode("utf-8"))
        email = str(request.get("email_address", ""))
        password = str(request.get("password", ""))
        hints = request.get("hints")
        if hints is not None and not isinstance(hints, dict):
            raise ValueError("hints must be an object")
        result = autoconfigure(email, password, hints=hints)
        print(json.dumps(result.public_dict(), separators=(",", ":")))
        return 0
    except AutoConfigurationError as exc:
        print(json.dumps(exc.public_dict(), separators=(",", ":")))
        return 20
    except Exception:
        print(json.dumps({
            "status": "error",
            "error_code": "setup_failed",
            "message": "Automatic setup failed safely. No password was logged or written to a configuration file.",
        }, separators=(",", ":")))
        return 1
    finally:
        password = ""


if __name__ == "__main__":
    raise SystemExit(main())
