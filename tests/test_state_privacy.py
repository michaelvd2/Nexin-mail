from __future__ import annotations

from imap_plugin.contracts import Classification, MessageRef
from imap_plugin.state import MetadataStore, StateError


def test_native_protected_state_does_not_store_priority_rule_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    path = tmp_path / "operator.sqlite3"
    store = MetadataStore(path)
    sentinel = "sensitive-sender-7841@example.test"
    store.save_priority_rules({"important_senders": [sentinel]})
    assert store.load_priority_rules()["important_senders"] == [sentinel]
    data = path.read_bytes()
    assert sentinel.encode("utf-8") not in data
    assert sentinel.encode("utf-16-le") not in data


def test_send_ledger_blocks_duplicate_and_ambiguous_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    store = MetadataStore(tmp_path / "operator.sqlite3")
    store.record_send_attempt("a" * 64, "attempting", "corr")
    store.update_send_outcome("a" * 64, "ambiguous")
    try:
        store.record_send_attempt("a" * 64, "attempting", "corr2")
    except StateError:
        pass
    else:
        raise AssertionError("ambiguous duplicate was not blocked")


def test_classification_cache_reuses_exact_inputs_and_keeps_transition_history(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    path = tmp_path / "operator.sqlite3"
    store = MetadataStore(path)
    reference = MessageRef("private-account@example.test", "folder_private", 7, 42)
    first = Classification(
        message_ref=reference,
        label="needs_review",
        reason_codes=("reason_b", "reason_a"),
        explanation="Advisory local result.",
        version="phishing-test-v1",
    )
    digest = "a" * 64

    store.save_classification(first, classifier="phishing", input_digest=digest)
    cached = store.load_classification(
        reference,
        classifier="phishing",
        version="phishing-test-v1",
        input_digest=digest,
    )
    assert cached is not None
    assert cached.label == "needs_review"
    assert set(cached.reason_codes) == {"reason_a", "reason_b"}
    assert store.load_classification(
        reference,
        classifier="phishing",
        version="phishing-test-v2",
        input_digest=digest,
    ) is None
    assert store.load_classification(
        reference,
        classifier="phishing",
        version="phishing-test-v1",
        input_digest="b" * 64,
    ) is None

    store.save_classification(first, classifier="phishing", input_digest=digest)
    assert store.classification_cache_stats()["history_events"] == 1

    changed = Classification(
        message_ref=reference,
        label="suspicious",
        reason_codes=("reason_c",),
        explanation="Advisory changed local result.",
        version="phishing-test-v1",
    )
    store.save_classification(changed, classifier="phishing", input_digest=digest)
    assert store.classification_cache_stats() == {
        "current_classifications": 1,
        "history_events": 2,
        "encrypted_assistant_results": 0,
        "history_retention_days": 365,
        "history_max_events": 10000,
        "assistant_result_retention_days": 30,
        "assistant_result_max_entries": 500,
        "stores_mail_content": False,
        "assistant_results_protected_with_native_keystore": True,
        "reference_storage": "sha256",
    }
    persisted = b"".join(file.read_bytes() for file in tmp_path.glob("operator.sqlite3*"))
    assert b"private-account@example.test" not in persisted
    assert b"folder_private" not in persisted


def test_assistant_cache_roundtrip_is_exact_bounded_and_native_protected(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAP_PLUGIN_TEST_MODE", "1")
    path = tmp_path / "operator.sqlite3"
    store = MetadataStore(path)
    reference = MessageRef("assistant-private-account@example.test", "folder_assistant_private", 17, 204)
    related = MessageRef("assistant-private-account@example.test", "folder_assistant_private", 17, 199)
    sentinel = "Private assistant result 9247: planning Tuesday."

    timing = store.save_assistant_result(
        reference,
        action="summary",
        prompt_version="assistant-test-v1",
        result=sentinel,
        sources=[reference, related],
    )
    cached = store.load_assistant_result(
        reference,
        action="summary",
        prompt_version="assistant-test-v1",
    )

    assert cached is not None
    assert cached["result"] == sentinel
    assert cached["sources"] == [reference.as_dict(), related.as_dict()]
    assert cached["created_at"] == timing["created_at"]
    assert store.load_assistant_result(
        reference,
        action="summary",
        prompt_version="assistant-test-v2",
    ) is None
    assert store.classification_cache_stats()["encrypted_assistant_results"] == 1

    persisted = b"".join(file.read_bytes() for file in tmp_path.glob("operator.sqlite3*"))
    for private_value in (sentinel, reference.account_id, reference.folder_id):
        assert private_value.encode("utf-8") not in persisted
        assert private_value.encode("utf-16-le") not in persisted
