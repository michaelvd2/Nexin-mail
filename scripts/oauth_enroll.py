from __future__ import annotations

import json
import sys

from imap_plugin.enrollment import enroll_microsoft_native
from imap_plugin.oauth import OAuthError


MAX_REQUEST_BYTES = 4_096


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        print(json.dumps({"status": "error", "error_code": "setup_failed", "message": "The local setup request was too large."}))
        return 64
    try:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError
        if set(request) - {"email_address", "include_smtp"}:
            raise ValueError
        email = request.get("email_address")
        include_smtp = request.get("include_smtp", False)
        if not isinstance(email, str) or not isinstance(include_smtp, bool):
            raise ValueError
        enrollment = enroll_microsoft_native(email, include_smtp=include_smtp)
        print(json.dumps({"status": "configured", **enrollment.public_dict()}, separators=(",", ":")))
        return 0
    except OAuthError as exc:
        print(json.dumps({"status": "error", "error_code": exc.code, "message": exc.public_message}, separators=(",", ":")))
        return 20
    except KeyboardInterrupt:
        print(json.dumps({
            "status": "error",
            "error_code": "oauth_cancelled",
            "message": "Microsoft sign-in was cancelled.",
        }, separators=(",", ":")))
        return 20
    except Exception:
        print(json.dumps({
            "status": "error",
            "error_code": "setup_failed",
            "message": "Microsoft setup could not finish safely. Check the local setup components.",
        }, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
