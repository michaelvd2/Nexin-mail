from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from imap_plugin import review


def test_native_review_rejects_nested_private_approval_material(monkeypatch):
    called = False

    def unexpected_run(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=0, stdout="CONFIRMED")

    monkeypatch.setattr(review.subprocess, "run", unexpected_run)
    with pytest.raises(review.ReviewError, match="approval material"):
        review.native_review(
            "Save this exact draft",
            {"proposal": {"payload": {"approval_handle": "private-secret"}}},
        )
    assert called is False


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_native_review_sends_only_bounded_json_and_maps_cancel(monkeypatch, system):
    requests = []

    def fake_run(command, *, input, **kwargs):
        requests.append(json.loads(input))
        return SimpleNamespace(returncode=1, stdout="CANCELLED")

    monkeypatch.setattr(review.platform, "system", lambda: system)
    monkeypatch.setattr(review, "os", SimpleNamespace(name="nt" if system == "Windows" else "posix"))
    monkeypatch.setattr(review, "powershell_command", lambda script: ["synthetic-powershell", str(script)])
    monkeypatch.setattr(review.subprocess, "run", fake_run)
    result = review.native_review(
        "Load this exact image",
        {"proposal_id": "0123456789abcdef", "hosts": ["images.example.test"]},
        require_checkbox=True,
    )

    assert result is False
    assert requests[0]["version"] == 1
    assert requests[0]["require_checkbox"] is True
    assert requests[0]["payload"]["proposal_id"] == "0123456789abcdef"
    assert "approval_handle" not in json.dumps(requests[0], ensure_ascii=False)


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_native_review_rejects_oversized_payload_before_launch(monkeypatch, system):
    monkeypatch.setattr(review.platform, "system", lambda: system)
    monkeypatch.setattr(review, "os", SimpleNamespace(name="nt" if system == "Windows" else "posix"))
    monkeypatch.setattr(review, "powershell_command", lambda *args: pytest.fail("host must not launch"))
    monkeypatch.setattr(review.subprocess, "run", lambda *args, **kwargs: pytest.fail("review must not launch"))
    with pytest.raises(review.ReviewError, match="payload"):
        review.native_review("Review", {"body": "x" * 1_500_001})
