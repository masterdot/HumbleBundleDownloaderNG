from hbdl.state import STATUS_FAILED, STATUS_VERIFIED, StateStore


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
