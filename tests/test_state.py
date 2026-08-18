from hbdl.state import STATUS_DOWNLOADING, STATUS_FAILED, STATUS_PENDING, STATUS_VERIFIED, StateStore


def test_upsert_and_get_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.upsert("key1", status=STATUS_VERIFIED, dest_path="/tmp/x", file_size=10, hash_algo="sha1", hash_value="abc")

    record = store.get("key1")
    assert record.status == STATUS_VERIFIED
    assert record.hash_value == "abc"
    assert store.is_verified("key1") is True
    store.close()


def test_is_verified_false_for_unknown_key(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    assert store.is_verified("missing") is False
    store.close()


def test_upsert_transitions_status(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.upsert("key1", status=STATUS_VERIFIED, dest_path="/tmp/x", file_size=10, hash_algo="sha1", hash_value="abc")
    store.upsert("key1", status=STATUS_FAILED, dest_path="/tmp/x", last_error="boom")

    record = store.get("key1")
    assert record.status == STATUS_FAILED
    assert record.last_error == "boom"
    # COALESCE keeps prior hash info even though this upsert didn't pass it
    assert record.hash_value == "abc"
    store.close()


def test_reconcile_stale_downloading_resets_to_pending(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.upsert("key1", status=STATUS_DOWNLOADING, dest_path="/tmp/x")
    store.upsert("key2", status=STATUS_VERIFIED, dest_path="/tmp/y", file_size=1)
    store.upsert("key3", status=STATUS_DOWNLOADING, dest_path="/tmp/z")

    reset_count = store.reconcile_stale_downloading()

    assert reset_count == 2
    assert store.get("key1").status == STATUS_PENDING
    assert store.get("key2").status == STATUS_VERIFIED  # untouched
    assert store.get("key3").status == STATUS_PENDING
    store.close()
