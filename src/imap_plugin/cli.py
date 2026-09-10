from __future__ import annotations

import json
import sys

from . import __version__
from .bridge import MailBridge
from .config import config_path, load_settings, state_root
from .credentials import platform_store
from .oauth import OAuthError, oauth_provider_for
from .privacy import trace_schema_is_safe
from .sender import MailSender


def doctor() -> int:
    report: dict[str, object] = {
        "bridge_version": __version__,
        "python": sys.executable,
        "config_path": str(config_path()),
        "config_present": config_path().is_file(),
        "credentials": {
            "imap": {"present": False},
            "smtp": {"present": False},
        },
        "connectivity": "not_checked",
        "smtp_connectivity": "not_checked",
        "mailbox_actions_ready": False,
        "send_ready": False,
        "operator_ready": False,
        "trace_schema_safe": trace_schema_is_safe(state_root() / "logs" / "bridge.jsonl"),
    }
    try:
        settings = load_settings()
        oauth = None
        if settings.microsoft_oauth:
            report["auth_method"] = "microsoft"
            oauth = oauth_provider_for(settings)
            metadata = oauth.cache_metadata()
            report["credentials"]["imap"] = {
                "present": metadata is not None,
                "type": "oauth_cache",
                "persist": metadata.persist if metadata is not None else None,
                "blob_size": metadata.blob_size if metadata is not None else 0,
            }
            store = None
        else:
            store = platform_store()
            metadata = store.metadata(settings.credential_target)
            report["credentials"]["imap"] = {
                "present": True,
                "type": metadata.credential_type,
                "persist": metadata.persist,
                "blob_size": metadata.blob_size,
            }
        health = MailBridge(settings, "read", oauth_token_provider=oauth).tls_and_capabilities()
        report["connectivity"] = "pass" if health["tls"]["verified"] else "fail"
        report["feature_gates"] = health["operator_features"]
        if settings.send_configured:
            if settings.microsoft_oauth:
                smtp_metadata = metadata
                report["credentials"]["smtp"] = {
                    "present": smtp_metadata is not None,
                    "type": "oauth_cache",
                    "persist": smtp_metadata.persist if smtp_metadata is not None else None,
                    "blob_size": smtp_metadata.blob_size if smtp_metadata is not None else 0,
                }
                smtp_health = MailSender(settings, oauth_token_provider=oauth).probe()
            else:
                smtp_metadata = store.metadata(settings.smtp_credential_target)
                report["credentials"]["smtp"] = {
                    "present": True,
                    "type": smtp_metadata.credential_type,
                    "persist": smtp_metadata.persist,
                    "blob_size": smtp_metadata.blob_size,
                }
                smtp_health = MailSender(settings, store.read_secret).probe()
            report["smtp_connectivity"] = "pass" if smtp_health["authenticated"] else "fail"
            report["smtp"] = smtp_health
        gates = health["operator_features"]
        report["mailbox_actions_ready"] = bool(
            report["connectivity"] == "pass"
            and all(gates.get(name) is True for name in ("safe_move", "drafts", "bin"))
        )
        report["send_ready"] = bool(
            report["mailbox_actions_ready"]
            and report["smtp_connectivity"] == "pass"
            and all(gates.get(name) is True for name in ("sent", "send_configured"))
        )
        report["operator_ready"] = report["mailbox_actions_ready"]
    except OAuthError as exc:
        report["error_code"] = exc.code
        report["error_class"] = type(exc).__name__
    except Exception as exc:
        report["error_class"] = type(exc).__name__
    print(json.dumps(report, indent=2))
    credentials = report.get("credentials", {})
    imap = credentials.get("imap", {}) if isinstance(credentials, dict) else {}
    smtp = credentials.get("smtp", {}) if isinstance(credentials, dict) else {}
    return 0 if (
        report.get("connectivity") == "pass"
        and imap.get("persist") == 2
        and (report.get("smtp_connectivity") != "pass" or smtp.get("persist") == 2)
    ) else 1


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["doctor"]):
        print("Only the interactive read-only doctor command is available.", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(doctor())
