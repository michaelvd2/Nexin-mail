import json
import subprocess
import sys
import threading
import time

import pytest

from nexin_mail import setup_flow as flow
from imap_plugin.review import SetupError


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_CONFIG", str(tmp_path / "config.toml"))
    calls = []
    monkeypatch.setattr(flow, "_spawn", lambda root, sid: calls.append(sid))
    return flow.session_root(), calls


def test_repeated_start_reuses_the_same_popup_session(session):
    root, calls = session
    one = flow.start()
    two = flow.start(new_attempt=True)
    assert one["session_id"] == two["session_id"]
    assert calls == [one["session_id"]]


def test_wait_timeout_does_not_cancel_or_reopen_form(session):
    root, calls = session
    sid = flow.start()["session_id"]
    shown = threading.Event()
    finish = threading.Event()
    def launch():
        shown.set()
        finish.wait(5)
        return False
    owner = threading.Thread(target=flow.worker, args=(sid,), kwargs={"launch": launch})
    owner.start()
    try:
        assert shown.wait(2)
        assert flow.wait(sid, 0)["status"] == "waiting_for_input"
        assert flow.start()["session_id"] == sid
        assert len(calls) == 1
    finally:
        finish.set()
        owner.join(3)
    assert flow.wait(sid, 0)["status"] == "cancelled"
    assert flow.start()["next_action"] == "stop"


def test_success_continues_with_connection_check_then_dashboard(session):
    sid = flow.start()["session_id"]
    steps = []
    flow.worker(sid, launch=lambda: steps.append("form") or True, check=lambda: steps.append("health"))
    result = flow.wait(sid, 0)
    assert steps == ["form", "health"]
    assert result["status"] == "ready"
    assert result["next_action"] == "render_mail_view"
    assert result["dashboard"] == "not_checked"


def test_failure_returns_typed_recovery_without_secrets_or_retry(session):
    root, calls = session
    sid = flow.start()["session_id"]
    def launch():
        raise SetupError({"error_code": "authentication_failed", "password": "PRIVATE_SENTINEL", "message": "PRIVATE_SENTINEL"})
    flow.worker(sid, launch=launch)
    result = flow.wait(sid, 0)
    assert result["recovery"]["error_code"] == "authentication_failed"
    assert result["recovery"]["recovery"]["automatic_login_retry"] is False
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    assert "PRIVATE_SENTINEL" not in (root / "current.json").read_text()
    flow.start()
    assert len(calls) == 1


def test_lost_worker_does_not_authorize_duplicate_window(session):
    root, calls = session
    sid = flow.start()["session_id"]
    value = flow._read(root)
    flow._write(root, {**value, "status": "waiting_for_input"})
    assert flow.wait(sid, 0)["status"] == "interrupted"
    assert flow.start(new_attempt=True)["next_action"] == "inspect_setup_owner"
    assert len(calls) == 1
    launched = []
    flow.worker(sid, launch=lambda: launched.append(True))
    assert launched == []


def test_wrong_session_cannot_consume_another_result(session):
    flow.start()
    assert flow.wait("f" * 32, 0)["status"] == "session_mismatch"


def test_existing_config_skips_form_and_checks_read_connection(session):
    flow.config_path().write_text("fixture")
    sid = flow.start()["session_id"]
    flow.worker(sid, launch=lambda: pytest.fail("existing account must not be overwritten"), check=lambda: None)
    assert flow.wait(sid, 0)["status"] == "ready"


def test_explicit_new_attempt_can_reopen_failed_setup(session):
    sid = flow.start()["session_id"]
    flow.worker(sid, launch=lambda: False)
    fresh = flow.start(new_attempt=True)
    assert fresh["session_id"] != sid
    assert fresh["status"] == "starting"


def test_wait_resumes_worker_from_separate_process(session):
    sid = flow.start()["session_id"]
    code = "import time; from nexin_mail.setup_flow import worker; worker(%r, launch=lambda: (time.sleep(0.3) or True), check=lambda: None)" % sid
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = flow.wait(sid, 5)
        assert result["status"] == "ready"
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
